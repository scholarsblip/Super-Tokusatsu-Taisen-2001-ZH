"""Reproducible narrated Chinese preview from verified same-build game captures.

Input JSON lists timed scenes with actual PNG/MP4 game sources, a short Chinese
title, explanatory lines, and local-TTS narration. No upload or publication.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/movie_runtime/pythonlib'))
import av
import numpy as np
from PIL import Image,ImageDraw,ImageFont

WIDTH,HEIGHT,FPS,RATE=1280,720,24,48000
FONT=Path('/System/Library/Fonts/Hiragino Sans GB.ttc')


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def save(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


@lru_cache(maxsize=12)
def font(size):return ImageFont.truetype(str(FONT),size)


def wrap(text,face,width):
    lines=[]
    for paragraph in text.split('\n'):
        line=''
        for char in paragraph:
            if line and face.getlength(line+char)>width:lines.append(line);line=char
            else:line+=char
        lines.append(line)
    return lines


def text(draw,xy,value,size=26,color='#e8edf4',width=264,pitch=None):
    face=font(size);x,y=xy
    for line in wrap(value,face,width):
        draw.text((x,y),line,font=face,fill=color);y+=pitch or size+12
    return y


class Media:
    def __init__(self,path,start=0):
        self.path=Path(path);self.start=start;self.container=None
        if self.path.suffix.lower() in ('.png','.jpg','.jpeg'):
            self.image=Image.open(self.path).convert('RGB');return
        self.container=av.open(str(self.path));stream=self.container.streams.video[0]
        self.rate=float(stream.average_rate or 60)
        self.iterator=iter(self.container.decode(video=0));self.index=0
        self.current=None;self.following=self.next()

    def next(self):
        frame=next(self.iterator,None)
        if frame is None:return None
        when=float(frame.time) if frame.time is not None else self.index/self.rate
        self.index+=1
        return when,frame.to_image()

    def at(self,seconds):
        if not self.container:return self.image
        target=self.start+seconds
        while self.following and (self.current is None or self.following[0]<=target):
            self.current=self.following;self.following=self.next()
        assert self.current,'Video has no decodable frames'
        return self.current[1]

    def close(self):
        if self.container:self.container.close()


def voice(path):
    pieces=[]
    with av.open(str(path)) as c:
        sampler=av.AudioResampler(format='fltp',layout='mono',rate=RATE)
        for frame in c.decode(audio=0):
            for converted in sampler.resample(frame):pieces.append(converted.to_ndarray()[0])
        for converted in sampler.resample(None):pieces.append(converted.to_ndarray()[0])
    assert pieces,'Narration audio empty'
    return np.concatenate(pieces).astype(np.float32)


def narration(spec,folder):
    seconds=sum(s['duration'] for s in spec['scenes'])
    samples=np.zeros(round(seconds*RATE),np.float32);cursor=0;reports=[]
    prior=json.loads((folder/'narration.json').read_text()) if (folder/'narration.json').exists() else []
    for index,scene in enumerate(spec['scenes']):
        raw=folder/('narration_%02d.txt'%index);raw.write_text(scene['narration'],encoding='utf-8')
        path=folder/('narration_%02d.aiff'%index);rate=190
        cached=(index<len(prior) and prior[index]['text']==scene['narration']
                and path.exists() and prior[index]['sha256']==sha(path))
        if cached:rate=prior[index]['rate']
        while True:
            if not cached:subprocess.run(['say','-v','Tingting','-r',str(rate),'-f',str(raw),'-o',str(path)],check=True)
            speech=voice(path)
            if len(speech)/RATE<=scene['duration']-1:break
            rate=round(rate*(len(speech)/RATE)/(scene['duration']-1)*1.03)
            assert rate<=280,('Narration too long',index)
            cached=False
        peak=float(np.max(np.abs(speech)));assert peak>0
        if peak>0.95:speech*=0.95/peak
        fade=min(480,len(speech)//2)
        speech[:fade]*=np.linspace(0,1,fade);speech[-fade:]*=np.linspace(1,0,fade)
        start=round((cursor+0.5)*RATE);samples[start:start+len(speech)]=speech
        reports.append({'scene':index,'text':scene['narration'],'voice':'macOS Tingting',
                        'rate':rate,'start':cursor+0.5,'duration':len(speech)/RATE,
                        'source_aiff':str(path),'sha256':sha(path)})
        cursor+=scene['duration']
    np.save(folder/'narration_mono48k.npy',samples)
    save(folder/'narration.json',reports)
    def stamp(seconds):
        ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
        return '%02d:%02d:%02d,%03d'%(h,m,s,ms)
    srt=[]
    for i,row in enumerate(reports):
        srt.extend([str(i+1),stamp(row['start'])+' --> '+stamp(row['start']+row['duration']),row['text'],''])
    (folder/'narration.zh_CN.srt').write_text('\n'.join(srt),encoding='utf-8')
    return samples


def compose(source,scene,spec,elapsed,total):
    canvas=Image.new('RGB',(WIDTH,HEIGHT),'#111923')
    # Fit each original4:3 capture at an integer pixel scale where possible.
    scale=min(960/source.width,720/source.height)
    size=(round(source.width*scale),round(source.height*scale))
    source=source.resize(size,Image.Resampling.NEAREST)
    canvas.paste(source,((960-size[0])//2,(720-size[1])//2))
    draw=ImageDraw.Draw(canvas);draw.rectangle((960,0,1279,719),fill='#111923')
    draw.rectangle((984,30,1034,35),fill='#eab552')
    text(draw,(984,52),'超级特摄大战',26,'#eab552')
    text(draw,(984,92),'2001',42,'#ffffff')
    text(draw,(984,151),'简体中文 · 全量机翻测试版',18,'#9daabc')
    draw.line((984,195,1256,195),fill='#344355',width=1)
    y=text(draw,(984,222),scene['title'],30,'#ffffff',pitch=44)
    y+=18
    y=text(draw,(984,y),scene['caption'],24,'#d3dce7',pitch=37)
    assert y<610,('Intro panel overflow',scene['title'],y)
    text(draw,(984,620),spec['version']+' · 模拟器实录',17,'#9daabc')
    text(draw,(984,650),'保留日语配音',17,'#9daabc')
    draw.rectangle((984,695,1255,698),fill='#344355')
    draw.rectangle((984,695,984+int(271*elapsed/total),698),fill='#eab552')
    return canvas


def build(spec_path,output,assets):
    spec=json.loads(spec_path.read_text(encoding='utf-8'))
    assert 90<=sum(s['duration'] for s in spec['scenes'])<=120
    assert sha(spec['game_bin'])==spec['game_bin_sha256'],'Final game BIN changed'
    assert assets.is_dir() or not assets.exists()
    assets.mkdir(parents=True,exist_ok=True);output.parent.mkdir(parents=True,exist_ok=True)
    proofs={}
    for scene in spec['scenes']:
        assert Path(scene['source']).is_file(),scene['source']
        proof_path=Path(scene['provenance_report'])
        proof=json.loads(proof_path.read_text(encoding='utf-8'))
        hashes=proof.get('game_components_sha256') or proof.get('recording',{}).get('game_components_sha256')
        assert hashes and spec['game_bin_sha256'] in hashes.values(),('Capture is not from final same build',proof_path)
        proofs[str(proof_path.resolve())]=sha(proof_path)
    save(assets/'original_edit_spec.json',spec)
    source_folder=assets/'sources';source_folder.mkdir(exist_ok=True)
    for scene in spec['scenes']:
        for key in ('source','provenance_report'):
            source_path=Path(scene[key]).resolve()
            copied=source_folder/(sha(source_path)[:8]+'_'+source_path.name)
            if not copied.exists():shutil.copyfile(source_path,copied)
            assert sha(copied)==sha(source_path)
            scene[key]=str(copied.resolve())
    save(assets/'edit_spec.json',spec)
    speech=narration(spec,assets);total=len(speech)/RATE
    subtitles=output.with_suffix('.zh_CN.srt')
    shutil.copyfile(assets/'narration.zh_CN.srt',subtitles)
    container=av.open(str(output),'w',options={'movflags':'+faststart'})
    video=container.add_stream('libx264',rate=FPS)
    video.width=WIDTH;video.height=HEIGHT;video.pix_fmt='yuv420p'
    video.options={'crf':'18','preset':'medium','profile':'high'}
    audio=container.add_stream('aac',rate=RATE);audio.layout='mono';audio.bit_rate=128000
    container.metadata.update({'title':'超级特摄大战2001 简体中文机翻测试版演示',
        'comment':'Actual same-build emulator captures; local synthetic Chinese narration; no publication.'})
    cursor=0;audio_cursor=0;frame_count=0;keyframes=[]
    for index,scene in enumerate(spec['scenes']):
        media=Media(scene['source'],scene.get('source_start',0));count=round(scene['duration']*FPS)
        for n in range(count):
            image=compose(media.at(n/FPS),scene,spec,cursor+n/FPS,total)
            if n==round(min(scene['duration']/2,3)*FPS):
                key=assets/('scene_%02d.png'%index);image.save(key);keyframes.append(str(key))
            frame=av.VideoFrame.from_image(image);frame.pts=frame_count;frame.time_base=Fraction(1,FPS)
            for packet in video.encode(frame):container.mux(packet)
            frame_count+=1
            upto=min(len(speech),round(frame_count/FPS*RATE))
            while audio_cursor+1024<=upto:
                af=av.AudioFrame.from_ndarray(speech[audio_cursor:audio_cursor+1024][None,:],format='fltp',layout='mono')
                af.sample_rate=RATE;af.pts=audio_cursor;af.time_base=Fraction(1,RATE)
                for packet in audio.encode(af):container.mux(packet)
                audio_cursor+=1024
        media.close();cursor+=scene['duration']
        print('Rendered intro scene%02d: %s'%(index,scene['title']),flush=True)
    if audio_cursor<len(speech):
        af=av.AudioFrame.from_ndarray(speech[audio_cursor:][None,:],format='fltp',layout='mono')
        af.sample_rate=RATE;af.pts=audio_cursor;af.time_base=Fraction(1,RATE)
        for packet in audio.encode(af):container.mux(packet)
    for stream in (video,audio):
        for packet in stream.encode(None):container.mux(packet)
    container.close()
    sources={str(Path(s['source']).resolve()):sha(s['source']) for s in spec['scenes']}
    result={'status':'encoded_pending_decode_validation','output':str(output.resolve()),
            'sha256':sha(output),'duration':total,'frames':frame_count,'size':output.stat().st_size,
            'width':WIDTH,'height':HEIGHT,'fps':FPS,'video_codec':'H264','audio_codec':'AAC',
            'subtitles':str(subtitles.resolve()),'subtitles_sha256':sha(subtitles),
            'scene_sources_sha256':sources,'spec_sha256':sha(spec_path),
            'provenance_reports_sha256':proofs,
            'game_bin_sha256':spec['game_bin_sha256'],'keyframes':keyframes,
            'generator_sha256':sha(Path(__file__)),'caption_font_sha256':sha(FONT),
            'game_capture_kind':'Actual final same-build emulator captures',
            'voice':'macOS Tingting synthetic narration','uploaded_or_published':False}
    save(assets/'build.json',result)
    return result


def verify(output,assets):
    report=json.loads((assets/'build.json').read_text(encoding='utf-8'))
    assert sha(output)==report['sha256']
    count=0
    with av.open(str(output)) as c:
        v=c.streams.video[0];assert v.codec_context.name=='h264'
        assert (v.width,v.height)==(WIDTH,HEIGHT) and v.codec_context.format.name=='yuv420p'
        assert abs(float(c.duration/av.time_base)-report['duration'])<0.1
        for f in c.decode(video=0):
            assert f.width==WIDTH and f.height==HEIGHT
            f.to_ndarray(format='rgb24');count+=1
    assert count==report['frames']
    audio_samples=0;peak=0
    with av.open(str(output)) as c:
        assert c.streams.audio[0].codec_context.name=='aac'
        for f in c.decode(audio=0):
            a=f.to_ndarray();peak=max(peak,float(np.max(np.abs(a))));audio_samples+=f.samples
    assert peak>0 and abs(audio_samples/RATE-report['duration'])<0.1
    sheet=Image.new('RGB',(960,270*((len(report['keyframes'])+2)//3)),'#111923')
    draw=ImageDraw.Draw(sheet)
    edit=json.loads((assets/'edit_spec.json').read_text(encoding='utf-8'))
    for i,path in enumerate(report['keyframes']):
        image=Image.open(path).resize((320,180),Image.Resampling.LANCZOS)
        sheet.paste(image,((i%3)*320,(i//3)*270))
        text(draw,((i%3)*320+8,(i//3)*270+190),
             '%02d  '%(i+1)+edit['scenes'][i]['title'].replace('\n',''),18,width=304)
    sheet.save(assets/'review_contact.png')
    report.update({'status':'complete_native_decode_passed','decoded_video_frames':count,
                   'decoded_audio_samples':audio_samples,'audio_peak':peak,
                   'review_contact':str((assets/'review_contact.png').resolve())})
    save(assets/'verification.json',report);return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--assets',required=True,type=Path)
    a=p.parse_args();build(a.spec,a.output,a.assets);r=verify(a.output,a.assets)
    print(json.dumps({k:v for k,v in r.items() if k not in ('scene_sources_sha256','keyframes')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
