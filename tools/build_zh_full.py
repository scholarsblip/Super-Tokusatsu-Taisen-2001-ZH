#!/usr/bin/env python3
"""Build the complete Chinese core text using the original relocation formats.

--preflight compiles strings and validates pointers/RAM limits with temporary
glyph codes; it cannot create a disc. Default mode uses the real full font and
prepares caller-owned resources/reports. Only --write creates a local image.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import time
import unicodedata

import cm
import dump_script as D
import insert as I
import repack
from zh_full_text import Encoder,Translator

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT.parents[1]
DISC=ROOT/'work/source/disc'
OUT=ROOT/'work/output'
DEFAULT_LEGACY={1123:'拓',1124:'真',1125:'咲',1126:'英',1127:'司',1128:'兰'}
DEFAULT_COMPONENTS=[[1118,1119],[1123,1124],[],[1125],[1120],[1126,1127],[1121,1122],[1128]]


def portable_default(public_path,legacy_path):
    """Prefer checked-in Chinese data, retaining old local-workspace support."""
    public_path=Path(public_path);legacy_path=Path(legacy_path)
    return str(public_path if public_path.exists() or not legacy_path.exists() else legacy_path)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def verify_disc_payloads(path,prepared):
    """Read the completed ISO directory and compare every prepared payload."""
    checked=[]
    with Path(path).open('rb') as disc:
        disc.seek(16*2352)
        pvd=disc.read(2352)[24:2072]
        assert pvd[:7]==b'\x01CD001\x01','Invalid ISO volume descriptor'
        root=pvd[156:190]
        lba,size=struct.unpack_from('<I',root,2)[0],struct.unpack_from('<I',root,10)[0]
        assert lba==struct.unpack_from('>I',root,6)[0]
        assert size==struct.unpack_from('>I',root,14)[0]
        directory,records=repack.read_dir(disc,lba,size)
        actual={}
        for offset,length,name in records:
            if name in (b'\0',b'\1'):continue
            key=name.decode().split(';')[0]
            file_lba=struct.unpack_from('<I',directory,offset+2)[0]
            file_size=struct.unpack_from('<I',directory,offset+10)[0]
            assert file_lba==struct.unpack_from('>I',directory,offset+6)[0]
            assert file_size==struct.unpack_from('>I',directory,offset+14)[0]
            actual[key]={'path':key,'lba':file_lba,'size':file_size}
        sidecar={row['path']:row for row in json.loads(Path(str(path)+'.files.json').read_text())}
        assert actual==sidecar,'ISO directory differs from build file table'
        for name,expected in sorted(prepared.items()):
            entry=actual[name];assert entry['size']==len(expected),(name,'size mismatch')
            disc.seek(entry['lba']*2352)
            digest=hashlib.sha256()
            for position in range(0,len(expected),2048):
                sector=disc.read(2352)
                assert len(sector)==2352 and sector[15]==2 and not sector[18]&0x20
                data=sector[24:24+min(2048,len(expected)-position)]
                assert data==expected[position:position+2048],(name,'disc payload differs',position)
                digest.update(data)
            checked.append({'path':name,'bytes':len(expected),'sha256':digest.hexdigest(),'matches_prepared_payload':True})
    return {'iso_directory_and_sidecar_match':True,'prepared_files':checked}


def preflight_font(texts):
    import zh_font as Z
    native=Z.original_map('11')
    encoding={v:k for k,v in sorted(native.items(),reverse=True) if len(v)==1 and k<320}
    encoding.update({v:k for k,v in DEFAULT_LEGACY.items()})
    for code in range(1118,1123):encoding[native[code]]=code
    aliases={'?':'？','!':'！',',':'，',':':'：',';':'；','(':'（',')':'）',
             '[':'［',']':'］','+':'＋','-':'－','/':'／','%':'％'}
    required=Z.required_chars(texts)
    required={c for c in required if unicodedata.category(c)!='Cf' and c not in ('\r','\t')}
    required|={aliases.get(c,c) for c in required}
    custom={c:0x1000+i for i,c in enumerate(sorted(required-set(encoding)))}
    encoding.update(custom)
    for a,b in aliases.items():
        if b in encoding:encoding[a]=encoding[b]
    plan={'encode':encoding,'aliases':aliases,'legacy_default_names':DEFAULT_COMPONENTS,
          'reserved_wide_codes':list(range(1118,1129))+list(range(1425,1454)),
          'status':'preflight_temporary_codes_not_a_playable_font','custom_glyphs':len(custom)}
    def encode(text,p):
        return [p['encode'][p['aliases'].get(c,c)] for c in text
                if unicodedata.category(c)!='Cf' and c not in ('\r','\t')]
    return plan,encode


def patch_exe(exe,tr,ui,encoder):
    out=bytearray(exe);report=[]
    for off,ws,term in D.table16_strings(exe,0x9A900):
        if off>0x9AF70:break
        key=f'{off:05X}'
        if not ws or not D.is_text(ws):continue
        source=tr.by_occ.get(('SLPS',off))
        if key in ui:
            if ui[key] is None:
                # Debug/audio identifiers and numeric templates are native
                # fields, not translatable prose (SE must not become 东南欧).
                if source:
                    uid=source['uid'];tr.seen[uid]+=1;tr.occurrences.add(('SLPS',off))
                    report.append({'offset':key,'uid':uid,'policy':'native_identifier_or_numeric_template_retained',
                                   'source':tr.sources[uid]['text'],'written_codes':0,'slot_codes':len(ws)})
                continue
            if ('SLPS',off) in tr.by_occ:
                tr.words_for('exe',list(ws),'11',('SLPS',off))
            text=tr.override_rows[source['uid']]['zh_CN'] if source and source['uid'] in tr.override_rows else ui[key]
            generated=encoder.encode(text,list(ws),'11')
        else:
            generated=tr.words_for('exe',list(ws),'11',('SLPS',off))
            if generated is None:continue
            text=tr.by_occ.get(('SLPS',off),{}).get('uid')
        if len(generated)>len(ws):
            raise ValueError(str((key,'executable slot overflow',len(generated),len(ws))))
        struct.pack_into('<%dH'%len(ws),out,off,*(generated+[0xFF30]*(len(ws)-len(generated))))
        report.append({'offset':key,'text':text,'written_codes':len(generated),'slot_codes':len(ws)})
    var6=[]
    for addr,slot,text in [(0x800AA108,6,'闪电人'),(0x800AA114,7,'闪电人F')]:
        off=addr-0x80010000+0x800
        old=struct.unpack_from('<%dH'%slot,out,off)
        assert old[-1]==0xFF05 and all(c<0xFF00 for c in old[:-1])
        codes=encoder.plain(text);assert len(codes)<slot
        struct.pack_into('<%dH'%slot,out,off,*(codes+[0xFF05]*(slot-len(codes))))
        var6.append({'address':hex(addr),'text':text,'codes':codes})
    return bytes(out),report,var6


def build(args):
    global OUT
    OUT=Path(getattr(args,'output_dir',OUT))
    start=time.monotonic();OUT.mkdir(exist_ok=True,parents=True)
    raw_targets=json.loads(Path(args.translations).read_text())['rows']
    ui_all=json.loads((Path(args.ui_dir)/'exe_strings.zh.json').read_text())
    ui={k:v for k,v in ui_all.items() if not k.startswith('_')}
    manual=json.loads((Path(args.ui_dir)/'manual.zh.json').read_text())
    texts=[value for r in raw_targets for value in (r['zh_CN'],r.get('speaker_zh_CN')) if value]
    texts+=list(v for v in ui.values() if isinstance(v,str))+list(manual.values())+['闪电人F','＜L2＞ ＜R2＞ ＜L/R＞']+list(DEFAULT_LEGACY.values())
    for override_name in ('build_overrides.v0.2.1.json','build_choice_fixes.v0.2.1.json','build_runtime_fixes.v0.2.4.json'):
        override_path=ROOT/'work/translation/zh_CN'/override_name
        if override_path.exists():texts += [row['zh_CN'] for row in json.loads(override_path.read_text())['rows']]
    if args.preflight:
        plan,encode_plain=preflight_font(texts)
    else:
        import zh_full_font as F
        plan=F.make_plan(texts,legacy_wide=DEFAULT_LEGACY)
        plan['legacy_default_names']=DEFAULT_COMPONENTS
        encode_plain=F.encode_plain
    encoder=Encoder(plan,encode_plain)
    tr=Translator(encoder,args.translations,args.inputs,args.ui_dir)
    if args.preflight:
        strict_words_for=tr.words_for
        def collect_words_for(src,ws,font,occ=None):
            try:return strict_words_for(src,ws,font,occ)
            except (ValueError,KeyError,AssertionError) as error:
                row=tr.by_occ.get(occ,{})
                tr.problems.append({'kind':'encoding_exception','uid':row.get('uid'),'src':src,
                                    'occurrence':occ,'error':str(error)})
                return None
        tr.words_for=collect_words_for
    # The generic u16-table relocator calls this for shared suffix fragments.
    I.encode_line_tokens=encoder.line_tokens
    I.STATS.clear();I.PROBLEMS.clear()
    rows=tr.rows
    font_at={(r['file'],r['off']):r['font'] for r in rows}
    sizes=[];files={}
    stage=repack.dat_entries((DISC/'STAGE.DAT').read_bytes())
    stage_jobs=[]
    for number,key in enumerate(sorted(D.STAGE_VAR)):
        index=int(key);name='STAGE'+key
        new=I.rebuild_overlay(stage[index],0,'stage',lambda off,ws,n=name:font_at.get((n,off),'11'),tr,name)
        sizes.append({'kind':'stage','entry':index,'bytes':len(new),'limit':0x12C00})
        if len(new)>0x12C00:raise ValueError(str((name,'overlay RAM capacity exceeded',len(new))))
        stage[index]=new;stage_jobs.append((630+number,new,index+1))
        if number%15==0:print(json.dumps({'phase':'stage_text','completed':number+1,'total':len(D.STAGE_VAR)}),flush=True)
    battle=repack.dat_entries((DISC/'BATTLE.DAT').read_bytes())
    for index,entry in enumerate(battle):
        if len(entry)>0x8438 and entry[:4]==b'\x10\0\0\0' and struct.unpack_from('<I',entry,0x8434)[0]>>16==0x800E:
            battle[index]=I.rebuild_overlay(entry,0x8434,'bquote',lambda off,ws:'11',tr,'BATTLE%04d'%index)
    battle[540]=I.rebuild_encyc(battle[540],tr)
    sizes.append({'kind':'encyclopedia','entry':540,'bytes':len(battle[540]),'limit':0x1F000})
    if len(battle[540])>0x1F000:raise ValueError('Encyclopedia RAM capacity exceeded')
    mm=repack.dat_entries((DISC/'MAPMAIN.DAT').read_bytes())
    mm[2]=I.rebuild_table16(mm[2],'db',tr,fname='MAPMAIN0002')
    blocks24=cm.blocks(mm[24]);db24=I.rebuild_table16(blocks24[1],'db',tr)
    sizes.append({'kind':'database','entry':24,'bytes':len(db24),'limit':0xD000})
    if len(db24)>0xD000:raise ValueError('Database RAM capacity exceeded')
    mm[27]=I.rebuild_sequential(mm[27],struct.unpack_from('<I',mm[27],0)[0],'music',tr,fname='MAPMAIN0027')
    exe,exe_report,var6=patch_exe((DISC/'SLPS_028.63').read_bytes(),tr,ui,encoder)
    missing=sorted(set(tr.targets)-set(tr.seen))
    report={'version':args.version,'status':'preflight' if args.preflight else 'prepared_runtime_verification_pending',
            'units':len(tr.targets),'units_seen':len(tr.seen),'missing_uids':missing,
            'coordinate_occurrences_seen':len(tr.occurrences),'expected_unique_coordinates':len(tr.by_occ),
            'text_stats':dict(I.STATS),'layout_stats':dict(encoder.stats),'capacity_checks':sizes,
            'executable':exe_report,'var6':var6,'default_names':tr.defaults,
            'functional_name_grids':tr.report,'problems':tr.problems+I.PROBLEMS,
            'font_plan_status':plan.get('status'),'font_glyphs':plan.get('custom_glyphs',len(plan.get('new_glyphs',{}))),
            'translation_file_sha256':sha(args.translations),'build_overrides':list(tr.override_rows.values()),'emulator_verified':False}
    name='STT2001_ZH_v'+args.version
    plan_path=OUT/(name+('_preflight_font_plan.json' if args.preflight else '_font_plan.json'))
    plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
    report['font_plan_path']=str(plan_path)
    report['font_plan_sha256']=sha(plan_path)
    report_path=OUT/(name+('_preflight.json' if args.preflight else '_report.json'))
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'phase':'text_prepared','units_seen':len(tr.seen),'missing':missing,'problems':len(report['problems']),'seconds':round(time.monotonic()-start,2),'report':str(report_path)},ensure_ascii=False),flush=True)
    if missing or report['problems']:raise ValueError('Text preparation has unresolved issues; see report')
    if args.preflight:return
    import stage_cards
    for number,(cm_index,text,script_index) in enumerate(stage_jobs):
        script,count=stage_cards.patch_script(stage[script_index]);stage[script_index]=script
        original=cm.blocks(stage[cm_index])
        stage[cm_index]=I.rebuild_cm(stage[cm_index],{4:text,5:script[:len(original[5])]})
        reopened=cm.blocks(stage[cm_index]);assert reopened[4]==text
        assert all(a==b for n,(a,b) in enumerate(zip(original,reopened)) if n not in (4,5))
        if number%15==0:print(json.dumps({'phase':'stage_compression','completed':number+1,'total':len(stage_jobs)}),flush=True)
    mm[24]=I.rebuild_cm(mm[24],{1:db24})
    files={'STAGE.DAT':repack.dat_pack(stage),'BATTLE.DAT':repack.dat_pack(battle),
           'MAPMAIN.DAT':repack.dat_pack(mm),'EVENT.DAT':(DISC/'EVENT.DAT').read_bytes()}
    import zh_full_font as F
    report['font']=F.patch_files(files,plan)
    exe=F.patch_exe(exe,plan)
    files['SLPS_028.63']=exe
    I.check_default_names(files)
    if I.PROBLEMS:raise ValueError(str(I.PROBLEMS))
    if not args.skip_raster:
        import zh_graphics_full
        report['graphics']=zh_graphics_full.patch_files(files)
    report['prepared_file_sha256']={name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())}
    if args.write:
        destination=OUT/(name+'.bin')
        repack.rebuild(str(Path(args.source_bin)),str(destination),files)
        report['disc_payload_verification']=verify_disc_payloads(destination,files)
        (OUT/(name+'.cue')).write_text('FILE "'+name+'.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
        report.update({'status':'built_runtime_verification_pending','output_bytes':destination.stat().st_size,'output_sha256':sha(destination)})
    report['seconds']=round(time.monotonic()-start,2)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('version');p.add_argument('--write',action='store_true')
    p.add_argument('--preflight',action='store_true');p.add_argument('--skip-raster',action='store_true')
    p.add_argument('--translations',default=portable_default(ROOT/'work/translation/zh_CN/translations.zh_CN.json',BASE/'outputs/STT2001_ZH_machine_text_v0.2.0/translations.zh_CN.json'))
    p.add_argument('--inputs',default=portable_default(ROOT/'work/source/zh_inputs','/tmp/stt-mt-input'))
    public_translation=ROOT/'work/translation/zh_CN/translations.zh_CN.json'
    legacy_ui=BASE/'outputs/STT2001_ZH_machine_text_v0.2.0/ui'
    p.add_argument('--ui-dir',default=str(ROOT/'work/translation/zh_CN/full_ui') if public_translation.exists() or not legacy_ui.exists() else str(legacy_ui))
    p.add_argument('--output-dir',default=str(OUT))
    p.add_argument('--source-bin',default=str(ROOT/'Super Tokusatsu Taisen 2001 (Japan).bin'))
    a=p.parse_args()
    if a.preflight and a.write:p.error('--preflight cannot write a disc')
    build(a)


if __name__=='__main__':main()
