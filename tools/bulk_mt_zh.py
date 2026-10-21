#!/usr/bin/env python3
"""Resumable Google machine baseline; local control/glossary preservation.

Input JSONL: {uid,text,source_language:'ja'|'en',speaker?:str}. Existing Z
translations are skipped, never modified. Without --write/--probe this only
describes a plan. --probe N translates N rows to a preview, not final batches.
Only standard-library modules are required. No account/API key is used.
"""
from __future__ import annotations
import argparse
import concurrent.futures as futures
import hashlib
import http.client
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ENGINE='google-translate-public-dict-chrome-ex/zh-CN/local-controls-v1'
BASE='https://translate.googleapis.com/translate_a/t'
CONTROL=re.compile(r'<[^<>]*>|\[(?:HERO[1-4]|VAR[56])\]|\{[^{}]*\}')
ASSET=r'(?:https?://[^\s<>]+|[A-Za-z]:[\\/][^\s<>]+|\b[A-Za-z0-9_./\\-]+\.(?:DAT|TIM|BIN|STR|XA|ISO|CHD|CUE)\b|\b(?:STAGE|MAPMAIN|EVENT|BATTLE|WAZA|SLPS)[_ .-]?\d+\b|\b[A-Z]{1,8}[-_]\d+[A-Z0-9_-]*\b)'
HAN=re.compile(r'[\u3040-\u30ff\u3400-\u9fffA-Za-z]')

