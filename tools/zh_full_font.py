"""Static whole-game Chinese atlas in the game's existing two font pages.

Eleven-pixel cells give23 columns per256px page. Four independent1bpp
planes provide enough slots for the full Chinese corpus. Two16-color CLUT
columns retain the game's existing eight color styles and two-row stride.
Native codes0..319 and explicitly preserved wide runtime/icon codes keep
their encoded values. This module never changes resource dimensions or VRAM
texture destinations; its CLUT width grows from16 to32 words.
"""
from __future__ import annotations
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import unicodedata

import numpy as np
from PIL import Image,ImageDraw,ImageFont
import zh_font as Z

ROOT=Path(__file__).resolve().parents[1]
CODE_BASE=0x1000
CODE_END=0x2000
CELL_WIDTH=11
CELL_HEIGHT=16
COLS=23
ENCYC_DARK_FOREGROUND=0x94A5
DEFAULT_WIDE=tuple(range(1118,1123))
ICON_WIDE=tuple(range(1425,1454))
GLYPH_FALLBACKS=dict(zip('恸羁哒娅岚泷濑觑讧谙谵镯镳飓鹫鼹','慟羈噠婭嵐瀧瀨覷訌諳譫鐲鑣颶鷲鼴'))
BITMAP_COMPOSITES={
    '嗬':{'left_glyph':'嗒','left_source_rect':[0,0,3,16],'left_dest_rect':[0,0,3,16],
          'right_glyph':'荷','right_source_rect':[0,0,11,16],'right_dest_rect':[4,0,7,16],
          'right_compact_rows':['.......','.......','..#.#..','#######','..#.#..','.#.....','#.#####','#.....#','#.###.#','#.#.#.#','#.#.#.#','#.###.#','#....##','.......','.......','.......'],
          'method':'Cubic11 mouth plus stroke-preserving7px compact grass/person/ke component; shared baseline'},
    '犸':{'left_glyph':'狮','left_source_rect':[0,0,3,16],'left_dest_rect':[0,0,3,16],
          'right_glyph':'吗','right_source_rect':[3,0,8,16],'right_dest_rect':[3,0,8,16],
          'method':'exact source bitmap columns; shared Cubic11 baseline'},
}


def font_codepoints(path):
    """Read Unicode cmap4/12 directly, so Pillow tofu cannot pass as a glyph."""
    data=Path(path).read_bytes();num=struct.unpack_from('>H',data,4)[0];tables={}
    for i in range(num):
        tag,_,offset,length=struct.unpack_from('>4sIII',data,12+i*16);tables[tag]=(offset,length)
    base,_=tables[b'cmap'];count=struct.unpack_from('>H',data,base+2)[0];result=set();seen=set()
    for i in range(count):
        platform,encoding,offset=struct.unpack_from('>HHI',data,base+4+i*8)
        if platform not in (0,3) or offset in seen:continue
        seen.add(offset);p=base+offset;fmt=struct.unpack_from('>H',data,p)[0]
        if fmt==12:
            n=struct.unpack_from('>I',data,p+12)[0]
            for j in range(n):
                start,end,glyph=struct.unpack_from('>III',data,p+16+j*12)
                result.update(range(start+(glyph==0),end+1))
        elif fmt==4:
            n=struct.unpack_from('>H',data,p+6)[0]//2;ends=p+14;starts=ends+n*2+2;deltas=starts+n*2;ranges=deltas+n*2
            for j in range(n):
                end=struct.unpack_from('>H',data,ends+j*2)[0];start=struct.unpack_from('>H',data,starts+j*2)[0]
                delta=struct.unpack_from('>h',data,deltas+j*2)[0];ro=struct.unpack_from('>H',data,ranges+j*2)[0]
                for cp in range(start,min(end,65534)+1):
                    if ro:
                        glyph=struct.unpack_from('>H',data,ranges+j*2+ro+(cp-start)*2)[0]
                        if glyph:glyph=(glyph+delta)&65535
                    else:glyph=(cp+delta)&65535
                    if glyph:result.add(cp)
    if not result:raise ValueError('No supported Unicode cmap found')
    return result


def location(code):
    if not CODE_BASE<=int(code)<CODE_END:raise ValueError('Not a full-font code')
    index=int(code)-CODE_BASE
    col=index&31;row=(index>>5)&15;plane=(index>>9)&3;page=(index>>11)&1
    if col>=COLS:raise ValueError('Unallocated column')
    return page*256+col*CELL_WIDTH,row*CELL_HEIGHT,plane


