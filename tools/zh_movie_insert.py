"""Prepare and verify native Chinese STR overlays without changing source media.

The patch(path) API validates every prepared stream and baseline range before
opening a caller-owned output image for writes. Original XA and frame slots stay
byte identical. Install PyAV/Pillow/numpy normally; the legacy isolated runtime
also remains supported. Extract with --baseline /path/to/original.bin.

Java: STT2001_JAVA, JAVA_HOME/bin/java, PATH, then legacy java_path.txt.
Encoder: STT2001_JPSXDEC_JAR/JPSXDEC_JAR, PATH jpsxdec (or jpsxdec.jar),
then the legacy local jPSXdec JAR. --dry-run performs read-only checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools/movie_runtime/pythonlib'))
import av
from PIL import Image, ImageDraw

import zh_movie_subtitles as lettering

SOURCE = ROOT/'work/source/movies_zh'
ENCODED = SOURCE/'encoded'
QA = ROOT/'work/translation/zh_CN/movies'
MANIFEST = lettering.MANIFEST
BASELINE = ROOT/'work/output/STT2001_ZH_v0.2.1.bin'
JAR = ROOT/'tools/movie_runtime/jpsxdec/jpsxdec_v2.1-beta/jpsxdec.jar'
SECTOR = 2352
MAGIC = bytes.fromhex('60010180')
BASELINE_SHA256 = 'b809ec1fe14cf0a50d0ada981e14e1b6c201930c84e2fdc51c4834e45e014d17'
ORIGINAL_SHA256 = '219d9c4f64caf670b5e400612fa19677ed9a3f59a7ebdb72c12c425412795465'
DISC_SIZE = 725316816
SUPPORTED_SOURCES = {ORIGINAL_SHA256:'original Japanese SLPS-02863',
                     BASELINE_SHA256:'legacy Chinese v0.2.1 (movies unchanged)'}


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def save(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def inventory():
    return json.loads((SOURCE/'inventory.json').read_text(encoding='utf-8'))


def selected(data, ids=None):
    return [c for c in data['clips'] if (c['subtitles'] or c.get('credits'))
            and (ids is None or c['id'] in ids)]


def scan_extract(baseline=BASELINE,dry_run=False):
    from check_movie_build import directory
    baseline=Path(baseline)
    if not baseline.is_file():
        raise FileNotFoundError('Source BIN missing; use --baseline /path/to/original.bin')
    source_hash=digest(baseline)
    assert source_hash in SUPPORTED_SOURCES,'Source BIN SHA256 is not a supported Japanese/legacy source'
    assert baseline.stat().st_size==DISC_SIZE,'Source BIN size differs'
    files=directory(baseline);movie=files['MOVIE.STR']
    end=files['VORTEX.XA']['lba'];count=end-movie['lba']
    assert movie=={'lba':372,'size':333578240} and count==162880
    rows=[];current=None
    with baseline.open('rb',buffering=4*1024*1024) as source:
        source.seek(movie['lba']*SECTOR)
        for n in range(count):
            s=source.read(SECTOR)
            assert len(s)==SECTOR
            typ=s[18]&14
            if typ in (2,8) and s[24:28]==MAGIC:
                chunk,chunks,frame,size,w,h=struct.unpack_from('<HHIIHH',s,28)
                if chunk==0 and frame==1:
                    if current:
                        current['end_sector']=n;rows.append(current)
                    current={'id':len(rows)+1,'start_sector':n,'width':w,'height':h,
                             'frames':0,'audio_sectors':0,'fps':12,'sample_rate':18900}
                assert current is not None,'Video before first frame'
                assert (w,h)==(current['width'],current['height'])
                if chunk==0:current['frames']+=1
            if current and typ==4:
                assert s[19]==5,'Unexpected XA coding'
                current['audio_sectors']+=1
    assert current is not None
    current['end_sector']=count;rows.append(current)
    assert len(rows)==74,len(rows)
    for row in rows:
        row['video_seconds']=round(row['frames']/12,6)
        row['audio_seconds']=round(row['audio_sectors']*2016/18900,6)
        row['type']='battle_clip' if row['width']==160 else 'movie'
    data=manifest();plan=lettering.plan(data,rows)
    plan.update({'mode':'dry_run' if dry_run else 'extract','source_bin':str(baseline.resolve()),
                 'source_sha256':source_hash,'source_kind':SUPPORTED_SOURCES[source_hash]})
    if dry_run:
        print(json.dumps({k:v for k,v in plan.items() if k not in ('captions','credits')},ensure_ascii=False,indent=2))
        return plan
    SOURCE.mkdir(parents=True,exist_ok=True)
    save(SOURCE/'inventory.json',rows)
    save(SOURCE/'source.json',{'source_bin':str(baseline.resolve()),'sha256':source_hash,
         'disc_size':baseline.stat().st_size,
         'movie':movie,'raw_sector_count':count,'selected_clips':plan['selected_clips']})
    save(QA/'native_layout_plan.json',plan)
    with baseline.open('rb') as source:
        for clip in selected(data):
            row=rows[clip['id']-1]
            source.seek((movie['lba']+row['start_sector'])*SECTOR)
            raw=source.read((row['end_sector']-row['start_sector'])*SECTOR)
            out=SOURCE/('movie_%03d.str'%clip['id'])
            if out.exists():assert out.read_bytes()==raw,('Existing source differs',clip['id'])
            else:out.write_bytes(raw)
            print('Extracted movie%03d: %d native frames, %d sectors.'%
                  (clip['id'],row['frames'],len(raw)//SECTOR),flush=True)
    return plan


def preview():
    data=manifest();inv=inventory();out=QA/'previews';out.mkdir(parents=True,exist_ok=True)
    samples={10:[],65:[],71:[66,690]}
    for i in (10,65):
        clip=data['clips'][i-1];row=lettering.display_subtitles(clip)[0]
        samples[i]=[round((row['start']+row['voice_end'])/2*12)]
    reports=[];images=[]
    for i,frames in samples.items():
        clip=data['clips'][i-1]
        with av.open(str(SOURCE/('movie_%03d.str'%i)),format='psxstr') as source:
            for n,frame in enumerate(source.decode(video=0)):
                if n not in frames:continue
                image,report=lettering.render_frame(frame.to_image(),clip,n,data['credit_pages'])
                path=out/('movie_%03d_frame_%05d.png'%(i,n));image.save(path)
                report.update({'clip_id':i,'path':str(path),'native_size':list(image.size)})
                reports.append(report);images.append((i,n,image.copy()))
                if n==max(frames):break
    sheet=Image.new('RGB',(640,560),(24,24,24));draw=ImageDraw.Draw(sheet)
    for pos,(i,n,image) in enumerate(images):
        x=(pos%2)*320;y=(pos//2)*280
        draw.text((x+4,y+4),'movie %03d | frame %05d | native 1x'%(i,n),fill='white')
        sheet.paste(image,(x,y+24))
    sheet.save(out/'native_contact.png');save(out/'report.json',reports)
    print(json.dumps(reports,ensure_ascii=False,indent=2),flush=True)
    return reports


def resolve_java():
    """Find a usable Java; reject bad explicit overrides, skip OS stubs."""
    explicit=os.environ.get('STT2001_JAVA')
    candidates=[]
    if explicit:candidates.append((explicit,True))
    else:
        if os.environ.get('JAVA_HOME'):candidates.append((str(Path(os.environ['JAVA_HOME'])/'bin/java'),False))
        if shutil.which('java'):candidates.append((shutil.which('java'),False))
        pointer=ROOT/'tools/movie_runtime/java_path.txt'
        if pointer.is_file():candidates.append((pointer.read_text().strip(),False))
    for candidate,required in candidates:
        found=shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if found:
            try:
                check=subprocess.run([found,'-version'],capture_output=True,timeout=10)
                if check.returncode==0:return str(Path(found).resolve())
            except (OSError,subprocess.TimeoutExpired):pass
        if required:raise RuntimeError('STT2001_JAVA does not name a usable Java executable')
    raise FileNotFoundError('Java not found. Install Java17+ or set STT2001_JAVA/JAVA_HOME.')


def encoder_command():
    explicit=os.environ.get('STT2001_JPSXDEC_JAR') or os.environ.get('JPSXDEC_JAR')
    if explicit:
        jar=Path(explicit).expanduser().resolve()
        if not jar.is_file():raise FileNotFoundError('Configured jPSXdec JAR not found: '+str(jar))
        return [resolve_java(),'-Xmx2g','-jar',str(jar)]
    launcher=shutil.which('jpsxdec')
    if launcher:return [launcher]
    for folder in os.get_exec_path():
        jar=Path(folder)/'jpsxdec.jar'
        if jar.is_file():return [resolve_java(),'-Xmx2g','-jar',str(jar.resolve())]
    if JAR.is_file():return [resolve_java(),'-Xmx2g','-jar',str(JAR)]
    raise FileNotFoundError('jPSXdec not found. Set STT2001_JPSXDEC_JAR/JPSXDEC_JAR or put jpsxdec on PATH.')


def run_java(args,log):
    command=encoder_command()
    with log.open('w',encoding='utf-8') as out:
        subprocess.run(command+args,cwd=log.parent,
                       stdout=out,stderr=out,check=True)
    output=log.read_text(encoding='utf-8',errors='replace')
    assert 'Unable to compress' not in output and 'Error:' not in output,output[-3000:]


def prepare(clip,row):
    i=clip['id'];name='movie_%03d'%i;folder=ENCODED/name
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/(name+'.str');original=SOURCE/(name+'.str')
    expected=lettering.expected_frames(clip,row['frames']);expected_set=set(expected)
    # A repeat resumes only a fully verified result with unchanged inputs.
    if (folder/'report.json').exists():
        try:
            _,report=validate(clip,row,decode=False,parity=False)
            print('%s already validated (%d frames).'%(name,len(expected)),flush=True)
            return report
        except (AssertionError,KeyError,ValueError,FileNotFoundError):pass
    start=time.monotonic();shutil.copyfile(original,target)
    frames=folder/'frames';frames.mkdir(exist_ok=True)
    root=ET.Element('str-replace',version='0.3');changed=[];overlay=[]
    pages=manifest()['credit_pages']
    with av.open(str(original),format='psxstr') as source:
        for n,frame in enumerate(source.decode(video=0)):
            if n not in expected_set:continue
            assert (frame.width,frame.height)==(row['width'],row['height'])
            image,report=lettering.render_frame(frame.to_image(),clip,n,pages)
            path=frames/('%05d.png'%n);image.save(path)
            ET.SubElement(root,'replace',{'frame':str(n)}).text=str(path)
            changed.append(n);overlay.append(report)
    assert n+1==row['frames'] and changed==expected,(i,n+1,row['frames'])
    xml=folder/'replace.xml';ET.ElementTree(root).write(xml,encoding='utf-8',xml_declaration=True)
    save(folder/'overlays.json',overlay)
    print('%s rendered%d frames in%.1fs; encoding.'%(name,len(changed),time.monotonic()-start),flush=True)
    index=folder/(name+'.idx')
    run_java(['-f',str(target),'-x',str(index)],folder/'index.log')
    run_java(['-x',str(index),'-i','0','-replaceframes',str(xml)],folder/'encode.log')
    report={'id':i,'frames':n+1,'edited_frames':changed,'subtitle_count':len(clip['subtitles']),
            'source_sha256':digest(original),'encoded_sha256':digest(target),
            'manifest_sha256':digest(MANIFEST),'renderer_sha256':digest(Path(lettering.__file__)),
            'encoder':'jPSXdec2.1 beta; full changed frames; original frame/sector capacities',
            'elapsed_seconds':round(time.monotonic()-start,3)}
    save(folder/'report.json',report)
    _,verified=validate(clip,row,decode=True,parity=True)
    save(folder/'validation.json',verified)
    print('%s PASS: %d frames, %d changed sectors, %.1fs.'%
          (name,len(changed),verified['changed_video_sectors'],time.monotonic()-start),flush=True)
    return verified


def validate(clip,row,decode=True,parity=True):
    from check_movie_build import check_parity
    i=clip['id'];name='movie_%03d'%i;folder=ENCODED/name
    report=json.loads((folder/'report.json').read_text(encoding='utf-8'))
    assert report['id']==i and report['frames']==row['frames'],i
    a=(SOURCE/(name+'.str')).read_bytes();b=(folder/(name+'.str')).read_bytes()
    assert report['source_sha256']==hashlib.sha256(a).hexdigest(),i
    assert report['encoded_sha256']==hashlib.sha256(b).hexdigest(),i
    assert report['manifest_sha256']==digest(MANIFEST),i
    assert report['renderer_sha256']==digest(Path(lettering.__file__)),i
    expected=lettering.expected_frames(clip,row['frames']);edited=set(expected)
    assert report['edited_frames']==expected,i
    assert len(a)==len(b)==(row['end_sector']-row['start_sector'])*SECTOR,i
    changed=[];seen=set();audio=0;parity_chunks=[]
    for pos in range(0,len(a),SECTOR):
        old=a[pos:pos+SECTOR];new=b[pos:pos+SECTOR]
        if old[24:28]==MAGIC:
            chunk,chunks,frame,size,w,h=struct.unpack_from('<HHIIHH',new,28)
            if chunk==0:seen.add(frame-1)
            assert old[:36]==new[:36] and old[40:44]==new[40:44],(i,frame,chunk)
            assert size<=chunks*2016 and (w,h)==(row['width'],row['height']),(i,frame,size,chunks)
            if frame-1 not in edited:assert old==new,(i,'Untargeted frame changed',frame)
            elif old!=new:
                changed.append(pos//SECTOR)
                if parity:parity_chunks.append(new)
        else:
            assert old==new,(i,'XA/nonvideo sector changed',pos//SECTOR)
            audio+=(old[18]&14)==4
        if len(parity_chunks)==4096:
            check_parity(b''.join(parity_chunks));parity_chunks=[]
    if parity_chunks:check_parity(b''.join(parity_chunks))
    assert seen==set(range(row['frames'])) and audio==row['audio_sectors'],i
    assert changed,i
    if decode:
        count=0
        with av.open(str(folder/(name+'.str')),format='psxstr') as container:
            for frame in container.decode(video=0):
                assert (frame.width,frame.height)==(row['width'],row['height'])
                frame.to_ndarray(format='rgb24');count+=1
        assert count==row['frames'],(i,count,row['frames'])
    return b,dict(report,changed_video_sectors=len(changed),audio_sectors_unchanged=audio,
                  frame_counts_and_sector_allocations_unchanged=True,
                  native_decode_passed=decode,edc_ecc_passed=parity)


def all_validated(decode=True,parity=True,write_report=True):
    data=manifest();inv=inventory();reports=[]
    for clip in selected(data):
        _,report=validate(clip,inv[clip['id']-1],decode,parity);reports.append(report)
        print('Validated movie%03d.'%clip['id'],flush=True)
    summary={'status':'all_prepared_chinese_movies_validated','movies_replaced':len(reports),
             'edited_frames':sum(len(r['edited_frames']) for r in reports),
             'changed_video_sectors':sum(r['changed_video_sectors'] for r in reports),
             'audio_unchanged':True,'frame_counts_and_sector_allocations_unchanged':True,
             'font':'Cubic11','native_han_ink_pixels':11,'clips':reports,
             'emulator_verified':False}
    if write_report:save(QA/'encoded_validation.json',summary)
    return summary


def patch(path,dry_run=False):
    """Patch a caller-owned build copy. All source ranges validated first."""
    from check_movie_build import directory
    path=Path(path).resolve()
    immutable={BASELINE.resolve(),(ROOT/'work/output/STT2001_ZH_v0.2.2.bin').resolve()}
    source_meta=SOURCE/'source.json'
    if source_meta.is_file():
        original=json.loads(source_meta.read_text(encoding='utf-8')).get('source_bin')
        if original:immutable.add(Path(original).resolve())
    assert path not in immutable,'Refusing finalized baseline overwrite'
    assert path.stat().st_size==DISC_SIZE,'Output BIN size differs from original disc'
    inv=inventory();data=manifest();clips=selected(data);table=directory(path)
    assert table['MOVIE.STR']=={'lba':372,'size':333578240}
    # Validate all prepared replacements and output baseline ranges pre-write.
    report=all_validated(write_report=not dry_run)
    with path.open('rb') as target:
        for clip in clips:
            row=inv[clip['id']-1];original=SOURCE/('movie_%03d.str'%clip['id'])
            target.seek((372+row['start_sector'])*SECTOR)
            assert target.read(original.stat().st_size)==original.read_bytes(),('Movie baseline differs',clip['id'])
    if dry_run:return dict(report,dry_run=True,output_written=False)
    with path.open('r+b') as target:
        for clip in clips:
            row=inv[clip['id']-1];name='movie_%03d'%clip['id']
            target.seek((372+row['start_sector'])*SECTOR)
            target.write((ENCODED/name/(name+'.str')).read_bytes())
    return report


def verify_disc(path,baseline):
    from check_movie_build import directory,same_range
    path=Path(path);baseline=Path(baseline)
    assert path.stat().st_size==baseline.stat().st_size
    assert directory(path)==directory(baseline),'Disc directory/LBAs/sizes changed'
    inv=inventory();clips={c['id']:c for c in selected(manifest())};reports=[]
    start=372*SECTOR;end=start+inv[-1]['end_sector']*SECTOR
    with path.open('rb') as new,baseline.open('rb') as old:
        same_range(new,old,0,start);same_range(new,old,end,path.stat().st_size)
        cursor=start
        for row in inv:
            offset=start+row['start_sector']*SECTOR
            size=(row['end_sector']-row['start_sector'])*SECTOR
            if cursor<offset:same_range(new,old,cursor,offset)
            if row['id'] not in clips:same_range(new,old,offset,offset+size)
            else:
                expected,report=validate(clips[row['id']],row,decode=True,parity=True)
                new.seek(offset);assert new.read(size)==expected,('Actual disc stream differs',row['id'])
                old.seek(offset);assert old.read(size)==(SOURCE/('movie_%03d.str'%row['id'])).read_bytes()
                reports.append(report)
            cursor=offset+size
    result={'all_checks_passed':True,'bin_sha256':digest(path),'baseline':str(baseline),
            'disc_size':path.stat().st_size,'disc_directory_and_all_lbas_unchanged':True,
            'all_nonmovie_disc_bytes_identical':True,'unchanged_movie_count':len(inv)-len(clips),
            'movie_edc_ecc_sectors_verified':sum(r['changed_video_sectors'] for r in reports),
            'movies':reports,'native_decode_passed':True,'emulator_verified':False}
    save(QA/'actual_disc_verification.json',result)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['extract','preview','encode','validate','patch','verify-disc','dependencies'])
    p.add_argument('--ids');p.add_argument('--path',type=Path);p.add_argument('--baseline',type=Path)
    p.add_argument('--dry-run',action='store_true',help='Read-only extraction/patch plan; no outputs written')
    args=p.parse_args()
    if args.dry_run and args.action not in ('extract','patch','dependencies'):
        p.error('--dry-run is supported for extract, patch and dependencies')
    if args.action=='dependencies':print(json.dumps({'encoder_command':encoder_command(),'probe_only':True},indent=2))
    elif args.action=='extract':scan_extract(args.baseline or BASELINE,args.dry_run)
    elif args.action=='preview':preview()
    elif args.action=='encode':
        inv=inventory();ids={int(x) for x in args.ids.split(',')} if args.ids else None
        for clip in selected(manifest(),ids):prepare(clip,inv[clip['id']-1])
    elif args.action=='validate':print(json.dumps(all_validated(),ensure_ascii=False,indent=2))
    elif args.action=='patch':
        assert args.path;print(json.dumps(patch(args.path,args.dry_run),ensure_ascii=False,indent=2))
    elif args.action=='verify-disc':
        assert args.path and args.baseline;verify_disc(args.path,args.baseline)


if __name__=='__main__':main()