def digest(s):return hashlib.sha256(s.encode('utf-8')).hexdigest()
def dump_atomic(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
    tmp.replace(path)

def read_records(path):
    path=Path(path)
    if path.suffix=='.jsonl':raw=[json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
    else:
        raw=json.loads(path.read_text(encoding='utf-8'))
        if isinstance(raw,dict):raw=raw.get('rows',raw.get('units'))
    if not isinstance(raw,list):raise ValueError('Input must contain a list of records')
    result=[];seen=set()
    for r in raw:
        uid=r['uid'];assert uid not in seen,('duplicate UID',uid);seen.add(uid)
        text=r.get('text',r.get('source',r.get('jp')))
        if not isinstance(text,str):raise ValueError('Missing source text for '+uid)
        lang=r.get('source_language','ja')
        if lang not in ('ja','en','auto'):raise ValueError('Unsupported source_language '+lang)
        speaker=r.get('speaker',r.get('speaker_jp'))
        result.append({'uid':uid,'text':text,'speaker':speaker,'source_language':lang,
                       'speaker_language':r.get('speaker_language',lang),
                       'source_provenance':r.get('source_provenance'),
                       'metadata':{k:r[k] for k in ('count','first','sources') if k in r}})
    return result

class Tokens:
    def __init__(self,glossary,protected):
        self.glossary=glossary
        terms=sorted(set(glossary)|set(protected),key=lambda x:(-len(x),x))
        escaped=[]
        for t in terms:
            if not t:continue
            q=re.escape(t)
            if t[0].isascii() and t[0].isalnum():q=r'(?<![A-Za-z0-9_])'+q
            if t[-1].isascii() and t[-1].isalnum():q+=r'(?![A-Za-z0-9_])'
            escaped.append(q)
        self.pattern=re.compile(CONTROL.pattern+'|(?i:'+ASSET+')'+('|'+('|'.join(escaped)) if escaped else ''))
        self.config=digest(json.dumps({'glossary':glossary,'protected':sorted(protected)},ensure_ascii=False,sort_keys=True))
    def parts(self,text,lang):
        out=[];at=0
        def plain(s):
            # Newlines and surrounding whitespace are reconstructed locally.
            for x in re.split(r'(\r\n|\n|\r)',s):
                if not x:continue
                if x in ('\r\n','\n','\r'):out.append(('literal',x));continue
                m=re.fullmatch(r'(\s*)(.*?)(\s*)',x,re.S);a,b,c=m.groups()
                if a:out.append(('literal',a))
                if b:out.append(('mt',lang,b) if HAN.search(b) else ('literal',b))
                if c:out.append(('literal',c))
        for m in self.pattern.finditer(text):
            plain(text[at:m.start()]);v=m.group(0)
            out.append(('literal',self.glossary.get(v,v)));at=m.end()
        plain(text[at:]);return out

class Cache:
    def __init__(self,path,config):
        self.lock=threading.Lock();self.config=config
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS segments (key TEXT PRIMARY KEY, lang TEXT, source TEXT, target TEXT, engine TEXT, created REAL)')
        self.db.commit()
    def key(self,lang,text):return digest(ENGINE+'\0'+self.config+'\0'+lang+'\0'+text)
    def get(self,lang,text):
        with self.lock:r=self.db.execute('SELECT target FROM segments WHERE key=?',(self.key(lang,text),)).fetchone()
        return r[0] if r else None
    def put(self,lang,pairs):
        with self.lock:
            self.db.executemany('INSERT OR REPLACE INTO segments VALUES (?,?,?,?,?,?)',
              [(self.key(lang,s),lang,s,t,ENGINE,time.time()) for s,t in pairs]);self.db.commit()

class Translator:
    def __init__(self,cache,interval=.67,retries=5,timeout=40):
        self.cache=cache;self.interval=interval;self.retries=retries;self.timeout=timeout
        self.lock=threading.Lock();self.next_request=0.;self.requests=0;self.splits=0
        self.stop=threading.Event()
    def request(self,texts,lang):
        payload=urllib.parse.urlencode([('client','dict-chrome-ex'),('sl',lang),('tl','zh-CN')]+[('q',s) for s in texts])
        for attempt in range(self.retries+1):
            if self.stop.is_set():raise RuntimeError('Rate-limit circuit breaker open; cached progress can be resumed later')
            with self.lock:
                now=time.monotonic();delay=max(0,self.next_request-now);self.next_request=max(now,self.next_request)+self.interval
                self.requests+=1
            if delay:time.sleep(delay)
            try:
                req=urllib.request.Request(BASE+'?'+payload,headers={'User-Agent':'Mozilla/5.0'})
                with urllib.request.urlopen(req,timeout=self.timeout) as f:
                    try:raw=f.read()
                    except http.client.IncompleteRead as e:
                        # Some intermediaries omit the final HTTP chunk marker.
                        # Accept only a fully parseable JSON response; partial
                        # JSON instead raises below and retries the same input.
                        raw=e.partial
                    data=json.loads(raw)
                if not isinstance(data,list) or len(data)!=len(texts):raise ValueError('Response count differs from input')
                result=[x if isinstance(x,str) else x[0] if isinstance(x,list) and x and isinstance(x[0],str) else None for x in data]
                if any(x is None or (s.strip() and not x.strip()) for s,x in zip(texts,result)):raise ValueError('Empty/invalid translation')
                # A control-looking sequence must not be invented by the service.
                if any(CONTROL.search(x) for x in result):raise ValueError('Unexpected control token in machine text')
                return result
            except urllib.error.HTTPError as e:
                if e.code in (400,413,414):raise ValueError('Batch too large/rejected') from e
                if attempt==self.retries and e.code==429:self.stop.set()
                if e.code not in (429,500,502,503,504) or attempt==self.retries:raise
                retry=e.headers.get('Retry-After','')
                delay=float(retry) if retry.isdigit() else min(120,10*2**attempt)
                with self.lock:self.next_request=max(self.next_request,time.monotonic()+delay)
                time.sleep(delay)
            except (urllib.error.URLError,http.client.HTTPException,json.JSONDecodeError,UnicodeDecodeError,TimeoutError,ConnectionError) as e:
                if attempt==self.retries:raise
                time.sleep(min(30,2**attempt))
        raise RuntimeError('Retries exhausted')
    def batch(self,lang,texts):
        try:
            targets=self.request(texts,lang)
            self.cache.put(lang,list(zip(texts,targets)))
            return len(texts)
        except ValueError:
            if len(texts)==1:raise
            self.splits+=1;mid=len(texts)//2
            return self.batch(lang,texts[:mid])+self.batch(lang,texts[mid:])

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True);p.add_argument('--output-dir',required=True)
    p.add_argument('--cache',required=True);p.add_argument('--existing',nargs='*',default=[])
    p.add_argument('--glossary');p.add_argument('--protect',action='append',default=[])
    p.add_argument('--protect-json');p.add_argument('--workers',type=int,default=3)
    p.add_argument('--batch-chars',type=int,default=3000);p.add_argument('--batch-items',type=int,default=80)
    p.add_argument('--request-interval',type=float,default=.67);p.add_argument('--retries',type=int,default=5)
    p.add_argument('--timeout',type=float,default=40);p.add_argument('--rows-per-file',type=int,default=80)
    p.add_argument('--probe',type=int,default=0);p.add_argument('--limit',type=int)
    p.add_argument('--preview-file');p.add_argument('--write',action='store_true')
    a=p.parse_args();assert 1<=a.workers<=4;assert not(a.write and a.probe)
    records=read_records(a.input);skip=set()
    for path in a.existing:
        old=json.loads(Path(path).read_text(encoding='utf-8'))
        if isinstance(old,dict):old=old.get('rows',[])
        skip.update(x['uid'] for x in old)
    active=[r for r in records if r['uid'] not in skip]
    if a.limit is not None:active=active[:a.limit]
    if a.probe:active=active[:a.probe]
    glossary=json.loads(Path(a.glossary).read_text(encoding='utf-8')) if a.glossary else {}
    if not isinstance(glossary,dict) or not all(isinstance(x,str) and isinstance(y,str) for x,y in glossary.items()):raise ValueError('Glossary must be a flat string-to-string mapping')
    protected=a.protect+(json.loads(Path(a.protect_json).read_text()) if a.protect_json else [])
    tokenizer=Tokens(glossary,protected)
    plans=[];segments={}
    for r in active:
        body=tokenizer.parts(r['text'],r['source_language'])
        speaker=tokenizer.parts(r['speaker'],r['speaker_language']) if isinstance(r['speaker'],str) else None
        plans.append((r,body,speaker))
        for parts in (body,speaker or []):
            for part in parts:
                if part[0]=='mt':segments[(part[1],part[2])]=None
    summary={'input_rows':len(records),'preserved_existing_uids':len(skip),'active_rows':len(active),'unique_readable_segments':len(segments),'source_characters':sum(len(r['text']) for r in active),'engine':ENGINE,'status':'plan'}
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    if not a.write and not a.probe:
        print(json.dumps({'sample':active[:3]},ensure_ascii=False,indent=1));return
    cache=Cache(a.cache,tokenizer.config);jobs=[];bylang={}
    for lang,text in segments:
        if cache.get(lang,text) is None:bylang.setdefault(lang,[]).append(text)
    for lang,texts in bylang.items():
        batch=[];chars=0
        for text in texts:
            url_length=len(urllib.parse.urlencode([('q',x) for x in batch+[text]]))
            if batch and (len(batch)>=a.batch_items or chars+len(text)>a.batch_chars or url_length>14000):jobs.append((lang,batch));batch=[];chars=0
            batch.append(text);chars+=len(text)
        if batch:jobs.append((lang,batch))
    tr=Translator(cache,a.request_interval,a.retries,a.timeout);errors=[];done=0;started=time.monotonic()
    with futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        tasks={pool.submit(tr.batch,lang,texts):(lang,texts) for lang,texts in jobs}
        for task in futures.as_completed(tasks):
            try:done+=task.result()
            except Exception as e:errors.append({'lang':tasks[task][0],'source_hashes':[digest(s) for s in tasks[task][1]],'error':type(e).__name__+': '+str(e)})
            if (done and done%500<80) or errors:print(json.dumps({'completed_new_segments':done,'requests':tr.requests,'errors':len(errors),'seconds':round(time.monotonic()-started,1)}),flush=True)
    def assemble(parts):
        if parts is None:return None
        result=[]
        for part in parts:
            value=part[1] if part[0]=='literal' else cache.get(part[1],part[2])
            if value is None:raise ValueError('Untranslated segment')
            result.append(value)
        return ''.join(result)
    out=[];incomplete=[]
    for r,body,speaker in plans:
        try:
            target=assemble(body);sp=assemble(speaker)
            assert CONTROL.findall(target)==CONTROL.findall(r['text']),(r['uid'],'control stream differs')
            if isinstance(r['speaker'],str):assert CONTROL.findall(sp)==CONTROL.findall(r['speaker'])
            out.append({'uid':r['uid'],'zh_CN':target,'speaker_zh_CN':sp,'mt':{'status':'machine_unreviewed','engine':ENGINE,'source_language':r['source_language'],'source_sha256':digest(r['text']),'speaker_source_sha256':digest(r['speaker']) if isinstance(r['speaker'],str) else None,'glossary_sha256':tokenizer.config,'source_provenance':r['source_provenance'],'controls_verified':True},**r['metadata']})
        except (ValueError,AssertionError) as e:incomplete.append({'uid':r['uid'],'error':str(e)})
    summary.update({'status':'complete_machine_unreviewed' if not incomplete else 'incomplete','completed_rows':len(out),'incomplete_rows':incomplete,'request_errors':errors,'http_requests':tr.requests,'split_batches':tr.splits,'seconds':round(time.monotonic()-started,2)})
    if a.probe:
        preview={'summary':summary,'rows':out}
        if a.preview_file:dump_atomic(a.preview_file,preview)
        print(json.dumps({'summary':summary,'preview_file':a.preview_file,'sample':out[:3]},ensure_ascii=False,indent=1))
    else:
        dest=Path(a.output_dir)
        # Never write Z files, and never silently overwrite another corpus run.
        dest.mkdir(parents=True,exist_ok=True)
        for index in range(0,len(plans),a.rows_per_file):
            uids={x[0]['uid'] for x in plans[index:index+a.rows_per_file]}
            rows=[r for r in out if r['uid'] in uids]
            dump_atomic(dest/('M%04d.json'%(index//a.rows_per_file+1)),{'language':'zh_CN','engine':ENGINE,'status':'machine_unreviewed','rows':rows})
        dump_atomic(dest/'manifest.json',summary)
        print(json.dumps(summary,ensure_ascii=False,indent=1),flush=True)
    if incomplete:raise SystemExit(2)

if __name__=='__main__':main()