def legacy_location(code):
    code=int(code)
    if code<320:return (code%32)*8,(code//32)*16,0,8
    x,y,shift=Z.cell_location(code,layout='dual_plane')
    return x,y,shift//2,12


def _overlap(a,b):
    ax,ay,aw,ah=a;bx,by,bw,bh=b
    return ax<bx+bw and bx<ax+aw and ay<by+bh and by<ay+ah


def make_plan(texts,legacy_wide=None,reserve_wide=None):
    """Return a JSON-serializable global encoder and exact atlas placement.

    legacy_wide optionally supplies code->character for default names. Other
    reserved wide glyphs retain their original default-bank primary bitmap.
    """
    legacy_wide={int(k):v for k,v in (legacy_wide or {}).items()}
    reference=Z.original_map('11')
    for code in DEFAULT_WIDE:
        if code in reference:legacy_wide.setdefault(code,reference[code])
    reserve=set(ICON_WIDE)|set(legacy_wide)|set(reserve_wide or [])
    if any(not 320<=c<1454 for c in reserve):raise ValueError('Reserved wide code outside main pages')
    narrow={}
    for code,ch in sorted(Z.TABLE.items()):
        if len(ch)==1 and not '\u3400'<=ch<='\u9fff':narrow.setdefault(ch,code)
    aliases={}
    punctuation=dict(Z.ALIASES);punctuation.update({'?':'？','!':'！'})
    for ch,native in punctuation.items():
        if ch not in narrow and native in narrow:
            narrow[ch]=narrow[native];aliases[ch]=native
    required=Z.required_chars(texts)
    ignored=sorted(ch for ch in required if unicodedata.category(ch)=='Cf')
    required-=set(ignored)
    preserved_encoding={ch:code for code,ch in legacy_wide.items() if len(ch)==1}
    wide=required-set(narrow)-set(preserved_encoding)
    legacy_rects={}
    for code in sorted(reserve):
        x,y,plane,width=legacy_location(code)
        legacy_rects.setdefault(plane,[]).append((x,y,width,16))
    candidates=[];reserved_slots=[]
    # Codes encode the physical placement directly, requiring no RAM table.
    for code in range(CODE_BASE,CODE_END):
        try:x,y,plane=location(code)
        except ValueError:continue
        if x<256 and plane==0 and y<160:continue
        if any(_overlap((x,y,11,16),rect) for rect in legacy_rects.get(plane,[])):
            reserved_slots.append(code);continue
        candidates.append(code)
    if len(wide)>len(candidates):
        raise ValueError(f'Full corpus needs{len(wide)} wide glyphs; capacity{len(candidates)}')
    counts=Counter(''.join(Z.CONTROL.sub('',s) for s in texts))
    ordered=sorted(wide,key=lambda ch:(-counts[ch],ord(ch)))
    new={ch:candidates[i] for i,ch in enumerate(ordered)}
    encoding=dict(narrow);encoding.update(preserved_encoding);encoding.update(new)
    return {'mode':'static_global_4plane_1bpp','variant':'11','cell_width':11,'cell_height':16,
            'custom_code_base':CODE_BASE,'custom_code_end':CODE_END,
            'new_glyphs':new,'encode':encoding,'aliases':aliases,
            'required_characters':len(required),'new_glyph_count':len(new),
            'slots_available':len(candidates),'spare_slots':len(candidates)-len(new),
            'legacy_wide':{str(k):v for k,v in legacy_wide.items()},
            'ignored_format_characters':ignored,
            'reserved_wide_codes':sorted(reserve),'reserved_custom_slots':reserved_slots,
            'clut_width_words':32,'clut_height':16,'color_style_stride_rows':2,
            'texture_pages':[28,29],'resident_atlas_used':False,
            'original_non_text_pixels_changed':False,'runtime_verified':False}


def encode_plain(text,plan):
    ignored=set(plan.get('ignored_format_characters',[]))
    return [plan['encode'][ch] for ch in text if ch not in ignored]


def normalize_aliases(text,plan):
    ignored=set(plan.get('ignored_format_characters',[]))
    return ''.join(plan.get('aliases',{}).get(ch,ch) for ch in text if ch not in ignored)


def decode_plain(codes,plan):
    inverse={}
    for ch,code in plan['encode'].items():
        if ch not in plan.get('aliases',{}):inverse.setdefault(int(code),ch)
    return ''.join(inverse[int(code)] for code in codes)


def _mono_glyph(ch,width,font):
    canvas=Image.new('L',(40,24));ImageDraw.Draw(canvas).text((8,1),ch,font=font,fill=255)
    a=np.asarray(canvas);ys,xs=np.nonzero(a>=64)
    if not len(xs):
        if ch.isspace():return np.zeros((16,width),np.uint8)
        raise ValueError('Empty glyph '+repr(ch))
    if ys.max()>=16:raise ValueError('Glyph exceeds16px line box '+repr(ch))
    ink=a[:16,xs.min():xs.max()+1]
    if ink.shape[1]>width:
        if width==8:ink=np.asarray(Image.fromarray(ink).resize((width,16),Image.Resampling.NEAREST))
        elif ch in ('—','仆') and ink.shape[1] in (12,13) and width==11:
            # Trim only an overhanging horizontal-stroke endpoint.
            ink=ink[:,:11]
        else:raise ValueError(f'{ch!r} ink{ink.shape[1]}px exceeds{width}px')
    result=np.zeros((16,width),np.uint8);x=(width-ink.shape[1])//2
    result[:,x:x+ink.shape[1]]=(ink>=160).astype(np.uint8)
    return result


def _composite(ch,font):
    spec=BITMAP_COMPOSITES[ch];result=np.zeros((16,11),np.uint8)
    for side in ('left','right'):
        src=_mono_glyph(spec[side+'_glyph'],11,font)
        x,y,w,h=spec[side+'_source_rect'];part=src[y:y+h,x:x+w]
        dx,dy,dw,dh=spec[side+'_dest_rect']
        if side+'_compact_rows' in spec:
            part=np.array([[int(c=='#') for c in row] for row in spec[side+'_compact_rows']],np.uint8)
        if part.shape!=(dh,dw):part=np.asarray(Image.fromarray(part).resize((dw,dh),Image.Resampling.NEAREST))
        result[dy:dy+dh,dx:dx+dw]|=part
    assert result.any()
    return result


def prepare_cells(plan,main_tim=None,font_path=None):
    """Render custom glyphs and preserve primary shapes of all native icons."""
    if main_tim is None:main_tim=(ROOT/'work/source/unpacked/MAPMAIN/0007.bin').read_bytes()
    pix,*_=Z.tim_pixels(main_tim)
    font_path=font_path or ROOT/'incoming/Cubic11/Cubic_11.ttf'
    available=font_codepoints(font_path)
    rendered=set(plan['new_glyphs'])|set(plan['legacy_wide'].values())
    missing=sorted(ch for ch in rendered if ord(ch) not in available and not ch.isspace())
    unresolved=[]
    for ch in missing:
        if ch in BITMAP_COMPOSITES:
            if any(ord(BITMAP_COMPOSITES[ch][side+'_glyph']) not in available for side in ('left','right')):unresolved.append(ch)
        elif ch not in GLYPH_FALLBACKS or ord(GLYPH_FALLBACKS[ch]) not in available:unresolved.append(ch)
    if unresolved:raise ValueError('Font cmap has no glyph or approved fallback: '+repr(unresolved))
    plan['glyph_fallbacks']={ch:GLYPH_FALLBACKS[ch] for ch in missing if ch in GLYPH_FALLBACKS}
    plan['bitmap_composites']={ch:BITMAP_COMPOSITES[ch] for ch in missing if ch in BITMAP_COMPOSITES}
    plan['cmap_verified_characters']=len(rendered)-len(plan['bitmap_composites']);plan['unresolved_missing_glyphs']=[]
    plan['pillow_font_size']=12;plan['native_pixel_ink_size']=11
    plan['glyph_endpoint_trims']={'—':'13px horizontal stroke trimmed to11px','仆':'12px horizontal endpoint trimmed to11px'}
    # Cubic11 has a12px em: this size yields exact binary pixels. At11px it
    # is resampled into grayscale, which would lose strokes when made1bpp.
    font=ImageFont.truetype(str(font_path),12)
    draw=lambda ch:plan['glyph_fallbacks'].get(ch,ch)
    cells={int(code):_composite(ch,font) if ch in plan['bitmap_composites'] else _mono_glyph(draw(ch),11,font)
           for ch,code in plan['new_glyphs'].items()}
    for code in list(range(320))+plan['reserved_wide_codes']:
        x,y,plane,width=legacy_location(code)
        # Original F0/F1 primary bits are1/3; shadow bits0/2 are discarded.
        cell=((pix[y:y+16,x:x+width]>>(1+plane*2))&1).copy()
        ch=Z.TABLE.get(code)
        if code<256 and isinstance(ch,str) and len(ch)==1 and (ch==' ' or ch.isascii() and ch.isalnum() or '\u3040'<=ch<='\u30ff' or unicodedata.category(ch).startswith('P') or unicodedata.category(ch)=='Sm'):
            cell=_mono_glyph(unicodedata.normalize('NFKC',ch),width,font)
        elif str(code) in plan['legacy_wide']:
            cell=_mono_glyph(draw(plan['legacy_wide'][str(code)]),width,font)
        cells[code]=cell
    return cells


def _palette(tim,encyclopedia_dark_source=False):
    if tim[:4]!=b'\x10\0\0\0' or struct.unpack_from('<I',tim,4)[0]!=8:
        raise ValueError('Expected4bpp TIM with CLUT')
    size,x,y,w,h=struct.unpack_from('<IHHHH',tim,8)
    if (w,h)!=(16,16):raise ValueError('Font source CLUT must be16x16')
    old=np.frombuffer(tim[20:8+size],dtype='<u2').reshape(h,w)
    if encyclopedia_dark_source:
        assert not old[10:12].any(),'Encyclopedia private style5 was not unused'
    new=np.zeros((16,32),dtype='<u2')
    for style in range(8):
        foreground=ENCYC_DARK_FOREGROUND if encyclopedia_dark_source and style==5 else int(old[style*2,3])
        for plane in range(4):
            cy=style*2+(plane&1);cx=16*(plane>>1)
            for index in range(16):new[cy,cx+index]=foreground if index&(1<<plane) else 0
    block=struct.pack('<IHHHH',12+new.nbytes,x,y,32,16)+new.tobytes()
    return size,block,new


def patch_font(tim,plan,cells,sheet='main',encyclopedia_dark_source=False):
    """Patch a full MAPMAIN/BATTLE font or a256px EVENT right-page font."""
    if sheet not in ('main','variant'):raise ValueError(sheet)
    pix,pos,length,rect=Z.tim_pixels(tim);pix=pix.copy()
    if pix.shape[0]!=256 or (sheet=='variant' and pix.shape[1]!=256) or (sheet=='main' and pix.shape[1] not in (512,768)):
        raise ValueError('Unexpected native font image geometry')
    for code,cell in cells.items():
        if code>=CODE_BASE:x,y,plane=location(code);width=11
        else:x,y,plane,width=legacy_location(code)
        if sheet=='variant':
            if not 256<=x<512:continue
            x-=256
        elif x>=512:continue
        region=pix[y:y+16,x:x+width]
        if region.shape!=cell.shape:raise ValueError('Glyph outside font resource')
        bit=1<<plane;region[:]=(region&(15^bit))|(np.asarray(cell,np.uint8)*bit)
    if encyclopedia_dark_source:assert sheet=='main' and pix.shape[1]==768
    old_clut_size,new_clut,_=_palette(tim,encyclopedia_dark_source)
    raw=(pix[:,0::2]|(pix[:,1::2]<<4)).astype(np.uint8).tobytes()
    assert len(raw)==length-12
    tail=tim[pos+length:]
    # Raw DAT font entries have1504 zero padding bytes. Their native bulk
    # loaders use fixed RAM pointers to following entries, so the enlarged
    # palette must consume padding instead of growing the aligned entry.
    # MAPMAIN25's decompressed TIM has no tail and can grow inside its CM.
    assert len(tail) in (0,1504) and not any(tail),'Unexpected source font padding'
    growth=len(new_clut)-old_clut_size
    if tail:
        assert growth==512 and len(tail)>=growth
        tail=tail[:-growth]
    result=tim[:8]+new_clut+tim[pos:pos+12]+raw+tail
    assert len(result)==len(tim)+(0 if tail else growth)
    return result


def validate_font(before,after,plan,cells,sheet='main',encyclopedia_dark_source=False):
    assert after==patch_font(before,plan,cells,sheet,encyclopedia_dark_source),'Unexpected font bytes'
    a,pos,ln,rect=Z.tim_pixels(before);b,npos,nln,nrect=Z.tim_pixels(after)
    assert rect==nrect and ln==nln and npos==pos+512
    _,_,pal=_palette(before,encyclopedia_dark_source)
    stored=np.frombuffer(after[20:npos],dtype='<u2').reshape(16,32)
    assert np.array_equal(pal,stored)
    checked=0
    for code,cell in cells.items():
        if code>=CODE_BASE:x,y,plane=location(code);width=11
        else:x,y,plane,width=legacy_location(code)
        if sheet=='variant':
            if not 256<=x<512:continue
            x-=256
        elif x>=512:continue
        actual=(b[y:y+16,x:x+width]>>plane)&1
        assert np.array_equal(actual,cell),(code,'overlapping glyph allocation')
        for style in range(8):
            colors=stored[style*2+(plane&1),16*(plane>>1):16*(plane>>1)+16]
            decoded=colors[b[y:y+16,x:x+width]]
            expected=np.where(cell,pal[style*2+(plane&1),16*(plane>>1)+(1<<plane)],0)
            assert np.array_equal(decoded,expected),(code,style,'color plane interference')
        checked+=1
    return {'cells_verified':checked,'color_styles_verified':8,'image_geometry_preserved':True,
            'clut_width_words':32,'clut_height':16,'added_resource_bytes':len(after)-len(before),
            'trailing_zero_padding_consumed':512-(len(after)-len(before)),
            'native_raw_entry_allocation_preserved':len(before)==len(after),
            'encyclopedia_private_dark_CLUT_source':encyclopedia_dark_source,
            'native_icon_primary_shapes_preserved':True,'native_alphabet_redrawn_uniform_11px':True,
            'resident_atlas_used':False,'runtime_verified':False}


def preview(plan,cells,path,max_chars=240):
    selected=sorted(plan['new_glyphs'],key=ord)[:max_chars];cols=24;rows=(len(selected)+cols-1)//cols
    canvas=np.zeros((rows*20+8,cols*14+8),np.uint8)
    for i,ch in enumerate(selected):
        y=4+(i//cols)*20;x=4+(i%cols)*14
        canvas[y:y+16,x:x+11]=cells[plan['new_glyphs'][ch]]*255
    Image.fromarray(canvas).resize((canvas.shape[1]*3,canvas.shape[0]*3),Image.Resampling.NEAREST).save(path)


def preview_fallbacks(plan,cells,path):
    chars=sorted(set(GLYPH_FALLBACKS)|set(BITMAP_COMPOSITES))
    chars+=list('你我世界战斗骑士中文勇气')
    font=ImageFont.truetype(str(ROOT/'incoming/Cubic11/Cubic_11.ttf'),12)
    cols=6;rows=(len(chars)+cols-1)//cols;canvas=Image.new('RGB',(cols*92,rows*94),(25,28,40));d=ImageDraw.Draw(canvas)
    for i,ch in enumerate(chars):
        x=(i%cols)*92;y=(i//cols)*94
        if ch in plan['encode']:cell=cells[plan['encode'][ch]]
        else:cell=_composite(ch,font) if ch in BITMAP_COMPOSITES else _mono_glyph(GLYPH_FALLBACKS.get(ch,ch),11,font)
        glyph=Image.fromarray(np.uint8(cell*255)).resize((cell.shape[1]*4,64),Image.Resampling.NEAREST)
        colored=Image.new('RGB',glyph.size,(235,235,235));canvas.paste(colored,(x+12,y+18),glyph)
        label=f'U+{ord(ch):04X}'
        if ch in GLYPH_FALLBACKS:label+=' trad'
        if ch in BITMAP_COMPOSITES:label+=' comp'
        d.text((x+3,y+2),label,fill=(180,200,230))
    canvas.save(path)


def _replace_cm(buf,replacements):
    import cm
    out=bytearray();pos=0;index=0
    while buf[pos:pos+2]==b'CM':
        old,nxt=cm.decompress(buf,pos)
        if index in replacements:
            packed=cm.compress(replacements[index]);assert cm.decompress(packed)[0]==replacements[index];out+=packed
        else:out+=buf[pos:nxt]
        pos=nxt;index+=1
    assert all(i<index for i in replacements)
    return bytes(out)+buf[pos:]


def patch_files(files,plan):
    """Mutate only font entries in supplied rebuilt DAT containers; return QA."""
    import cm,repack
    archives={name:repack.dat_entries(files[name]) for name in ('MAPMAIN.DAT','EVENT.DAT','BATTLE.DAT')}
    main=archives['MAPMAIN.DAT'][7];cells=prepare_cells(plan,main);reports=[]
    def change(name,index,sheet,dark=False):
        entries=archives[name];old=entries[index];new=patch_font(old,plan,cells,sheet,dark)
        report=validate_font(old,new,plan,cells,sheet,dark);entries[index]=new
        reports.append({'archive':name,'entry':index,'sheet':sheet,**report})
    change('MAPMAIN.DAT',7,'main');change('EVENT.DAT',10,'main')
    for index in range(11,24):change('EVENT.DAT',index,'variant')
    # BATTLE537 is a separate encyclopedia-tab atlas uploaded tox512,y256,
    # with its own CLUT atx288,y240. It is not glyph page29 (x832,y256).
    # Keep both its native sprites and byte length; the encyclopedia loader
    # expects BATTLE538 atRAM0x8018e800 and539 atRAM0x801a7000.
    tabs=archives['BATTLE.DAT'][537]
    assert len(tabs)==0x8800,'Unexpected source encyclopedia-tab allocation'
    assert struct.unpack_from('<H',tabs,20+3*2)[0]==ENCYC_DARK_FOREGROUND,'Native encyclopedia dark foreground drift'
    change('BATTLE.DAT',538,'main',dark=True)
    assert archives['BATTLE.DAT'][537]==tabs
    assert len(archives['BATTLE.DAT'][538])==0x18800,'Encyclopedia font allocation drift'
    parts=cm.blocks(archives['MAPMAIN.DAT'][25]);old=parts[3];new=patch_font(old,plan,cells,'main')
    reports.append({'archive':'MAPMAIN.DAT','entry':25,'cm_block':3,'sheet':'main',**validate_font(old,new,plan,cells)})
    archives['MAPMAIN.DAT'][25]=_replace_cm(archives['MAPMAIN.DAT'][25],{3:new})
    assert cm.blocks(archives['MAPMAIN.DAT'][25])[3]==new
    for name,entries in archives.items():files[name]=repack.dat_pack(entries)
    return {'mode':plan['mode'],'font_resources_patched':len(reports),'resources':reports,
            'glyphs':plan['new_glyph_count'],'capacity':plan['slots_available'],'spare_slots':plan['spare_slots'],
            'traditional_glyph_fallbacks':plan.get('glyph_fallbacks',{}),'bitmap_composites':plan.get('bitmap_composites',{}),
            'unresolved_missing_glyphs':plan['unresolved_missing_glyphs'],'native_texture_geometry_preserved':True,
            'native_encyclopedia_tab_atlas_preserved':True,
            'encyclopedia_native_font_load_pointers_preserved':True,
            'resident_atlas_used':False,'runtime_verified':False}


def patch_exe(exe,plan=None):
    import zh_full_glyph_lookup,zh_full_text_helpers
    result=zh_full_text_helpers.patch(zh_full_glyph_lookup.patch(exe,plan))
    return patch_encyclopedia_clut_copy(result)


def patch_encyclopedia_clut_copy(exe):
    """Keep all four planes in sync when the encyclopedia copies text style0.

    Its one private RECT duplicates font CLUT rows240/241 to242/243. The
    original16-word width copied planes0/1 only; the expanded32-word palette
    also stores planes2/3 atcx64. A later tab-gradient-to-font copy instead
    takes the private four-plane dark palette atstyle5, retaining the native
    book's dark text. The font-to-tab copy and all tab pixels stay intact.
    """
    result=bytearray(exe)
    offset=lambda addr:addr-0x80010000+0x800
    table=bytes.fromhex('3000f000100004003000f000100002002001f00010000200c001000120000001')
    source=offset(0x80010f40)
    width_only=bytearray(table);struct.pack_into('<H',width_only,12,32)
    self_copy=bytearray(width_only);struct.pack_into('<H',self_copy,16,48);struct.pack_into('<H',self_copy,20,32)
    expected=bytearray(self_copy);struct.pack_into('<H',expected,18,250)
    assert result[source:source+32] in (table,width_only,self_copy,expected),'Encyclopedia RECT source drift'
    # This table is copied only by the native encyclopedia loader. Its
    # second RECT is passed directly to MoveImage with destination48,242.
    assert result[offset(0x8005c728):offset(0x8005c728)+24]==bytes.fromhex('4000a427e00105240180023c400f59240300338b0000339b')
    assert result[offset(0x8005c9b0):offset(0x8005c9b0)+24]==bytes.fromhex('3000a427300005240c10020cf2000624310f020c21200000')
    assert result[offset(0x8005c9c8):offset(0x8005c9c8)+24]==bytes.fromhex('3800a427300005240c10020cf00006240600042423030524')
    result[source:source+32]=expected
    assert len(result)==len(exe)
    return bytes(result)

