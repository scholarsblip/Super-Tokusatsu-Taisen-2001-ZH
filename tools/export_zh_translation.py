#!/usr/bin/env python3
"""Merge and export the complete Chinese text draft, without game insertion.

The default is a read-only plan. --write requires complete, validated coverage
and creates a new directory atomically. Existing prototype Z files are read
only, take no machine replacements, and are verified unchanged after export.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid

import check_zh_mt as checker

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parents[1]


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def write_json(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def target_projection(row):
    return {'uid':row['uid'],'zh_CN':row['zh_CN'],'speaker_zh_CN':row.get('speaker_zh_CN')}


def read_outputs(directory,pattern):
    rows=[];owners={};hashes={};errors=[]
    for path in sorted(Path(directory).glob(pattern)):
        hashes[str(path)]=file_hash(path)
        for row in checker.load_rows(path):
            uid=checker.row_uid(row)
            if uid in owners:
                errors.append({'kind':'duplicate_uid_in_output_files','uid':uid,'files':[owners[uid],str(path)]})
            owners[uid]=str(path);rows.append(row)
    return rows,owners,hashes,errors


def prepare(source_path,machine_dir,prototype_dir,expected_units=21508,expected_prototype=248):
    source=checker.load_rows(source_path)
    baseline,base_owners,base_hashes,errors=read_outputs(prototype_dir,'Z*.json')
    machine,mt_owners,mt_hashes,more=read_outputs(machine_dir,'M*.json');errors+=more
    source_ids=[checker.row_uid(r) for r in source]
    source_map={checker.row_uid(r):r for r in source}
    base_map={checker.row_uid(r):r for r in baseline};mt_map={checker.row_uid(r):r for r in machine}
    if len(source)!=expected_units:
        errors.append({'kind':'unexpected_source_count','expected':expected_units,'actual':len(source)})
    if len(base_map)!=expected_prototype:
        errors.append({'kind':'unexpected_prototype_count','expected':expected_prototype,'actual':len(base_map)})
    expected_base={f'U{i:05d}' for i in range(expected_prototype)}
    if set(base_map)!=expected_base:
        errors.append({'kind':'unexpected_prototype_uids','missing':sorted(expected_base-set(base_map)),'extra':sorted(set(base_map)-expected_base)})
    overlap=sorted(set(base_map)&set(mt_map))
    if overlap:
        errors.append({'kind':'machine_attempted_prototype_replacement','uids':overlap})
    if len(source_ids)!=len(set(source_ids)):
        errors.append({'kind':'duplicate_source_uid'})
    extra=sorted((set(base_map)|set(mt_map))-set(source_map))
    if extra:errors.append({'kind':'unknown_target_uid','uids':extra})
    combined={**mt_map,**base_map}
    merged=[combined[uid] for uid in source_ids if uid in combined]
    validation=checker.validate_rows(source,merged,source_field='text',target_field='zh_CN')
    validation['errors']=errors+validation['errors']
    validation['status']='pass' if not validation['errors'] else 'fail'
    validation['source_kind_counts']=dict(Counter(r.get('kind','unknown') for r in source))
    validation['source_language_counts']=dict(Counter(r.get('source_language','unknown') for r in source))
    validation['preserved_prototype_units']=len(base_map)
    validation['machine_units']=len(mt_map)
    return {'source':source,'source_map':source_map,'merged':merged,'baseline':base_map,
            'base_owners':base_owners,'base_hashes':base_hashes,'mt_owners':mt_owners,
            'mt_hashes':mt_hashes,'validation':validation,'source_input_sha256':file_hash(source_path)}


def export(prepared,output,version='0.2.0',batch_size=80):
    report=prepared['validation']
    if report['status']!='pass':
        raise ValueError('Coverage/token validation failed; no output directory was written')
    output=Path(output)
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError('Refusing to overwrite nonempty output: '+str(output))
    output.parent.mkdir(parents=True,exist_ok=True)
    staging=output.with_name('.'+output.name+'.writing-'+uuid.uuid4().hex[:8])
    staging.mkdir()
    try:
        core=[target_projection(row) for row in prepared['merged']]
        global_meta={'version':version,'language':'zh_CN','status':'machine_unreviewed',
                     'inserted_into_game':False,'units':len(core),
                     'scope':'Extracted core text; auxiliary image/movie text is separate.',
                     'preserved_prototype_units':len(prepared['baseline']),
                     'machine_units':report['machine_units'],
                     'source_input_sha256':prepared['source_input_sha256']}
        write_json(staging/'translations.zh_CN.json',{**global_meta,'rows':core})
        provenance={}
        for row in prepared['merged']:
            uid=row['uid'];source=prepared['source_map'][uid]
            item={'origin':'preserved_existing_prototype' if uid in prepared['baseline'] else 'machine_translation',
                  'status':'machine_unreviewed','source_language':source.get('source_language'),
                  'source_policy':source.get('source_policy'),
                  'chosen_source_sha256':hashlib.sha256(source['text'].encode('utf-8')).hexdigest(),
                  'original_source_sha256':source.get('original_source_sha256'),
                  'kind':source.get('kind'),'sources':source.get('sources',[]),
                  'occurrences':source.get('occurrences'),
                  'source_provenance':source.get('source_provenance')}
            if uid in prepared['baseline']:
                item['source_file']=Path(prepared['base_owners'][uid]).name
            else:
                item['source_file']=Path(prepared['mt_owners'][uid]).name
                item['mt']=row.get('mt')
            provenance[uid]=item
        write_json(staging/'provenance.json',{**global_meta,'rows':provenance,
                                            'prototype_file_sha256':prepared['base_hashes'],
                                            'machine_file_sha256':prepared['mt_hashes']})
        write_json(staging/'validation.json',report)
        with (staging/'translations.zh_CN.tsv').open('w',encoding='utf-8',newline='') as f:
            writer=csv.writer(f,delimiter='\t',lineterminator='\n',quoting=csv.QUOTE_MINIMAL)
            writer.writerow(['uid','speaker_is_null','speaker_zh_CN','zh_CN','origin','status','sources'])
            for row in core:
                p=provenance[row['uid']]
                writer.writerow([row['uid'],'1' if row['speaker_zh_CN'] is None else '0',
                                 row['speaker_zh_CN'] or '',row['zh_CN'],p['origin'],p['status'],
                                 json.dumps(p['sources'],ensure_ascii=False,separators=(',',':'))])
        batches=staging/'batches';batches.mkdir()
        for first in range(0,len(core),batch_size):
            number=first//batch_size+1;rows=core[first:first+batch_size]
            write_json(batches/f'T{number:04d}.json',{'version':version,'language':'zh_CN',
                       'status':'machine_unreviewed','inserted_into_game':False,
                       'batch':f'T{number:04d}','rows':rows})
        readme=(
            '超级特摄大战2001：简体中文机器翻译文本\n'
            f'版本：{version}\n\n'
            f'本包包含 {len(core)} 个提取文本单元；保留原有 {len(prepared["baseline"])} 个测试版译文，'
            '其余为机器翻译。状态为 machine_unreviewed，尚未逐句人工校对。\n'
            '这里只完成文本翻译，不代表已写回游戏，也不代表字体、排版、存档、战斗或完整通关验证通过。\n'
            '图片菜单及影片字幕等辅助文本如另有文件，应以其各自清单为准。\n\n'
            'translations.zh_CN.json：仅译文、角色名和 UID，不含原文正文。\n'
            'translations.zh_CN.tsv：UTF-8、制表符分隔；含换行的单元格使用标准 CSV 引号。'
            '请用支持 TSV/CSV 引号的读取器；不要按物理行数统计文本条数。\n'
            'speaker_is_null=1 表示角色名为 null，与空字符串区别保留。\n'
            f'batches/：每批最多 {batch_size} 条，保持输入 UID 顺序和一条输入对应一条输出。\n'
            'provenance.json：来源、机器翻译引擎、哈希及原测试版文件记录。\n'
            'validation.json：UID 覆盖、控制码、占位符、ID、说话者状态和来源哈希检查。\n'
            'accepted_id_transforms 逐项记录可读单位、已接受译名等 ID 误报例外；'
            '每项绑定 UID、原文哈希、出现次数和目标证据，不会放宽其他缩写或运行时标识。\n'
            'warnings 是待复核标记；残留假名、英文姓名或型号不应自动视为已人工确认的译名。\n'
            'manifest.json：本包各文件的大小和 SHA-256。\n\n'
            '该文本包不会覆盖或修改已有 Z0001–Z0004 测试版翻译文件。\n')
        (staging/'README.txt').write_text(readme,encoding='utf-8')
        # Reopen every representation: CSV quoting and batch boundaries must
        # reconstruct exactly the same target/speaker data, including nulls.
        reopened=json.loads((staging/'translations.zh_CN.json').read_text(encoding='utf-8'))['rows']
        assert reopened==core,'JSON round trip changed target rows'
        with (staging/'translations.zh_CN.tsv').open(encoding='utf-8',newline='') as f:
            tabrows=list(csv.DictReader(f,delimiter='\t'))
        restored=[{'uid':r['uid'],'zh_CN':r['zh_CN'],
                   'speaker_zh_CN':None if r['speaker_is_null']=='1' else r['speaker_zh_CN']} for r in tabrows]
        assert restored==core,'TSV quoting/null-state round trip failed'
        batched=[]
        for path in sorted(batches.glob('T*.json')):
            rows=json.loads(path.read_text(encoding='utf-8'))['rows']
            assert 1<=len(rows)<=batch_size
            batched+=rows
        assert batched==core,'Batch boundaries changed or duplicated target rows'
        assert checker.validate_rows(prepared['source'],core,'text','zh_CN')['status']=='pass'
        for uid,original in prepared['baseline'].items():
            assert reopened[[r['uid'] for r in reopened].index(uid)]==target_projection(original)
        for path,expected_hash in prepared['base_hashes'].items():
            assert file_hash(path)==expected_hash,'An existing prototype file changed: '+path
        manifest={**global_meta,'batch_size':batch_size,'batch_files':len(list(batches.glob('T*.json'))),
                  'json_tsv_batch_round_trips':True,'existing_prototype_unchanged':True,
                  'files':[{'path':str(p.relative_to(staging)),'bytes':p.stat().st_size,'sha256':file_hash(p)}
                           for p in sorted(staging.rglob('*')) if p.is_file()]}
        write_json(staging/'manifest.json',manifest)
        if output.exists():output.rmdir() # only the prechecked empty directory
        staging.replace(output)
        return manifest
    except Exception:
        shutil.rmtree(staging)
        raise


def self_test():
    with tempfile.TemporaryDirectory(prefix='stt-export-test-') as d:
        d=Path(d);proto=d/'prototype';proto.mkdir();mt=d/'mt';mt.mkdir()
        source=[{'uid':'U00000','text':'Hello<p>[HERO2]','speaker':None},
                {'uid':'U00001','text':'UCMA\nworld','speaker':'[HERO2]'}]
        (d/'input.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in source))
        write_json(proto/'Z0001.json',{'rows':[{'uid':'U00000','zh_CN':'你好<p>[HERO2]','speaker_zh_CN':None}]})
        write_json(mt/'M0001.json',{'rows':[{'uid':'U00001','zh_CN':'UCMA\n世界\t测试','speaker_zh_CN':'[HERO2]'}]})
        prepared=prepare(d/'input.jsonl',mt,proto,2,1)
        assert prepared['validation']['status']=='pass'
        manifest=export(prepared,d/'out',batch_size=1)
        assert manifest['units']==2 and manifest['batch_files']==2
        try:export(prepared,d/'out')
        except FileExistsError:pass
        else:raise AssertionError('Existing output was overwritten')
        (mt/'M0001.json').unlink()
        bad=prepare(d/'input.jsonl',mt,proto,2,1)
        assert bad['validation']['missing_units']==1
        try:export(bad,d/'incomplete')
        except ValueError:pass
        else:raise AssertionError('Incomplete data was exported as complete')
        assert not (d/'incomplete').exists()
    return {'status':'pass','checks':['JSON/TSV multiline and tab round trip','speaker null state',
                                      '80-row batching mechanism','prototype preservation',
                                      'nonempty output refusal','missing-unit export refusal']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',default='/tmp/stt-mt-input/all_units.input.jsonl')
    p.add_argument('--machine-dir',default='/tmp/stt-mt-output')
    p.add_argument('--prototype-dir',default=str(ROOT/'work/translation/zh_CN/out'))
    p.add_argument('--output',default=str(BASE/'outputs/STT2001_ZH_machine_text_v0.2.0'))
    p.add_argument('--version',default='0.2.0');p.add_argument('--batch-size',type=int,default=80)
    p.add_argument('--expected-units',type=int,default=21508);p.add_argument('--expected-prototype',type=int,default=248)
    p.add_argument('--write',action='store_true');p.add_argument('--self-test',action='store_true')
    args=p.parse_args()
    if args.self_test:print(json.dumps(self_test(),indent=2));return
    if not 1<=args.batch_size<=80:p.error('batch-size must be between1and80')
    prepared=prepare(args.input,args.machine_dir,args.prototype_dir,args.expected_units,args.expected_prototype)
    report=prepared['validation']
    preview={k:v for k,v in report.items() if k not in ('errors','warnings','accepted_id_transforms')}
    preview['accepted_id_transform_rules_used']=len(report.get('accepted_id_transforms',[]))
    preview['mode']='write' if args.write else 'dry_run'
    preview['error_examples']=report['errors'][:12]
    preview['warning_examples']=report['warnings'][:12]
    print(json.dumps(preview,ensure_ascii=False,indent=2),flush=True)
    if report['status']!='pass':raise SystemExit(1)
    if args.write:
        manifest=export(prepared,args.output,args.version,args.batch_size)
        print(json.dumps({'output':str(Path(args.output).resolve()),'units':manifest['units'],
                          'batch_files':manifest['batch_files'],'status':manifest['status'],
                          'inserted_into_game':False},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
