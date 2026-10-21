"""Chinese prototype fonts without overwriting used Japanese glyphs.

This module has two deliberately distinct routes:
  unused: font-specific unused variable slots; no TIM size changes.
  extension: fixed original glyphs + new codes1454..2125 on pages3/4.
The latter changes resource sizes and is EXPERIMENTAL until the native loader,
RAM allocation and VRAM destination are checked in an emulator.
No original asset is modified by this module. The CLI writes a plan/preview only.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from kana_table import TABLE

VARIABLE = set(range(446, 782)) | set(range(1118, 1454))
FIXED = set(range(320, 446)) | set(range(782, 1118))
EXT_FIRST, EXT_COUNT = 1454, 336
CONTROL = re.compile(r'<[^>]*>|\[(?:HERO[1-4]|VAR[56])\]|\{[^}]*\}')
ALIASES = dict(zip('?!,:;()[]+-/%', '！？，：；（）［］＋－／％'))


def variable(code):
    return code in VARIABLE


def original_map(variant='11', stable=False):
    maps = json.loads((ROOT / 'work/font/variant_maps.json').read_text())
    result = {int(k): v for k, v in maps[str(variant)].items()}
    if stable:
        result = {k: v for k, v in result.items() if k in FIXED}
    result.update(TABLE)
    return result


def audit_usage():
    """Union current dump and frozen occurrence map; never alter either file."""
    rows = []
    for p in (ROOT / 'work/script/ja/strings.json', ROOT / 'work/script/occurrences.json'):
        if p.exists():
            rows.extend(json.loads(p.read_text()))
    seen, buffers, used = set(), {}, defaultdict(set)
    for r in rows:
        key = (r['file'], r['off'], str(r['font']))
        if key in seen:
            continue
        seen.add(key)
        if r['file'] == 'SLPS':
            path = ROOT / 'work/source/disc/SLPS_028.63'
        else:
            m = re.fullmatch(r'([A-Z]+)(\d{4})', r['file'])
            if not m:
                raise ValueError('Unknown source file ' + r['file'])
            path = ROOT / 'work/source/unpacked' / m[1] / (m[2] + '.bin')
        if path not in buffers:
            buffers[path] = path.read_bytes()
        b = buffers[path]
        off = r['off']
        while off + 2 <= len(b):
            w = struct.unpack_from('<H', b, off)[0]
            off += 2
            if w in (0xFFFE, 0xFFFD):
                break
            if w < 0xFF00:
                used[str(r['font'])].add(w)
        else:
            raise ValueError('No string terminator at %r' % (key,))
    return dict(used)


def required_chars(texts):
    return set(''.join(CONTROL.sub('', s).replace('\n', '') for s in texts))


def plan(texts, variant='11', mode='unused', usage=None, capacity=336):
    if mode not in ('unused', 'extension'):
        raise ValueError(mode)
    original = original_map(variant, stable=mode == 'extension')
    encode = {}
    for code in sorted(original):
        ch = original[code]
        if len(ch) == 1:
            encode.setdefault(ch, code)
    aliases = {}
    for ch, native in ALIASES.items():
        if ch not in encode and native in encode:
            encode[ch] = encode[native]
            aliases[ch] = native
    required = required_chars(texts)
    missing = sorted(required - set(encode))
    if mode == 'unused':
        usage = audit_usage() if usage is None else usage
        # The upper tail includes native elemental badges and runtime symbols.
        required_original_codes={encode[ch] for ch in required if ch in encode}
        slots = sorted(VARIABLE - usage.get(str(variant), set()) - set(range(1425, 1454)) - required_original_codes)
    else:
        if capacity not in (336,672):
            raise ValueError('Extension capacity must be336 or672')
        slots = list(range(EXT_FIRST, EXT_FIRST + capacity))
    if len(missing) > len(slots):
        raise ValueError('%s font %s needs %d additional glyphs, only %d slots available' % (mode, variant, len(missing), len(slots)))
    new = {ch: slots[i] for i, ch in enumerate(missing)}
    overwritten=set(new.values())
    encode={ch:code for ch,code in encode.items() if code not in overwritten}
    encode.update(new)
    return {'mode': mode, 'variant': str(variant), 'cell_width': 12, 'cell_height': 16,
            'new_glyphs': new, 'encode': encode, 'aliases': aliases,
            'slots_available': len(slots), 'required_characters': len(required_chars(texts)),
            'new_glyph_count': len(new), 'original_resource_pixels_preserved': mode == 'extension',
            'runtime_verified': False,
            'risk': ('Context-specific map: use only while this font bank is active; corpus-unused does not prove undocumented runtime references.'
                     if mode == 'unused' else 'Loader, buffer sizes and VRAM occupancy need emulator validation. BATTLE encyclopedia already uses page3 but other modes may not.')}


def render_code_cells(code_to_char,font_path=None,size=11,narrow='error'):
    """One font/baseline for translated native and added glyphs.

    Narrow native cells are8x16; wide cells are12x16. Native narrow CJK
    and kana can exceed8px, requiring an explicit skip/compress decision.
    The returned dictionary omits skipped cells. This function does not
    assert an old code's semantic mapping: the caller must provide the
    appropriate source-bank character map.
    """
    font_path=font_path or ROOT/'incoming/Cubic11/Cubic_11.ttf'
    if narrow not in ('error','skip','compress'):
        raise ValueError(narrow)
    font = ImageFont.truetype(str(font_path), size)
    result = {}
    for code,ch in code_to_char.items():
        code=int(code)
        if len(ch)!=1:
            raise ValueError('Expected one character for code%d: %r'%(code,ch))
        width=8 if code<320 else 12
        mask=Image.new('L',(40,24))
        # A common y-origin keeps punctuation on the same baseline as Han.
        ImageDraw.Draw(mask).text((8,1),ch,font=font,fill=255)
        a=np.asarray(mask)
        ys,xs=np.nonzero(a>=64)
        if not len(xs):
            if ch.isspace():
                result[code]=np.zeros((16,width),np.uint8)
                continue
            raise ValueError('Empty glyph '+repr(ch))
        if ys.max()>=16:
            raise ValueError('Glyph exceeds16px line box: '+repr(ch))
        ink=a[:16,xs.min():xs.max()+1]
        if ink.shape[1]>width:
            if width==8 and narrow=='skip':
                continue
            if width==8 and narrow=='compress':
                ink=np.asarray(Image.fromarray(ink).resize((width,16),Image.Resampling.NEAREST))
            else:
                raise ValueError('Glyph%r for code%d is%dpx wide but cell is%dpx; choose explicitnarrow policy'%(ch,code,ink.shape[1],width))
        a=np.zeros((16,width),np.uint8)
        x=(width-ink.shape[1])//2
        a[:,x:x+ink.shape[1]]=ink
        cell=np.where(a>=160,3,np.where(a>=64,2,0)).astype(np.uint8)
        result[code]=cell
    return result


def render_cells(p,font_path,size=11):
    """Render added glyphs with the uniform native11px baseline."""
    return render_code_cells({code:ch for ch,code in p['new_glyphs'].items()},font_path,size)


def tim_pixels(tim):
    if tim[:4] != b'\x10\0\0\0' or struct.unpack_from('<I',tim,4)[0] & 7:
        raise ValueError('Expected4bpp TIM')
    pos=8
    if struct.unpack_from('<I',tim,4)[0] & 8:
        pos += struct.unpack_from('<I',tim,pos)[0]
    length,x,y,w,h=struct.unpack_from('<IHHHH',tim,pos)
    raw=np.frombuffer(tim[pos+12:pos+12+w*2*h],np.uint8).reshape(h,w*2)
    pix=np.empty((h,w*4),np.uint8)
    pix[:,0::2]=raw&15
    pix[:,1::2]=raw>>4
    return pix,pos,length,(x,y,w,h)


def cell_location(code, sheet='main',layout='linear'):
    if layout not in ('linear','dual_plane'):
        raise ValueError(layout)
    if code < 320:
        return (code%32)*8,(code//32)*16,0
    dual_second=layout=='dual_plane' and 1790<=code<2126
    if dual_second:
        code-=336
    a=code-110
    page,r=divmod(a,336)
    shift=0
    if code>=782:
        page-=2
        if code<1454:
            shift=2
    if dual_second:
        shift=2
    if sheet=='variant':
        if page != 1:
            raise ValueError('Code is not on a variable page: '+str(code))
        page=0
    return page*256+(r%21)*12,(r//21)*16,shift


def patch_tim(tim,cells,sheet='main',mode='unused',layout='linear',allow_redraw=False):
    pix,pos,length,(x,y,w,h)=tim_pixels(tim)
    if mode=='extension':
        if sheet!='main' or pix.shape[1] not in (512,768,1024):
            raise ValueError('Extension requires a512px,768px or1024px full font sheet')
        if not allow_redraw and any(int(c)<1454 for c in cells):
            raise ValueError('Redrawing original codes requires allow_redraw=True')
        needed=max([pix.shape[1]]+[cell_location(int(c),sheet,layout)[0]+(8 if int(c)<320 else 12) for c in cells])
        needed=((needed+255)//256)*256
        if needed>(768 if layout=='dual_plane' else 1024):
            raise ValueError('Extension exceeds four texture pages')
        if needed>pix.shape[1]:
            pix=np.pad(pix,((0,0),(0,needed-pix.shape[1])))
    else:
        pix=pix.copy()
    for code,cell in cells.items():
        cx,cy,shift=cell_location(int(code),sheet,layout)
        cell=np.asarray(cell,np.uint8)
        width=8 if int(code)<320 else 12
        if cell.shape != (16,width) or cell.max()>3:
            raise ValueError('Bad2bpp cell')
        if cy+16>pix.shape[0] or cx+width>pix.shape[1]:
            raise ValueError('Glyph outside TIM: '+str(code))
        mask=15^(3<<shift)
        pix[cy:cy+16,cx:cx+width]=(pix[cy:cy+16,cx:cx+width]&mask)|(cell<<shift)
    packed=(pix[:,0::2]|(pix[:,1::2]<<4)).astype(np.uint8).tobytes()
    header=bytearray(tim[:pos+12])
    struct.pack_into('<IHHHH',header,pos,12+len(packed),x,y,pix.shape[1]//4,h)
    return bytes(header)+packed+tim[pos+length:]


def validate_tim(before,after,cells,sheet='main',mode='unused',layout='linear',allow_redraw=False):
    old,*_=tim_pixels(before)
    new,*_=tim_pixels(after)
    expected=patch_tim(before,cells,sheet,mode,layout,allow_redraw)
    assert after==expected,'Unexpected TIM change'
    if mode=='extension' and not allow_redraw:
        assert np.array_equal(old,new[:,:old.shape[1]]),'Original glyph pixels changed'
    old_expanded=np.pad(old,((0,0),(0,new.shape[1]-old.shape[1])))
    allowed=np.zeros(new.shape,np.uint8)
    for code,cell in cells.items():
        x,y,s=cell_location(int(code),sheet,layout)
        width=8 if int(code)<320 else 12
        allowed[y:y+16,x:x+width]|=3<<s
        assert np.array_equal((new[y:y+16,x:x+width]>>s)&3,cell),'Stored cell differs'
    assert not np.any((old_expanded^new)&(15^allowed)),'Unexpected change outside intended glyph bitplanes'
    return {'cells_verified':len(cells),'original_shape':list(old.shape),'new_shape':list(new.shape),
            'entire_original_font_preserved':bool(np.array_equal(old,new[:,:old.shape[1]])),
            'outside_intended_cells_preserved':True,'layout':layout,'allow_redraw':allow_redraw,'runtime_verified':False}


def resident_atlas_pixels(tim):
    """Read the resident 8bpp UI sheet as physical4bpp font texels."""
    if tim[:4]!=b'\x10\0\0\0' or struct.unpack_from('<I',tim,4)[0]!=9:
        raise ValueError('Expected resident8bpp TIM with CLUT')
    pos=8+struct.unpack_from('<I',tim,8)[0]
    length,x,y,w,h=struct.unpack_from('<IHHHH',tim,pos)
    if w not in (256,320) or h!=240 or length!=12+w*h*2:
        raise ValueError('Expected resident UI sheet256/320words by240rows')
    raw=np.frombuffer(tim[pos+12:pos+length],np.uint8).reshape(h,w*2)
    pix=np.empty((h,w*4),np.uint8);pix[:,0::2]=raw&15;pix[:,1::2]=raw>>4
    return pix,pos,length


def resident_atlas_location(code,code_base=1790):
    """Map new codes into upper page10 below the reserved48pixel sprite band."""
    index=int(code)-code_base
    if not 0<=index<504:raise ValueError('Resident atlas capacity is504glyphs')
    plane,slot=divmod(index,252);row,col=divmod(slot,21)
    return col*12,48+row*16,plane*2


def patch_resident_atlas(tim,cells,code_base=1790):
    """Prepend an atlas to the resident UI sheet, preserving every native texel.

    The source image256words wide is expanded to320words by prepending64words
    per row. The builder must move its runtime upload origin704->640 so all
    original portraits remain at their original physical coordinates. The new
    page10 atlas occupies y48..239; its first48rows are reserved for the game's
    later40pixel-high sprite uploads. Two252cell planes provide504codes.
    GPU traces establish availability for the tested opening scenes; further
    runtime coverage still requires validation.
    """
    original,pos,length=resident_atlas_pixels(tim)
    if original.shape!=(240,1024):raise ValueError('Resident atlas input is already expanded')
    pix=np.concatenate([np.zeros((240,256),np.uint8),original],axis=1)
    for code,cell in cells.items():
        x,y,shift=resident_atlas_location(code,code_base);cell=np.asarray(cell,np.uint8)
        if cell.shape!=(16,12) or cell.max()>3:raise ValueError('Bad resident atlas cell')
        region=pix[y:y+16,x:x+12];region[:]=(region&(15^(3<<shift)))|(cell<<shift)
    packed=(pix[:,0::2]|(pix[:,1::2]<<4)).astype(np.uint8).tobytes()
    header=bytearray(tim[:pos+12]);old_length,x,y,w,h=struct.unpack_from('<IHHHH',tim,pos)
    struct.pack_into('<IHHHH',header,pos,12+len(packed),x,y,320,h)
    return bytes(header)+packed+tim[pos+length:]


def validate_resident_atlas(before,after,cells,code_base=1790):
    old,pos,length=resident_atlas_pixels(before);new,npos,nlength=resident_atlas_pixels(after)
    assert len(after)==len(before)+30720 and pos==npos and nlength==length+30720
    assert before[:pos]==after[:pos],'TIM flags or CLUT changed'
    original_header=struct.unpack_from('<IHHHH',before,pos);new_header=struct.unpack_from('<IHHHH',after,pos)
    assert new_header==(original_header[0]+30720,original_header[1],original_header[2],320,240)
    assert before[pos+length:]==after[pos+nlength:],'Trailing resource bytes changed'
    assert np.array_equal(old,new[:,256:]),'Native portrait pixels changed'
    padded=np.concatenate([np.zeros((240,256),np.uint8),old],axis=1)
    allowed=np.zeros(new.shape,np.uint8)
    for code,cell in cells.items():
        x,y,shift=resident_atlas_location(code,code_base)
        allowed[y:y+16,x:x+12]|=3<<shift
        assert np.array_equal((new[y:y+16,x:x+12]>>shift)&3,cell),'Stored resident cell differs'
    assert not np.any((padded^new)&(15^allowed)),'Changed outside intended resident glyph bitplanes'
    assert not new[:48,:256].any(),'Reserved sprite band changed'
    return {'cells_verified':len(cells),'original_resource_bytes':len(before),'expanded_resource_bytes':len(after),
            'original_portrait_pixels_preserved':True,'clut_and_padding_preserved':True,
            'image_header_change':{'original_width_words':256,'expanded_width_words':320,'height':240},
            'outside_intended_cells_preserved':True,'reserved_sprite_rows_0_47_clear':True,'native_upper_tpage':10,
            'extension_code_base':code_base,'extension_capacity':504,'runtime_verified':False}


def wrap_upper_tim(tim,cells,upper_left=None,code_base=1790):
    """Append an extension atlas which a y256/h512 GPU upload wraps to y0.

    The original image must be a native full font (512px) or right-page font
    (256px). Its source coordinates are retained; the game relocates it to
    y256 at runtime. Native pixels and CLUT bytes are preserved. A full-font upload
    also reaches upper page12, so its 256x256 pixels must be supplied explicitly
    as ``upper_left``; this API never silently clears that graphics page.
    Extension code_base..code_base+335 uses upper page13 F0; the next336
    codes use its F1. The default1790 preserves the original encyclopedia's
    native third-page glyphs1454..1789.
    This only constructs a resource. Loader height handling and region liveness
    require actual runtime verification before delivery.
    """
    pix,pos,length,(x,y,w,h)=tim_pixels(tim)
    if h!=256 or pix.shape[1] not in (256,512):
        raise ValueError('Wrap upload requires a native256px-high font')
    atlas=np.zeros((256,256),np.uint8)
    for code,cell in cells.items():
        code=int(code)
        if not code_base<=code<code_base+672:raise ValueError('Expected an extension glyph: '+str(code))
        index=(code-code_base)%336;shift=0 if code<code_base+336 else 2
        cx=(index%21)*12;cy=(index//21)*16
        cell=np.asarray(cell,np.uint8)
        if cell.shape!=(16,12) or cell.max()>3:raise ValueError('Bad extension cell')
        atlas[cy:cy+16,cx:cx+12]|=cell<<shift
    if pix.shape[1]==512:
        if upper_left is None:raise ValueError('Full-font wrap requires preserved upper-page12 pixels')
        if isinstance(upper_left,(bytes,bytearray)):
            if len(upper_left)!=32768:raise ValueError('Upper-page12 raw payload must be32768bytes')
            raw=np.frombuffer(upper_left,np.uint8).reshape(256,128)
            preserved=np.empty((256,256),np.uint8);preserved[:,0::2]=raw&15;preserved[:,1::2]=raw>>4
        else:preserved=np.asarray(upper_left,np.uint8)
        if preserved.shape!=(256,256) or preserved.max()>15:raise ValueError('Bad upper-page12 pixels')
        extension=np.concatenate([preserved,atlas],axis=1)
    else:extension=atlas
    combined=np.concatenate([pix,extension],axis=0)
    packed=(combined[:,0::2]|(combined[:,1::2]<<4)).astype(np.uint8).tobytes()
    header=bytearray(tim[:pos+12]);struct.pack_into('<IHHHH',header,pos,12+len(packed),x,y,w,512)
    return bytes(header)+packed+tim[pos+length:]


def validate_wrap_upper_tim(before,after,cells,upper_left=None,code_base=1790):
    old,pos,_,rect=tim_pixels(before);new,npos,_,newrect=tim_pixels(after)
    assert after==wrap_upper_tim(before,cells,upper_left,code_base),'Unexpected wrapped resource change'
    assert before[:pos]==after[:npos],'CLUT or TIM flags changed'
    assert np.array_equal(old,new[:256]),'Native font pixels changed'
    assert newrect==(rect[0],rect[1],rect[2],512)
    return {'extension_cells_verified':len(cells),'native_font_pixels_preserved':True,
            'clut_preserved':True,'resource_height':512,'upper_atlas_tpage':13,'extension_code_base':code_base,
            'upper_page12_preserved':old.shape[1]==512,'runtime_verified':False}


def encode_plain(text,p):
    return [p['encode'][ch] for ch in text]


def decode_plain(codes,p):
    inverse={}
    for ch,code in p['encode'].items():
        if ch not in p.get('aliases',{}):
            inverse.setdefault(int(code),ch)
    return ''.join(inverse[int(code)] for code in codes)


def normalize_aliases(text,p):
    return ''.join(p.get('aliases',{}).get(ch,ch) for ch in text)


def preview(texts,p,cells,dst):
    import fontsets
    width=320
    lines=[]
    for text in texts:
        text=CONTROL.sub('',text).replace('\n',' ')
        x,line=0,[]
        for ch in text:
            code=p['encode'][ch]
            adv=8 if code<320 else 12
            if x+adv>width-16 and line:
                lines.append(line);x,line=0,[]
            line.append(code);x+=adv
        lines.append(line)
    canvas=np.zeros((max(1,len(lines))*20+8,width),np.uint8)
    for li,line in enumerate(lines):
        x=8
        for code in line:
            glyph=cells.get(code)
            if glyph is None:
                glyph=fontsets.glyph_level(code,int(p['variant']))
            adv=8 if code<320 else 12
            dest=canvas[4+li*20:20+li*20,x:x+glyph.shape[1]]
            dest[:]=np.maximum(dest,glyph)
            x+=adv
    palette=np.array([(24,32,96),(40,40,40),(165,165,165),(230,230,230)],np.uint8)
    image=Image.fromarray(palette[canvas])
    image.resize((width*3,canvas.shape[0]*3),Image.Resampling.NEAREST).save(dst)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--ui',type=Path,default=ROOT/'work/translation/zh_CN/exe_strings.zh.json')
    ap.add_argument('--font',type=Path,default=ROOT/'incoming/Cubic11/Cubic_11.ttf')
    ap.add_argument('--mode',choices=['unused','extension'],default='unused')
    ap.add_argument('--variant',default='11')
    ap.add_argument('--capacity',type=int,choices=[336,672],default=336)
    ap.add_argument('--out',type=Path,default=ROOT/'work/translation/zh_CN')
    args=ap.parse_args()
    d=json.loads(args.ui.read_text())
    texts=[v[1] if isinstance(v,list) else v for k,v in d.items() if not k.startswith('_') and v is not None]
    p=plan(texts,args.variant,args.mode,capacity=args.capacity)
    cells=render_cells(p,args.font)
    for text in texts:
        assert decode_plain(encode_plain(text,p),p)==normalize_aliases(text,p)
    args.out.mkdir(parents=True,exist_ok=True)
    path=args.out/('font_plan_'+args.mode+'.json')
    path.write_text(json.dumps(p,ensure_ascii=False,indent=2)+'\n')
    np.savez(args.out/('font_cells_'+args.mode+'.npz'),**{str(k):v for k,v in cells.items()})
    preview(texts,p,cells,args.out/('ui_font_preview_'+args.mode+'.png'))
    print('Dry run: %d labels, %d required chars, %d added glyphs / %d slots; no game asset written.'%(len(texts),p['required_characters'],p['new_glyph_count'],p['slots_available']))
    print(path)


if __name__=='__main__':
    main()
