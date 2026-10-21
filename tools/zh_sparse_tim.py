"""Sparse TIM restoration: distribute index changes, never the source artwork.

Applying a payload requires the user's exact original TIM (including padding).
The source CLUT, headers, padding and all pixels outside the mask are retained.
The create command is a dry run unless --write is explicitly supplied.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

import gfx

FORMAT='stt2001.tim-index-delta.v1'
KEYS={'format','source_sha256','result_sha256','width','height','bpp','byte_length',
      'rect','allowed_mask_runs','changed_runs','method'}


def sha(data):return hashlib.sha256(data).hexdigest()


def runs(mask):
    points=np.flatnonzero(mask.ravel())
    if not len(points):return []
    cuts=np.flatnonzero(np.diff(points)!=1)+1
    return [(int(a[0]),len(a)) for a in np.split(points,cuts)]


def mask_from_runs(rows,size):
    mask=np.zeros(size,bool);end=0
    for start,count in rows:
        if not isinstance(start,int) or not isinstance(count,int) or count<=0 or start<end or start+count>size:
            raise ValueError('Invalid/overlapping sparse mask run')
        mask[start:start+count]=True;end=start+count
    return mask


def create(source,restored,mask,rect):
    before,after=gfx.Tim(source),gfx.Tim(restored)
    if len(source)!=len(restored) or (before.w,before.h,before.bpp)!=(after.w,after.h,after.bpp):
        raise ValueError('Restoration changed TIM size or format')
    if before.clut!=after.clut:raise ValueError('Restoration changed the original CLUT')
    mask=np.asarray(mask,dtype=bool)
    if mask.shape!=before.idx.shape:raise ValueError('Mask dimensions differ from TIM')
    x0,y0,x1,y1=rect
    if not (0<=x0<x1<=before.w and 0<=y0<y1<=before.h):raise ValueError('Invalid restoration rectangle')
    allowed=np.zeros_like(mask);allowed[y0:y1,x0:x1]=True
    if np.any(mask&~allowed):raise ValueError('Mask exceeds restoration rectangle')
    changed=before.idx!=after.idx
    if np.any(changed&~mask):raise ValueError('Restoration modified original pixels outside the mask')
    check=gfx.Tim(source);check.idx[changed]=after.idx[changed]
    if check.bytes()!=restored:raise ValueError('Restoration changed headers/padding or non-index data')
    values=after.idx.ravel()
    payload={'format':FORMAT,'source_sha256':sha(source),'result_sha256':sha(restored),
             'width':before.w,'height':before.h,'bpp':before.bpp,'byte_length':len(source),
             'rect':list(rect),'allowed_mask_runs':[list(row) for row in runs(mask)],
             'changed_runs':[[start,base64.b64encode(values[start:start+count].tobytes()).decode('ascii')]
                             for start,count in runs(changed)],
             'method':'AI-reconstructed hidden title-band artwork; sparse original-CLUT indices only. Not ground truth.'}
    if apply(source,payload)!=restored:raise ValueError('Sparse restoration round trip failed')
    return payload


def apply(source,payload):
    if set(payload)!=KEYS or payload['format']!=FORMAT:raise ValueError('Unsupported sparse TIM payload')
    if sha(source)!=payload['source_sha256']:raise ValueError('Original TIM SHA256 does not match restoration payload')
    tim=gfx.Tim(source)
    if (tim.w,tim.h,tim.bpp,len(source))!=(payload['width'],payload['height'],payload['bpp'],payload['byte_length']):
        raise ValueError('Original TIM dimensions/length differ from payload')
    count=tim.w*tim.h;allowed=mask_from_runs(payload['allowed_mask_runs'],count)
    x0,y0,x1,y1=payload['rect'];rectangle=np.zeros_like(tim.idx,dtype=bool)
    if not (0<=x0<x1<=tim.w and 0<=y0<y1<=tim.h):raise ValueError('Invalid payload rectangle')
    rectangle[y0:y1,x0:x1]=True
    if np.any(allowed&~rectangle.ravel()):raise ValueError('Payload mask exceeds title band')
    original=tim.idx.copy();flat=tim.idx.ravel();end=0
    for start,encoded in payload['changed_runs']:
        values=np.frombuffer(base64.b64decode(encoded,validate=True),np.uint8)
        stop=start+len(values)
        if not len(values) or not isinstance(start,int) or start<end or stop>count:
            raise ValueError('Invalid/overlapping sparse index run')
        if not np.all(allowed[start:stop]) or np.any(values>=tim.ncol):
            raise ValueError('Sparse indices exceed mask or original palette')
        if np.any(values==flat[start:stop]):raise ValueError('Payload contains unchanged source pixels')
        flat[start:stop]=values;end=stop
    if np.any((tim.idx!=original).ravel()&~allowed):raise ValueError('Sparse restoration exceeded mask')
    result=tim.bytes()
    if sha(result)!=payload['result_sha256']:raise ValueError('Restored TIM SHA256 mismatch')
    return result


def summary(payload):
    return {'format':payload['format'],'source_sha256':payload['source_sha256'],
            'result_sha256':payload['result_sha256'],'width':payload['width'],'height':payload['height'],
            'allowed_mask_pixels':sum(count for _,count in payload['allowed_mask_runs']),
            'changed_pixels':sum(len(base64.b64decode(row[1])) for row in payload['changed_runs']),
            'contains_source_palette_or_background':False}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['create','apply'])
    p.add_argument('--source-tim',required=True,type=Path);p.add_argument('--restored-tim',type=Path)
    p.add_argument('--mask',type=Path);p.add_argument('--rect',type=int,nargs=4,default=[14,91,307,142])
    p.add_argument('--payload',type=Path);p.add_argument('--output',type=Path);p.add_argument('--write',action='store_true')
    a=p.parse_args();source=a.source_tim.read_bytes()
    if a.action=='create':
        if not a.restored_tim or not a.mask:p.error('create requires --restored-tim and --mask')
        payload=create(source,a.restored_tim.read_bytes(),np.asarray(Image.open(a.mask).convert('L'))>0,a.rect)
        result=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode('utf-8')+b'\n'
    else:
        if not a.payload:p.error('apply requires --payload')
        payload=json.loads(a.payload.read_text(encoding='utf-8'));result=apply(source,payload)
    if a.write:
        if not a.output:p.error('--write requires --output')
        if a.output.resolve()==a.source_tim.resolve():p.error('Refusing original TIM overwrite')
        a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_bytes(result)
    print(json.dumps(dict(summary(payload),mode='write' if a.write else 'dry_run',output_written=a.write),indent=2))


if __name__=='__main__':main()
