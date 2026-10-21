#!/usr/bin/env python3
"""Independently audit canonical literals, metadata and complete MT coverage.

This is a read-only check. It never changes translation rows or source files.
Canonical target-presence checks do not replace human meaning review.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from bulk_mt_zh import Tokens
import export_zh_translation as exporter


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def expected_literals(text, tokenizer, glossary):
    counts=Counter();aliases={}
    for match in tokenizer.pattern.finditer(text or ''):
        alias=match.group()
        if alias not in glossary or alias==glossary[alias]:
            continue
        target=glossary[alias];counts[target]+=1
        aliases.setdefault(target,set()).add(alias)
    return counts,{target:sorted(values) for target,values in aliases.items()}


def audit(args):
    prepared=exporter.prepare(args.input,args.machine_dir,args.prototype_dir,
                              args.expected_units,248)
    glossary=json.loads(Path(args.glossary).read_text(encoding='utf-8'))
    protected=json.loads(Path(args.protect_json).read_text(encoding='utf-8'))
    tokenizer=Tokens(glossary,protected)
    targets={r['uid']:r for r in prepared['merged']}
    errors=[];prototype_gaps=[];stats=Counter();term_counts={}
    for number,source in enumerate(prepared['source'],1):
        uid=source['uid'];target=targets.get(uid)
        if target is None:continue # Coverage errors are already recorded.
        prototype=uid in prepared['baseline']
        if not prototype:
            metadata=target.get('mt',{})
            if metadata.get('glossary_sha256')!=tokenizer.config:
                errors.append({'kind':'canonical_glossary_config_mismatch','uid':uid})
            if metadata.get('source_language')!=source.get('source_language'):
                errors.append({'kind':'source_language_metadata_mismatch','uid':uid})
            if metadata.get('status')!='machine_unreviewed' or metadata.get('controls_verified') is not True:
                errors.append({'kind':'machine_status_metadata_mismatch','uid':uid})
            stats['machine_metadata_rows_checked']+=1
        for field,sfield,tfield in [('body','text','zh_CN'),('speaker','speaker','speaker_zh_CN')]:
            expected,aliases=expected_literals(source.get(sfield),tokenizer,glossary)
            if expected:stats[('prototype_' if prototype else 'machine_')+field+'_rows_with_aliases']+=1
            translated=target.get(tfield) or ''
            for canonical,count in expected.items():
                scope=('prototype_' if prototype else 'machine_')+field
                actual=translated.count(canonical)
                stats[scope+'_expected_alias_occurrences']+=count
                stats[scope+'_target_pairs_checked']+=1
                stats[scope+'_minimum_target_literals_found']+=min(count,actual)
                term_counts.setdefault(canonical,Counter())[scope+'_expected']+=count
                if actual<count:
                    item={'kind':'canonical_literal_absent','uid':uid,'field':field,
                          'zh_CN':canonical,'expected_minimum':count,'actual_literal_count':actual,
                          'source_aliases':aliases[canonical]}
                    (prototype_gaps if prototype else errors).append(item)
        if number%5000==0:
            print(json.dumps({'progress':'canonical_audit','checked_rows':number},ensure_ascii=False),flush=True)
    structure=prepared['validation']
    return {'status':'pass' if structure['status']=='pass' and not errors else 'fail',
            'source_units':len(prepared['source']),'target_units':len(prepared['merged']),
            'preserved_prototype_units':len(prepared['baseline']),
            'source_input_sha256':sha(args.input),'flat_glossary_sha256':sha(args.glossary),
            'protected_list_sha256':sha(args.protect_json),'tokenizer_config_sha256':tokenizer.config,
            'statistics':dict(stats),'canonical_targets_counted':len(term_counts),
            'canonical_target_counts':{key:dict(value) for key,value in sorted(term_counts.items())},
            'structural_validation':structure,'errors':errors,
            'preserved_prototype_canonical_gaps':prototype_gaps,
            'prototype_policy':'Existing 248 prototype rows are preserved. Canonical differences are reported, never silently changed.',
            'not_verified':['human translation meaning','source alias identity beyond glossary research',
                            'font coverage','layout','graphics/movie rendering','game insertion/runtime'],
            'literal_check_limit':'At-least-count literal presence; overlapping targets and naturally occurring identical words can overcount. Not a semantic proof.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',default='/tmp/stt-mt-input/all_units.input.jsonl')
    p.add_argument('--machine-dir',default='/tmp/stt-canonical-output')
    p.add_argument('--prototype-dir',default=str(exporter.ROOT/'work/translation/zh_CN/out'))
    p.add_argument('--glossary',default=str(exporter.ROOT/'work/glossary/zh_CN_canonical_terms.flat.json'))
    p.add_argument('--protect-json',default=str(exporter.ROOT/'work/glossary/zh_CN_canonical_protected.json'))
    p.add_argument('--expected-units',type=int,default=21508)
    p.add_argument('--report',default='/tmp/stt-mt-input/canonical_independent_audit.json')
    args=p.parse_args();report=audit(args)
    path=Path(args.report);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary={key:value for key,value in report.items() if key not in
             ('structural_validation','canonical_target_counts','errors','preserved_prototype_canonical_gaps')}
    summary['structural_error_count']=len(report['structural_validation']['errors'])
    summary['canonical_error_count']=len(report['errors'])
    summary['error_examples']=report['errors'][:10]
    summary['preserved_prototype_canonical_gap_count']=len(report['preserved_prototype_canonical_gaps'])
    summary['report']=str(path)
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    raise SystemExit(0 if report['status']=='pass' else 1)


if __name__=='__main__':main()
