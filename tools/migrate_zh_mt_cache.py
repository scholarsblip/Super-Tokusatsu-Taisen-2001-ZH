#!/usr/bin/env python3
"""Reuse exact plain-segment translations after a glossary expansion.

The tokenizer runs first with the new glossary/protected literals. Only a
matching (engine, language, exact source segment) with one unambiguous cached
target may migrate. Newly protected names are reconstructed locally by the
translator and therefore never copied from an old mistranslated name.
Read-only preview unless --write is supplied; the old database is untouched.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sqlite3

import bulk_mt_zh as mt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True)
    p.add_argument('--glossary',required=True)
    p.add_argument('--protect-json',required=True)
    p.add_argument('--old-cache',required=True)
    p.add_argument('--new-cache',required=True)
    p.add_argument('--report')
    p.add_argument('--write',action='store_true')
    a=p.parse_args()
    if Path(a.old_cache).resolve()==Path(a.new_cache).resolve():
        raise ValueError('Old and new cache paths must differ')
    glossary=json.loads(Path(a.glossary).read_text())
    protected=json.loads(Path(a.protect_json).read_text())
    tokenizer=mt.Tokens(glossary,protected)
    segments=set(); samples=[]
    for row in mt.read_records(a.input):
        for value,lang in ((row['text'],row['source_language']),
                           (row['speaker'],row['speaker_language'])):
            if not isinstance(value,str):continue
            parts=tokenizer.parts(value,lang)
            segments.update((part[1],part[2]) for part in parts if part[0]=='mt')
            if len(samples)<5 and any(part[0]=='literal' and part[1].strip() for part in parts):
                samples.append({'uid':row['uid'],'parts':parts})
    old=sqlite3.connect(Path(a.old_cache).resolve().as_uri()+'?mode=ro',uri=True)
    indexed=defaultdict(set)
    for lang,source,target,engine in old.execute('SELECT lang,source,target,engine FROM segments'):
        if engine==mt.ENGINE:indexed[(lang,source)].add(target)
    old.close()
    reuse={key:next(iter(indexed[key])) for key in segments if len(indexed[key])==1}
    report={'mode':'write' if a.write else 'dry_run','new_config_sha256':tokenizer.config,
            'unique_segments':len(segments),'exact_cached_segments':len(reuse),
            'uncached_segments':len(segments)-len(reuse),
            'ambiguous_cache_matches':sum(len(indexed[key])>1 for key in segments),
            'source_engine_and_language_must_match':True,'samples':samples}
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    if a.write:
        cache=mt.Cache(a.new_cache,tokenizer.config)
        bylang=defaultdict(list)
        for (lang,source),target in reuse.items():
            bylang[lang].append((source,target))
        for lang,pairs in bylang.items():cache.put(lang,pairs)
        assert all(cache.get(lang,source)==target for (lang,source),target in reuse.items())
        cache.db.close()
    if a.report:
        Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
