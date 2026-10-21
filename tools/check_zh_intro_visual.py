"""Reopen the delivered MP4 and export actual encoded frames for visual QA."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/movie_runtime/pythonlib'))
import av
from PIL import Image,ImageDraw,ImageFont


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('video',type=Path);p.add_argument('assets',type=Path);a=p.parse_args()
    edit=json.loads((a.assets/'edit_spec.json').read_text(encoding='utf-8'))
    checkpoints={};cursor=0
    for i,scene in enumerate(edit['scenes']):
        checkpoints[round((cursor+min(scene['duration']/2,3))*24)]=(i,scene)
        cursor+=scene['duration']
    rows=[]
    with av.open(str(a.video)) as c:
        for n,frame in enumerate(c.decode(video=0)):
            if n not in checkpoints:continue
            i,scene=checkpoints[n];dest=a.assets/('encoded_scene_%02d.png'%i)
            frame.to_image().save(dest)
            rows.append({'scene':i,'title':scene['title'],'frame':n,'time':n/24,'image':str(dest.resolve())})
            if len(rows)==len(checkpoints):break
    assert len(rows)==len(checkpoints)
    sheet=Image.new('RGB',(1280,280*((len(rows)+2)//3)),'#111923')
    draw=ImageDraw.Draw(sheet);face=ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc',18)
    for i,row in enumerate(rows):
        x=(i%3)*426;y=(i//3)*280
        image=Image.open(row['image']).resize((426,240),Image.Resampling.LANCZOS)
        sheet.paste(image,(x,y));draw.text((x+6,y+245),row['title'].replace('\n',''),font=face,fill='white')
    contact=a.assets/'encoded_review_contact.png';sheet.save(contact)
    with a.video.open('rb') as f:checksum=hashlib.file_digest(f,'sha256').hexdigest()
    report={'status':'actual_encoded_frames_exported_for_visual_review','video':str(a.video.resolve()),
            'video_sha256':checksum,'frames':rows,'contact':str(contact.resolve())}
    (a.assets/'encoded_visual_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
