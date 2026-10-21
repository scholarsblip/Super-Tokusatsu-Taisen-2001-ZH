"""Measured native raster UI localization with Cubic11 and unchanged CLUTs.

Only selected menu/option/disclaimer/narration assets are included. This does
not claim that every raster label, episode card or protagonist description is
translated. No source assets are changed. patch_files modifies a caller-owned
dictionary of DAT bytes; the CLI performs previews/structural QA only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import cm
import gfx
import repack

ROOT=Path(__file__).resolve().parents[1]
FONT=ROOT/'incoming/Cubic11/Cubic_11.ttf'
OUT=ROOT/'work/translation/zh_CN/graphics'


def targets():
    """Preserve measured ink/sprite rectangles, including both title copies."""
    menu=[
        {'rect':[40,1,86,14],'zh_CN':'开始','size':11},
        {'rect':[25,17,101,30],'zh_CN':'继续','size':11},
        {'rect':[34,33,91,46],'zh_CN':'设置','size':11},
        {'rect':[0,208,162,226],'zh_CN':'人物图鉴','size':16},
        {'rect':[44,232,120,251],'zh_CN':'退出','size':17},
    ]
    result=[{'archive':'MAPMAIN','entry':22,'kind':'main_menu','regions':[r['rect'] for r in menu],'labels':menu},
            {'archive':'MAPMAIN','entry':23,'block':1,'kind':'main_menu','regions':[r['rect'] for r in menu],'labels':menu}]
    manifest=json.loads((ROOT/'work/translation/zh_CN/graphics.zh.json').read_text())
    for t in manifest['targets']:
        if t['kind'] in ('options','disclaimer','narration'):
            result.append(t)
    return result


def lettering(text,size,outline=0):
    # Cubic11 is a pixel font: fractional scaling makes one-pixel strokes
    # disappear after palette quantisation. Render native11px, then enlarge
    # by an integer factor only.
    scale=max(1,size//11)
    f=ImageFont.truetype(str(FONT),11)
    box=f.getbbox(text)
    im=Image.new('L',(box[2]-box[0]+8,box[3]-box[1]+8))
    ImageDraw.Draw(im).text((4-box[0],4-box[1]),text,font=f,fill=255)
    core=np.asarray(im)>110
    edge=np.zeros_like(core)
    for dy in range(-outline,outline+1):
        for dx in range(-outline,outline+1):
            edge|=np.roll(np.roll(core,dy,0),dx,1)
    mask=np.where(core,2,np.where(edge,1,0)).astype(np.uint8)
    ys,xs=np.nonzero(mask)
    if not len(xs):
        raise ValueError('Empty raster label '+repr(text))
    mask=mask[ys.min():ys.max()+1,xs.min():xs.max()+1]
    if scale>1:
        mask=np.repeat(np.repeat(mask,scale,0),scale,1)
    return mask


def label(t,row,style='plain'):
    text=row.get('zh_CN',row.get('en'))
    if chr(92)+'u3000' in text:
        raise ValueError('Literal Unicode escape in raster text; fix manifest')
    x0,y0,x1,y1=row['rect']
    assert 0<=x0<x1<=t.w and 0<=y0<y1<=t.h
    outline=1 if style=='main_menu' else 0
    maxscale=2 if style=='options' and y1-y0>=24 else max(1,row.get('size',11)//11)
    for scale in range(maxscale,0,-1):
        size=scale*11
        mask=lettering(text,size,outline)
        h,w=mask.shape
        if h<=y1-y0 and w<=x1-x0:
            break
    else:
        raise ValueError('Chinese label cannot fit measured rect: '+repr(row))
    x=x0+(x1-x0-w)//2;y=y0+(y1-y0-h)//2
    dst=t.idx[y:y+h,x:x+w]
    if style=='main_menu':
        dst[mask==1]=t.nearest((0,80,32))
        for i in range(h):
            rgb=tuple(round(a+(b-a)*i/max(h-1,1)) for a,b in zip((238,255,238),(0,160,64)))
            dst[i,mask[i]==2]=t.nearest(rgb)
    else:
        dst[mask==2]=t.nearest(row.get('color',(255,255,255)))
    return {'text':text,'font':'Cubic11','font_size':size,'bounds':[x,y,x+w,y+h],
            'measured_rect':row['rect']}


def render(data,target):
    t=gfx.Tim(data)
    kind=target['kind']
    if kind in ('disclaimer','narration'):
        rect=target['regions'][0]
        t.fill(*rect,int(t.idx[rect[1],5]))
    labels=[]
    for row in target['labels']:
        if kind=='main_menu':
            t.fill(*row['rect'],0)
        elif kind=='options':
            t.fill(*row['rect'],t.nearest(row['background']))
        labels.append(label(t,row,kind))
    return t.bytes(),labels


def verify(before,after,target):
    a,b=gfx.Tim(before),gfx.Tim(after)
    assert len(before)==len(after),'TIM resource size changed'
    pixbytes=a.idx.size//(2 if a.bpp==0 else 1)
    assert before[:a.pix_off]==after[:b.pix_off],'TIM header or CLUT changed'
    assert before[a.pix_off+pixbytes:]==after[b.pix_off+pixbytes:],'TIM trailing data changed'
    allowed=np.zeros(a.idx.shape,bool)
    for x0,y0,x1,y1 in target['regions']:
        allowed[y0:y1,x0:x1]=True
    changed=a.idx!=b.idx
    assert not np.any(changed&~allowed),'Pixel changed outside measured rectangles'
    return {'changed_pixels':int(changed.sum()),'palette_preserved':True,
            'sprite_bounds_preserved':True,'resource_size_preserved':True,'size':[a.w,a.h]}


def replace_cm(buf,replacements):
    pos=0;out=bytearray();i=0
    while buf[pos:pos+2]==b'CM':
        old,nxt=cm.decompress(buf,pos)
        if i in replacements:
            packed=cm.compress(replacements[i])
            assert cm.decompress(packed)[0]==replacements[i]
            out+=packed
        else:
            out+=buf[pos:nxt]
        pos=nxt;i+=1
    assert all(k<i for k in replacements)
    out+=buf[pos:]
    return bytes(out)


def source(target):
    data=(ROOT/'work/source/unpacked'/target['archive']/('%04d.bin'%target['entry'])).read_bytes()
    return cm.blocks(data)[target['block']] if 'block' in target else data


def name(target):
    return target['archive']+'_%04d'%target['entry']+('_b%d'%target['block'] if 'block' in target else '')


def rgb(data):
    t=gfx.Tim(data)
    return Image.fromarray(np.asarray(t.palette,np.uint8)[t.idx.astype(np.int32)%len(t.palette)])


def patch_files(files,selected=None,previews=False):
    selected=targets() if selected is None else selected
    report=[]
    for archive in sorted(set(t['archive'] for t in selected)):
        key=archive+'.DAT'
        entries=repack.dat_entries(files[key])
        for target in [t for t in selected if t['archive']==archive]:
            i=target['entry']
            if 'block' in target:
                k=target['block'];old_blocks=cm.blocks(entries[i]);before=old_blocks[k]
            else:
                before=entries[i]
            after,labels=render(before,target)
            qa=verify(before,after,target)
            if 'block' in target:
                entries[i]=replace_cm(entries[i],{k:after})
                new_blocks=cm.blocks(entries[i])
                assert new_blocks[k]==after
                assert all(a==b for j,(a,b) in enumerate(zip(old_blocks,new_blocks)) if j!=k)
            else:
                entries[i]=after
            report.append({'asset':name(target),'kind':target['kind'],**qa,'labels':labels,
                           'runtime_verified':False})
            if previews:
                OUT.mkdir(parents=True,exist_ok=True)
                left,right=rgb(before),rgb(after)
                pair=Image.new('RGB',(left.width+right.width+8,max(left.height,right.height)),(55,0,55))
                pair.paste(left,(0,0));pair.paste(right,(left.width+8,0))
                pair.resize((pair.width*2,pair.height*2),Image.Resampling.NEAREST).save(OUT/(name(target)+'_before_after.png'))
        files[key]=repack.dat_pack(entries)
    return report


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--preview',action='store_true');args=ap.parse_args()
    selected=targets()
    files={a+'.DAT':(ROOT/'work/source/disc'/(a+'.DAT')).read_bytes() for a in set(t['archive'] for t in selected)}
    report=patch_files(files,selected,args.preview)
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'raster_UI_report.json').write_text(json.dumps({'status':'structural_checks_passed_runtime_pending','assets':report},ensure_ascii=False,indent=2)+'\n')
    print('Dry run:',len(report),'raster assets;',sum(len(r['labels']) for r in report),'labels; no source asset written.')


if __name__=='__main__':
    main()
