#!/usr/bin/env python3
"""Apply six guarded source-based unit phrase fixes after canonical MT.

Read-only without --write. All rules must match before any batch is changed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import uuid

import check_zh_mt as checker


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--machine-dir',default='/tmp/stt-canonical-final')
    p.add_argument('--rules',default='/tmp/stt-mt-input/canonical_unit_fixes.json')
    p.add_argument('--report',default='/tmp/stt-mt-input/canonical_unit_fix_audit.json')
    p.add_argument('--write',action='store_true');a=p.parse_args()
    rules=json.loads(Path(a.rules).read_text(encoding='utf-8'))['rules']
    wanted={r['uid']:r for r in rules};files={};rows={};owners={}
    for path in sorted(Path(a.machine_dir).glob('M*.json')):
        value=json.loads(path.read_text(encoding='utf-8'));files[path]=value
        for row in value['rows']:
            uid=row['uid']
            if uid in wanted:
                if uid in rows:raise ValueError('Duplicate target UID: '+uid)
                rows[uid]=row;owners[uid]=path
    if set(rows)!=set(wanted):raise ValueError('Not all six unit-fix UIDs are present')
    changes=[];dirty=set()
    for uid,rule in wanted.items():
        row=rows[uid];old=row['zh_CN']
        if row.get('mt',{}).get('source_sha256')!=rule['source_sha256']:
            raise ValueError('Source hash differs: '+uid)
        if old.count(rule['before'])!=1:raise ValueError('Exact before-phrase guard failed: '+uid)
        new=old.replace(rule['before'],rule['after'],1)
        if checker.control_tokens(old)!=checker.control_tokens(new):raise ValueError('Controls changed: '+uid)
        row['zh_CN']=new
        row['mt'].setdefault('local_source_based_edits',[]).append({
            'kind':'unit_phrase','reason':rule['reason'],'before':rule['before'],'after':rule['after']})
        changes.append({**rule,'batch':owners[uid].name});dirty.add(owners[uid])
    report={'status':'ready','mode':'write' if a.write else 'dry_run','units':len(changes),
            'batch_files':len(dirty),'changes':changes,'rule_file_sha256':hashlib.sha256(Path(a.rules).read_bytes()).hexdigest()}
    if a.write:
        staging=[]
        try:
            for path in sorted(dirty):
                temp=path.with_name('.'+path.name+'.units-'+uuid.uuid4().hex[:8])
                temp.write_text(json.dumps(files[path],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                assert json.loads(temp.read_text(encoding='utf-8'))==files[path]
                staging.append((temp,path))
            for temp,path in staging:temp.replace(path)
        finally:
            for temp,_ in staging:
                if temp.exists():temp.unlink()
        for uid,rule in wanted.items():
            reopened=next(r for r in checker.load_rows(owners[uid]) if r['uid']==uid)
            assert rule['after'] in reopened['zh_CN'] and rule['before'] not in reopened['zh_CN']
        report['status']='pass'
        Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='changes'},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
