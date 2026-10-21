"""Native Chinese movie lettering and layout; no source movie/image writes."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from movie_subtitles import display_subtitles
import zh_full_font

ROOT=Path(__file__).resolve().parents[1]
MANIFEST=ROOT/'work/translation/zh_CN/full_ui/movies.zh_CN.json'
FONT=ROOT/'incoming/Cubic11/Cubic_11.ttf'
CREDIT_MASKS=[(0,24,320,94),(0,94,132,206)]


@lru_cache(maxsize=1)
def font():return ImageFont.truetype(str(FONT),12)


@lru_cache(maxsize=1)
def cmap():return zh_full_font.font_codepoints(FONT)


def visual_text(text):
    result=[]
    for char in text:
        if char.isspace() or ord(char) in cmap():result.append(char)
        elif char in zh_full_font.GLYPH_FALLBACKS and ord(zh_full_font.GLYPH_FALLBACKS[char]) in cmap():
            result.append(zh_full_font.GLYPH_FALLBACKS[char])
        else:raise ValueError('No approved Cubic11 movie glyph for '+repr(char))
    return ''.join(result)


@lru_cache(maxsize=2048)
def lettering(text,outline=0):
    display=visual_text(text);box=font().getbbox(display)
    image=Image.new('L',(box[2]-box[0]+8,box[3]-box[1]+8))
    ImageDraw.Draw(image).text((4-box[0],4-box[1]),display,font=font(),fill=255)
    pixels=np.asarray(image);levels=set(np.unique(pixels).tolist())
    if levels-{0,255}:raise ValueError('Movie font introduced gray resampling')
    core=pixels>0;edge=np.zeros_like(core)
    for dy in range(-outline,outline+1):
        for dx in range(-outline,outline+1):edge|=np.roll(np.roll(core,dy,0),dx,1)
    mask=np.where(core,2,np.where(edge,1,0)).astype(np.uint8)
    ys,xs=np.nonzero(mask)
    if not len(xs):return np.zeros((0,0),np.uint8)
    return mask[ys.min():ys.max()+1,xs.min():xs.max()+1]


def wrap(text,width,outline=0):
    """Chinese character wrapping, preferring Latin spaces without losing text."""
    lines=[]
    for paragraph in text.split('\n'):
        if not paragraph:
            lines.append('');continue
        line=''
        for ch in paragraph:
            proposed=line+ch
            if line and lettering(proposed,outline).shape[1]>width:
                # Keep ordinary Latin words together when a useful space exists.
                split=line.rfind(' ')
                if ch.isascii() and ch.isalnum() and split>0:
                    lines.append(line[:split].rstrip());line=line[split+1:]+ch
                else:lines.append(line.rstrip());line=ch.lstrip()
            else:line=proposed
        if line:lines.append(line.rstrip())
    for line in lines:
        if line and lettering(line,outline).shape[1]>width:raise ValueError('Unbreakable movie line '+repr(line))
    return lines


def paint(image,text,x,y,outline=0,color=(255,255,255)):
    mask=lettering(text,outline);h,w=mask.shape
    if not w:return [x,y,x,y]
    if x<0 or y<0 or x+w>image.width or y+h>image.height:raise ValueError('Movie text exceeds native frame')
    pixels=np.asarray(image).copy();area=pixels[y:y+h,x:x+w]
    area[mask==1]=(0,0,0);area[mask==2]=color
    image.paste(Image.fromarray(pixels))
    return [x,y,x+w,y+h]


def caption_layout(text,width,height):
    lines=wrap(text,width-8,outline=1)
    if len(lines)>3:raise ValueError(f'Native caption needs{len(lines)}lines (>3): {text!r}')
    top=height-4-len(lines)*14
    result=[]
    for index,line in enumerate(lines):
        mask=lettering(line,1);h,w=mask.shape
        result.append({'text':line,'x':(width-w)//2,'y':top+14*index,'width':w,'height':h})
    return result


def caption(image,text):
    rows=caption_layout(text,image.width,image.height);bounds=[]
    for row in rows:bounds.append(paint(image,row['text'],row['x'],row['y'],outline=1))
    return {'text':text,'lines':[r['text'] for r in rows],'bounds':bounds,
            'font_point_size':12,'native_han_ink_pixels':11,'integer_scale':1}


def credit_layout(page):
    """Flow within the original L-shaped black credit-text areas only."""
    heading=wrap(page['heading'],296)
    if len(heading)>1:raise ValueError('Credit heading does not fit one line')
    result=[{'text':heading[0],'x':12,'y':28,'role':'heading'}]
    y=46
    for paragraph in page['body'].split('\n'):
        if not paragraph:y+=14;continue
        pending=paragraph
        while pending:
            width=296 if y<88 else 118
            lines=wrap(pending,width)
            line=lines[0]
            # wrap() only trims boundary whitespace; retain every source word.
            normalized=pending.lstrip()
            if not normalized.startswith(line):raise ValueError('Credit wrap lost source text')
            pending=normalized[len(line):].lstrip()
            if y>=88:y=max(y,96)
            if y+11>205:raise ValueError('Credit page overflows native mask: '+page['heading'])
            result.append({'text':line,'x':12,'y':y,'role':'body'});y+=14
    for row in result:
        mask=lettering(row['text']);h,w=mask.shape
        box=(row['x'],row['y'],row['x']+w,row['y']+h)
        if not any(a<=box[0] and b<=box[1] and c>=box[2] and d>=box[3] for a,b,c,d in CREDIT_MASKS):
            raise ValueError('Credit text exceeds existing mask: '+repr(row))
    return result


def credits(image,page):
    if image.size!=(320,240):raise ValueError('Credits require original320x240 frame')
    draw=ImageDraw.Draw(image)
    for x0,y0,x1,y1 in CREDIT_MASKS:draw.rectangle((x0,y0,x1-1,y1-1),fill='black')
    rows=credit_layout(page)
    for row in rows:row['bounds']=paint(image,row['text'],row['x'],row['y'])
    return {'heading':page['heading'],'body':page['body'],'rows':rows,
            'mask_rects':[list(r) for r in CREDIT_MASKS],'font_point_size':12,
            'native_han_ink_pixels':11,'integer_scale':1}


def page_at(clip,time,pages):
    if not clip.get('credits') or not 5<=time<=93:return None
    index=int((time-5)//4)
    return pages[index] if 0<=index<len(pages) else None


def active_frame(clip,time):
    return next((r for r in display_subtitles(clip) if r['start']<=time<r['end']),None)


def expected_frames(clip,count):
    rows=display_subtitles(clip)
    return [n for n in range(count) if any(r['start']<=n/12<r['end'] for r in rows)
            or (clip.get('credits') and 5<=n/12<=93)]


def render_frame(image,clip,n,pages):
    original=np.asarray(image).copy();report={};time=n/12
    row=active_frame(clip,time)
    if clip.get('credits') and 5<=time<=93:
        page=page_at(clip,time,pages)
        if page:report['credit']=credits(image,page)
        else:
            d=ImageDraw.Draw(image)
            for x0,y0,x1,y1 in CREDIT_MASKS:d.rectangle((x0,y0,x1-1,y1-1),fill='black')
            report['credit']='end_of_roll_clear'
    if row:report['caption']=caption(image,row['en'])
    changed=np.any(np.asarray(image)!=original,axis=2);allowed=np.zeros(changed.shape,bool)
    if row:
        for x0,y0,x1,y1 in report['caption']['bounds']:allowed[y0:y1,x0:x1]=True
    if 'credit' in report:
        for x0,y0,x1,y1 in CREDIT_MASKS:allowed[y0:y1,x0:x1]=True
    if np.any(changed&~allowed):raise ValueError('Overlay changed original frame outside measured text/mask pixels')
    report.update({'frame':n,'time':time,'changed_pixels':int(changed.sum()),'unchanged_pixels_outside_overlays':True})
    return image,report


def plan(manifest,inventory=None):
    full=interrupted=0;captions=[];characters=set();fallbacks={}
    for clip in manifest['clips']:
        width,height=(160,128) if clip['id']<=64 else (320,240)
        if inventory:
            item=inventory[clip['id']-1];width,height=item['width'],item['height']
            if abs(item['frames']/12-clip['duration'])>1/12:raise ValueError('Manifest/source duration mismatch')
        rows=display_subtitles(clip)
        for index,row in enumerate(rows):
            layout=caption_layout(row['en'],width,height);characters.update(row['en'])
            hold=row['end']-row.get('voice_end',row['end'])
            if hold>=0.5-1e-6:full+=1
            else:
                if index+1>=len(rows) or abs(row['end']-rows[index+1]['start'])>1e-6:raise ValueError('Caption hold cut before next-caption interruption')
                interrupted+=1
            captions.append({'clip_id':clip['id'],'start':row['start'],'end':row['end'],'voice_end':row.get('voice_end'),
                             'lines':[r['text'] for r in layout],'native_size':[width,height]})
    credit_rows=[]
    for index,page in enumerate(manifest['credit_pages']):
        characters.update(page['heading']+page['body']);rows=credit_layout(page)
        credit_rows.append({'page':index+1,'start':5+4*index,'end':9+4*index,'layout_rows':rows})
    for char in characters:
        visual_text(char)
        if not char.isspace() and ord(char) not in cmap():fallbacks[char]=zh_full_font.GLYPH_FALLBACKS[char]
    selected=[c['id'] for c in manifest['clips'] if c['subtitles'] or c.get('credits')]
    return {'status':'native_layout_and_timing_plan_passed','clips':len(manifest['clips']),
            'selected_clips':selected,'unmodified_clip_count':len(manifest['clips'])-len(selected),
            'caption_rows':len(captions),'clips_with_captions':sum(bool(c['subtitles']) for c in manifest['clips']),
            'shared_credit_pages':len(credit_rows),'full_half_second_holds':full,'next_caption_interruptions':interrupted,
            'font':'Cubic11','point_size':12,'native_han_ink_pixels':11,'glyph_fallbacks':fallbacks,
            'required_characters':len(characters),'captions':captions,'credits':credit_rows,
            'no_new_audio_transcription':True,'not_verified':['MDEC encoded video','actual-disc insertion','runtime playback']}
