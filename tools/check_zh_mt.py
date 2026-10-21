"""Token-safe glossary application and validation for Chinese MT drafts.

Read-only by default. This validates text data, not font/layout or game behavior.
Use --self-test for the token/ID safety checks, or pass source and target JSON/
JSONL files. --apply-terms-output writes a separate draft copy; an existing
output is never overwritten. Import apply_terms() for a batch translator.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GLOSSARY = ROOT / 'work/glossary/zh_CN_machine_terms.json'
DEFAULT_ID_TRANSFORMS = ROOT / 'work/glossary/zh_CN_identifier_transforms.json'
CONTROL_RE = re.compile(r'<[^<>]*>|\[(?:HERO[1-4]|VAR[56])\]|\{[^{}]*\}')
URL_RE = r'https?://[^\s<>]+'
PATH_RE = r'(?:[A-Za-z]:[\\/]|(?:[A-Za-z0-9_.-]+[\\/])+)[A-Za-z0-9_.\\/-]+'
STRUCTURED_ID_RE = r'(?<![A-Za-z0-9_])(?:[A-Za-z]+[A-Za-z0-9]*[-_][A-Za-z0-9_-]*[0-9][A-Za-z0-9_-]*|[A-Za-z]+[0-9]+[A-Za-z0-9_-]*)(?![A-Za-z0-9_])'
KNOWN_IDS = ('UCMA','SIDO','TDF','EATER','NAAGER','VOL','EAGLE','BF','SSI','SRI',
             'MAC','MAT','TAC','SSSP','HP','EN','EXP','LV','SP','MAP','RX','BLACK')
ID_RE = re.compile(r'(?<![A-Za-z0-9_])(?:' + '|'.join(KNOWN_IDS) + r')(?![A-Za-z0-9_])|' + STRUCTURED_ID_RE)
PROTECTED_RE = re.compile(URL_RE + '|' + PATH_RE + '|' + CONTROL_RE.pattern + '|' + ID_RE.pattern)
KANA_RE = re.compile(r'[\u3040-\u30ff\uff66-\uff9f]')


def control_tokens(text):
    return CONTROL_RE.findall(text or '')


def protected_ids(text):
    """IDs, asset paths and URLs; ordinary capitalized proper names are not IDs."""
    spans = re.compile(URL_RE + '|' + PATH_RE + '|' + ID_RE.pattern)
    return [m.group() for m in spans.finditer(CONTROL_RE.sub('', text or ''))]


def latin_fragments(text):
    readable=PROTECTED_RE.sub('',text or '')
    return sorted(set(re.findall(r'[A-Za-z]{2,}(?:[\u0027\u2019-][A-Za-z]+)*',readable)))


def load_glossary(path=DEFAULT_GLOSSARY):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def load_id_transforms(path=DEFAULT_ID_TRANSFORMS):
    """Read explicit readable-text exceptions; none can waive control tokens.

    Each exception is pinned to one UID and the complete chosen source hash.
    Required target evidence and exact lost-token counts keep aliases from
    becoming a generic bypass for labels such as HP, EN or asset IDs.
    """
    path=Path(path)
    if not path.exists():return {'rules':[]}
    policy=json.loads(path.read_text(encoding='utf-8'))
    seen=set()
    for rule in policy.get('rules',[]):
        key=(rule['uid'],rule['lost_id'])
        if key in seen:raise ValueError('Duplicate accepted ID transform: '+str(key))
        seen.add(key)
        if not re.fullmatch(r'[0-9a-f]{64}',rule['source_sha256']):
            raise ValueError('Accepted ID transform needs source SHA256: '+str(key))
        if not isinstance(rule['lost_count'],int) or rule['lost_count']<1:
            raise ValueError('Invalid accepted ID transform count: '+str(key))
        if not rule.get('target_evidence') or not all(
            isinstance(e.get('text'),str) and e['text'] and
            isinstance(e.get('count'),int) and e['count']>=1
            for e in rule['target_evidence']):
            raise ValueError('Accepted ID transform needs target evidence: '+str(key))
    return {**policy,'policy_file':path.name,
            'policy_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def accept_id_losses(uid,original,translated,lost,policy):
    remaining=lost.copy();accepted=[]
    source_sha=hashlib.sha256(original.encode('utf-8')).hexdigest()
    for rule in policy.get('rules',[]):
        if rule['uid']!=uid or rule['source_sha256']!=source_sha:
            continue
        token=rule['lost_id'];count=rule['lost_count']
        if remaining[token]!=count:
            continue
        if not all(translated.count(e['text'])>=e['count'] for e in rule['target_evidence']):
            continue
        evidence=rule.get('glossary_evidence')
        if evidence:
            # A composite display label may contain a translated character
            # name, but only its source-pinned rule and frozen canonical files
            # can authorize this. No arbitrary name/path matching is waived.
            checked=[]
            for item in evidence.get('files',[]):
                path=Path(item['path'])
                if not path.is_file():break
                data=path.read_bytes()
                if hashlib.sha256(data).hexdigest()!=item['sha256']:break
                checked.append(path)
            if len(checked)!=len(evidence.get('files',[])) or not checked:
                continue
            flat=json.loads(checked[-1].read_text(encoding='utf-8'))
            if flat.get(evidence['alias'])!=evidence['zh_CN']:
                continue
        remaining[token]-=count
        accepted.append({k:rule[k] for k in
                         ('uid','source_sha256','lost_id','lost_count','target_evidence','reason','glossary_evidence') if k in rule})
    return +remaining,accepted


def _alias_pattern(alias, lang):
    escaped = re.escape(alias)
    if lang == 'en':
        return r'(?<![A-Za-z0-9_])' + escaped + r'(?![A-Za-z0-9_])'
    return escaped


def apply_terms(text, glossary=None):
    """Apply longest exact aliases in readable spans, never protected content.

    Targets are applied once, so replacements cannot cascade. Latin boundaries
    exclude word/ID substrings. Japanese aliases are explicit multi-character
    names; particles need no artificial word boundary. Returns(text, changes).
    """
    glossary = load_glossary() if glossary is None else glossary
    aliases = []
    for term in glossary.get('terms', []):
        for lang, values in term.get('aliases', {}).items():
            for alias in values:
                if not alias or alias == term['zh_CN']:
                    continue
                if lang == 'ja' and len(alias) < 2:
                    continue
                aliases.append((alias, lang, term['zh_CN'], term['id']))
    # Deduplicate only identical semantics; a conflicting alias is an error.
    seen = {}
    for alias, lang, target, ident in aliases:
        key = (alias, lang)
        if key in seen and seen[key][0] != target:
            raise ValueError('Conflicting glossary alias: ' + alias)
        seen[key] = (target, ident)
    entries = sorted(((a, l, t, i) for (a,l),(t,i) in seen.items()),
                     key=lambda x: (-len(x[0]), x[0], x[1]))
    if not entries:
        return text, []
    pattern = re.compile('|'.join('(?P<T%d>%s)' % (n, _alias_pattern(a,l))
                                  for n,(a,l,t,i) in enumerate(entries)))
    changes = []
    def replace(match):
        index = int(match.lastgroup[1:])
        alias, lang, target, ident = entries[index]
        changes.append({'term':ident,'from':match.group(),'to':target})
        return target
    parts = []; pos = 0
    for protected in PROTECTED_RE.finditer(text):
        parts.append(pattern.sub(replace, text[pos:protected.start()]))
        parts.append(protected.group()); pos = protected.end()
    parts.append(pattern.sub(replace, text[pos:]))
    result = ''.join(parts)
    assert control_tokens(result) == control_tokens(text), 'Glossary changed controls'
    assert protected_ids(result) == protected_ids(text), 'Glossary changed IDs/paths'
    return result, changes


def load_rows(path):
    p = Path(path)
    if p.suffix.lower() == '.jsonl':
        return [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]
    data = json.loads(p.read_text(encoding='utf-8'))
    if isinstance(data, list):
        return data
    for key in ('rows','units','translations'):
        if isinstance(data.get(key), list):
            return data[key]
    if all(isinstance(v, dict) for v in data.values()):
        return [dict(v,uid=v.get('uid',k)) for k,v in data.items()]
    raise ValueError('Expected a row list, rows/units/translations, or UID dictionary: ' + str(p))


def row_uid(row):
    return str(row.get('uid', row.get('id', '')))


def text_of(row, field=None, target=False):
    if field:
        value = row.get(field)
        return value if isinstance(value,str) else ''
    keys = ('zh_CN','translated_text','translation','text') if target else ('jp','ja','source_ja','source_text','source','text','en')
    for key in keys:
        if isinstance(row.get(key),str):
            return row[key]
    return ''


def validate_rows(source_rows, target_rows, source_field=None, target_field=None,
                  accepted_transforms=None):
    """Check exact UID coverage and immutable runtime data; warnings are drafts."""
    errors=[]; warnings=[]; source={}; target={};accepted=[]
    policy=load_id_transforms() if accepted_transforms is None else accepted_transforms
    for label, rows, destination in [('source',source_rows,source),('target',target_rows,target)]:
        for row in rows:
            uid=row_uid(row)
            if not uid:
                errors.append({'kind':'missing_uid','side':label}); continue
            if uid in destination:
                errors.append({'kind':'duplicate_uid','side':label,'uid':uid})
            destination[uid]=row
    missing=sorted(set(source)-set(target)); extra=sorted(set(target)-set(source))
    errors.extend({'kind':'missing_target','uid':u} for u in missing)
    errors.extend({'kind':'extra_target','uid':u} for u in extra)
    for uid in sorted(set(source)&set(target)):
        original=text_of(source[uid],source_field); translated=text_of(target[uid],target_field,True)
        if original.strip() and not translated.strip():
            errors.append({'kind':'empty_translation','uid':uid})
        a,b=control_tokens(original),control_tokens(translated)
        if a!=b:
            errors.append({'kind':'control_sequence_changed','uid':uid,'source':a,'target':b})
        a,b=Counter(protected_ids(original)),Counter(protected_ids(translated))
        lost,used=accept_id_losses(uid,original,translated,a-b,policy)
        accepted+=used
        if lost:
            errors.append({'kind':'protected_id_lost','uid':uid,'lost':list(lost.elements())})
        if b-a:
            warnings.append({'kind':'new_protected_id','uid':uid,'added':list((b-a).elements())})
        if KANA_RE.search(CONTROL_RE.sub('',translated)):
            warnings.append({'kind':'kana_in_machine_draft','uid':uid})
        latin=latin_fragments(translated)
        if latin:
            warnings.append({'kind':'latin_in_machine_draft','uid':uid,'fragments':latin[:20]})
        if '\\n' in translated and '\\n' not in original:
            warnings.append({'kind':'literal_backslash_n_added','uid':uid})
        if source[uid].get('source_hash') and target[uid].get('source_hash') and source[uid]['source_hash']!=target[uid]['source_hash']:
            errors.append({'kind':'source_hash_changed','uid':uid})
        source_speaker=None;has_source_speaker=False
        for sk,tk in [('speaker_jp','speaker_zh_CN'),('source_speaker','speaker_zh_CN'),('speaker','speaker_zh_CN')]:
            if sk in source[uid] and tk in target[uid]:
                source_speaker=source[uid][sk];has_source_speaker=True
                target_speaker=target[uid].get(tk)
                if (source_speaker is None)!=(target_speaker is None):
                    errors.append({'kind':'speaker_null_state_changed','uid':uid})
                if control_tokens(source_speaker)!=control_tokens(target_speaker):
                    errors.append({'kind':'speaker_control_changed','uid':uid})
                if isinstance(source_speaker,str) and source_speaker.strip() and not (target_speaker or '').strip():
                    errors.append({'kind':'empty_speaker_translation','uid':uid})
                if KANA_RE.search(CONTROL_RE.sub('',target_speaker or '')):
                    warnings.append({'kind':'kana_in_speaker_draft','uid':uid})
                latin=latin_fragments(target_speaker)
                if latin:warnings.append({'kind':'latin_in_speaker_draft','uid':uid,'fragments':latin[:20]})
                break
        metadata=target[uid].get('mt')
        if isinstance(metadata,dict):
            expected=hashlib.sha256(original.encode('utf-8')).hexdigest()
            if metadata.get('source_sha256')!=expected:
                errors.append({'kind':'mt_source_sha256_mismatch','uid':uid})
            if has_source_speaker:
                expected=hashlib.sha256(source_speaker.encode('utf-8')).hexdigest() if isinstance(source_speaker,str) else None
                if metadata.get('speaker_source_sha256')!=expected:
                    errors.append({'kind':'mt_speaker_sha256_mismatch','uid':uid})
            if source[uid].get('source_provenance') is not None and metadata.get('source_provenance')!=source[uid]['source_provenance']:
                errors.append({'kind':'mt_source_provenance_mismatch','uid':uid})
    return {'status':'pass' if not errors else 'fail','source_units':len(source),
            'target_units':len(target),'matched_units':len(set(source)&set(target)),
            'missing_units':len(missing),'extra_units':len(extra),'errors':errors,
            'warnings':warnings,'warning_counts':dict(Counter(x['kind'] for x in warnings)),
            'accepted_id_transforms':accepted,
            'accepted_id_transform_counts':dict(Counter(x['reason'] for x in accepted)),
            'accepted_id_transform_policy':{k:policy[k] for k in
                                            ('policy_file','policy_sha256') if k in policy},
            'not_verified':['translation meaning','font coverage','layout','game insertion/runtime']}


def self_test():
    glossary={'terms':[{'id':'shocker','aliases':{'en':['Shocker'],'ja':['ショッカー']},'zh_CN':'修卡'}]}
    text='<c3>[HERO2]</c> Shocker Shockers UCMA STAGE0005 {FF05} https://a/Shocker EVENT/Shocker.bin'
    out,changes=apply_terms(text,glossary)
    assert '修卡 Shockers' in out and 'https://a/Shocker' in out and 'EVENT/Shocker.bin' in out
    assert len(changes)==1
    good=[{'uid':'U1','zh_CN':'<c3>[HERO2]</c>修卡 UCMA STAGE0005 {FF05}'}]
    source=[{'uid':'U1','jp':'<c3>[HERO2]</c>ショッカー UCMA STAGE0005 {FF05}'}]
    assert validate_rows(source,good)['status']=='pass'
    bad=[{'uid':'U1','zh_CN':'[HERO1]修卡 UCMA STAGE0006'}]
    kinds={x['kind'] for x in validate_rows(source,bad)['errors']}
    assert {'control_sequence_changed','protected_id_lost'}<=kinds
    assert validate_rows(source,[])['missing_units']==1
    alias_source=[{'uid':'Alias1','text':'NAAGER'}]
    alias_target=[{'uid':'Alias1','zh_CN':'纳伽'}]
    rule={'uid':'Alias1','source_sha256':hashlib.sha256(b'NAAGER').hexdigest(),
          'lost_id':'NAAGER','lost_count':1,'target_evidence':[{'text':'纳伽','count':1}],
          'reason':'source_pinned_name_alias'}
    policy={'rules':[rule]}
    checked=validate_rows(alias_source,alias_target,'text','zh_CN',policy)
    assert checked['status']=='pass' and len(checked['accepted_id_transforms'])==1
    assert validate_rows(alias_source,[{'uid':'Alias1','zh_CN':'纳格'}],
                         'text','zh_CN',policy)['status']=='fail'
    assert validate_rows([{'uid':'Alias1','text':'NAAGER changed'}],alias_target,
                         'text','zh_CN',policy)['status']=='fail'
    assert validate_rows([{'uid':'Alias2','text':'NAAGER'}],[{'uid':'Alias2','zh_CN':'纳伽'}],
                         'text','zh_CN',policy)['status']=='fail'
    assert validate_rows([{'uid':'Alias1','text':'NAAGER NAAGER'}],alias_target,
                         'text','zh_CN',policy)['status']=='fail'
    with tempfile.TemporaryDirectory(prefix='stt-canonical-evidence-') as folder:
        flat=Path(folder)/'terms.flat.json'
        flat.write_text(json.dumps({'NAAGER':'纳伽'}),encoding='utf-8')
        linked={**rule,'glossary_evidence':{'alias':'NAAGER','zh_CN':'纳伽',
                'files':[{'path':str(flat),'sha256':hashlib.sha256(flat.read_bytes()).hexdigest()}]}}
        assert validate_rows(alias_source,alias_target,'text','zh_CN',{'rules':[linked]})['status']=='pass'
        flat.write_text(json.dumps({'NAAGER':'纳格'}),encoding='utf-8')
        assert validate_rows(alias_source,alias_target,'text','zh_CN',{'rules':[linked]})['status']=='fail'
    return {'status':'pass','checks':['controls','URL/path protection','ID protection','Latin boundaries','coverage','negative corruption detection',
                                      'UID/source-hash/count/target-evidence pinned aliases','frozen canonical glossary hash enforcement']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',nargs='?');parser.add_argument('target',nargs='?')
    parser.add_argument('--source-field');parser.add_argument('--target-field')
    parser.add_argument('--glossary',default=str(DEFAULT_GLOSSARY));parser.add_argument('--report')
    parser.add_argument('--accepted-id-transforms',default=str(DEFAULT_ID_TRANSFORMS))
    parser.add_argument('--apply-terms-output');parser.add_argument('--self-test',action='store_true')
    args=parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(),indent=2));return
    if not args.source or not args.target:
        parser.error('source and target are required unless --self-test is used')
    source=load_rows(args.source);target=load_rows(args.target)
    changes=[]
    if args.apply_terms_output:
        glossary=load_glossary(args.glossary)
        for row in target:
            value=text_of(row,args.target_field,True);new,edits=apply_terms(value,glossary)
            key=args.target_field or next((k for k in ('zh_CN','translated_text','translation','text') if isinstance(row.get(k),str)),'zh_CN')
            row[key]=new
            if edits:changes.append({'uid':row_uid(row),'changes':edits})
        p=Path(args.apply_terms_output)
        if p.exists():raise FileExistsError('Refusing to overwrite '+str(p))
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps({'language':'zh_CN','status':'machine_draft','rows':target},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report=validate_rows(source,target,args.source_field,args.target_field,
                         load_id_transforms(args.accepted_id_transforms))
    report['glossary_changed_rows']=len(changes);report['glossary_change_examples']=changes[:20]
    if args.report:
        p=Path(args.report);p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={k:v for k,v in report.items() if k not in ('errors','warnings','accepted_id_transforms')}
    summary['accepted_id_transform_rules_used']=len(report['accepted_id_transforms'])
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if report['errors']:
        print(json.dumps(report['errors'][:20],ensure_ascii=False,indent=2));raise SystemExit(1)


if __name__=='__main__':main()
