"""Chinese raster UI using native Cubic11 pixels and integer scaling only.

The caller owns the DAT dictionary passed to patch_files(). Source assets are
never written. Every edited TIM retains its CLUT, dimensions and byte length;
only measured manifest rectangles may change. The shared BATTLE0537 font atlas
is deliberately left to the font builder. The 24x8 Critical sprite uses the
established synonym 会心 in native 8px Misaki bitmap lettering; body text uses
Cubic11. No glyph is fractionally resampled and no runtime quad is enlarged.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import cm
import gfx
import repack
import zh_graphics
import zh_sparse_tim

ROOT = Path(__file__).resolve().parents[1]
FONT = ROOT / "incoming/Cubic11/Cubic_11.ttf"
COMPACT_FONT = ROOT / "incoming/Misaki/misaki_gothic.ttf"
RESTORED_ART = ROOT / "work/translation/zh_CN/graphics_full_assets/EVENT_0230_background_zh.png"
RESTORATION_MASK = ROOT / "work/translation/zh_CN/graphics_full_assets/EVENT_0230_restoration_mask.png"
SPARSE_RESTORATION = ROOT / "work/translation/zh_CN/graphics_full_assets/EVENT_0230_restoration.delta.json"
CANONICAL = ROOT / "work/translation/zh_CN/full_ui/graphics.zh.json"
MANIFEST = CANONICAL if CANONICAL.exists() else ROOT / "work/translation/zh_CN/graphics.zh.json"
PREVIEW = ROOT / "work/translation/zh_CN/graphics_full"
# The font's design is11px ink on a12px EM grid. Point12 preserves binary
# pixel strokes; point11 introduces fractional antialiasing and loses strokes.
NATIVE_SIZE = 12
INDEX_TEXT = "索引"
APPEARANCE_TEXT = "登场作品"
GLYPH_VARIANTS = {"恸":"慟", "羁":"羈"}


@lru_cache(maxsize=1)
def font():
    return ImageFont.truetype(str(FONT), NATIVE_SIZE)


def clean(text):
    # An inherited options draft accidentally stores a literal JSON escape.
    return text.replace("\\u3000", "\u3000")


@lru_cache(maxsize=4096)
def lettering(text, scale=1, outline=0, shadow=False):
    if scale not in (1, 2, 3):
        raise ValueError("Cubic11 requires integer scaling")
    text = "".join(GLYPH_VARIANTS.get(ch,ch) for ch in clean(text))
    bounds = font().getbbox(text)
    image = Image.new("L", (bounds[2] - bounds[0] + 8, bounds[3] - bounds[1] + 8))
    ImageDraw.Draw(image).text((4-bounds[0], 4-bounds[1]), text, font=font(), fill=255)
    core = np.asarray(image) > 110
    edge = np.zeros_like(core)
    for dy in range(-outline, outline+1):
        for dx in range(-outline, outline+1):
            edge |= np.roll(np.roll(core, dy, 0), dx, 1)
    if shadow:
        edge |= np.roll(np.roll(core, 1, 0), 1, 1)
    mask = np.where(core, 2, np.where(edge, 1, 0)).astype(np.uint8)
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("Empty raster text: " + repr(text))
    mask = mask[ys.min():ys.max()+1, xs.min():xs.max()+1]
    if scale > 1:
        mask = np.repeat(np.repeat(mask, scale, 0), scale, 1)
    return mask


def draw_label(tim, rect, text, scale=1, color=(255,255,255),
               outline=0, edge=(0,0,0), gradient=None, indices=None):
    text = clean(text)
    x0,y0,x1,y1 = rect
    if not (0 <= x0 < x1 <= tim.w and 0 <= y0 < y1 <= tim.h):
        raise ValueError("Invalid measured rectangle: " + repr(rect))
    mask = lettering(text, scale, outline, shadow=indices is not None)
    h,w = mask.shape
    if w > x1-x0 or h > y1-y0:
        raise ValueError(f"Cubic11 {text!r} ({w}x{h}) exceeds {rect}")
    x,y = x0+(x1-x0-w)//2, y0+(y1-y0-h)//2
    destination = tim.idx[y:y+h,x:x+w]
    if indices is not None:
        face_index, edge_index = indices
        destination[mask==1] = edge_index
        destination[mask==2] = face_index
    else:
        destination[mask==1] = tim.nearest(edge)
        if gradient:
            for row in range(h):
                rgb = tuple(round(a+(b-a)*row/max(h-1,1)) for a,b in zip(*gradient))
                destination[row,mask[row]==2] = tim.nearest(rgb)
        else:
            destination[mask==2] = tim.nearest(color)
    return {"text":text,"font":"Cubic11","native_font_size":NATIVE_SIZE,
            "integer_scale":scale,"font_size":NATIVE_SIZE*scale,
            "ink_size":[w,h],"bounds":[x,y,x+w,y+h],"measured_rect":list(rect),
            "resampled":False,"visual_glyph_variants":{ch:GLYPH_VARIANTS[ch] for ch in text if ch in GLYPH_VARIANTS}}


def wrap_title(text, width=304, scale=2):
    """Wrap at character boundaries while retaining a constant native scale."""
    text = clean(text)
    if lettering(text,scale).shape[1] <= width:
        return [text]
    candidates = []
    for split in range(1,len(text)):
        first,second = text[:split].rstrip(),text[split:].lstrip()
        if not first or not second:
            continue
        if second[0] in "，。！？；：、）》】」』…":
            continue
        widths = [lettering(line,scale).shape[1] for line in (first,second)]
        if max(widths) <= width:
            candidates.append((abs(widths[0]-widths[1]),max(widths),[first,second]))
    if not candidates:
        raise ValueError("Episode title does not fit two constant-scale lines: "+repr(text))
    return min(candidates)[2]


def title_card(tim, target):
    background = int(tim.idx[5,5])
    tim.fill(0,18,320,84,background)
    lines = wrap_title(target["en"])
    boxes = [(8,22,312,80)] if len(lines)==1 else [(8,20,312,50),(8,52,312,82)]
    labels = [draw_label(tim,box,line,scale=2) for box,line in zip(boxes,lines)]
    # Keep compatibility with stage_cards.patch_script's 12px numeral quads.
    tim.fill(0,100,320,128,background)
    for digit in range(10):
        labels.append(draw_label(tim,(digit*24+6,104,digit*24+18,128),str(digit),scale=2))
    # The English routine's 52px prefix becomes Chinese; its suffix stays blank.
    labels.append(draw_label(tim,(256,104,308,128),"关卡",scale=2))
    return labels


def targets(manifest=None):
    path = Path(manifest) if manifest else MANIFEST
    result = deepcopy(json.loads(path.read_text(encoding="utf-8"))["targets"])
    # Additional measured labels already localized by the prototype renderer.
    menu = [{"rect":[40,1,86,14],"en":"开始"},
            {"rect":[25,17,101,30],"en":"继续"},
            {"rect":[34,33,91,46],"en":"设置"},
            {"rect":[0,208,162,226],"en":"人物图鉴"},
            {"rect":[44,232,120,251],"en":"退出"}]
    for target in result:
        if target["kind"]=="title_menu":
            target["kind"]="main_menu"
            target["labels"]=deepcopy(menu)
            target["regions"]=[row["rect"] for row in menu]
        elif target["kind"]=="artwork_logo":
            if SPARSE_RESTORATION.is_file():
                # Public builds reconstruct only these changed pixels against
                # the user's own original TIM; no full artwork is distributed.
                target["restoration_delta"]=str(SPARSE_RESTORATION.relative_to(ROOT))
                target["regions"]=[[14,91,307,142]]
            elif not (ROOT/target["background"]).exists() and RESTORED_ART.exists():
                target["background"]=str(RESTORED_ART.relative_to(ROOT))
                target["restoration_mask"]=str(RESTORATION_MASK.relative_to(ROOT))
                # Keep compatibility with the old private local cleanplate.
                target["regions"]=[[14,91,307,142]]
    return result


def resource_plan(manifest=None):
    result=[]
    for target in targets(manifest):
        result.append({"archive":target["archive"],"entry":target["entry"],
                       "block":target.get("block"),"kind":target["kind"],
                       "regions":target["regions"],
                       "font_atlas_target":target["kind"]=="encyclopedia_tab_font",
                       "policy":"preserve_font_atlas" if target["kind"]=="encyclopedia_tab_font" else "measured_rectangles_only"})
    return result


def paper_label(tim, box):
    x0,y0,x1,y1=box
    palette=np.array(tim.palette,np.int32)
    top,bottom=palette[tim.idx[y0-1,x0:x1]],palette[tim.idx[y1,x0:x1]]
    for y in range(y0,y1):
        alpha=(y-y0+1)/(y1-y0+1)
        rgb=(top*(1-alpha)+bottom*alpha).astype(np.int32)
        distance=((rgb[:,None,:]-palette[None,:,:])**2).sum(axis=2)
        tim.idx[y,x0:x1]=distance.argmin(axis=1)


def compact_callout(tim,rect):
    """Native 7px ink in an 8px cell; preserve Critical's face/shadow indices."""
    text="会心";face_font=ImageFont.truetype(str(COMPACT_FONT),8)
    box=face_font.getbbox(text)
    image=Image.new("L",(box[2]-box[0]+8,box[3]-box[1]+8))
    ImageDraw.Draw(image).text((4-box[0],4-box[1]),text,font=face_font,fill=255)
    core=np.asarray(image)>110
    shadow=np.roll(np.roll(core,1,0),1,1)
    mask=np.where(core,2,np.where(shadow,1,0)).astype(np.uint8)
    ys,xs=np.nonzero(mask);mask=mask[ys.min():ys.max()+1,xs.min():xs.max()+1]
    h,w=mask.shape;x0,y0,x1,y1=rect
    if h>y1-y0 or w>x1-x0:raise ValueError("Native compact 会心 does not fit source Critical sprite")
    tim.fill(*rect,0);x=x0+(x1-x0-w)//2;y=y0+(y1-y0-h)//2
    destination=tim.idx[y:y+h,x:x+w]
    destination[mask==2]=1;destination[mask==1]=4
    return {"text":text,"source_draft_text":"暴击","semantic_choice":"会心 is the compact Critical synonym",
            "font":"Misaki Gothic native bitmap","native_font_size":8,"integer_scale":1,
            "font_size":8,"ink_size":[w,h],"bounds":[x,y,x+w,y+h],"measured_rect":list(rect),
            "face_index":1,"shadow_index":4,"resampled":False,
            "font_source":"https://littlelimit.net/misaki.htm"}


def render(data,target,allow_callout_expansion=False):
    tim=gfx.Tim(data);kind=target["kind"];labels=[]
    if kind=="episode":
        labels=title_card(tim,target)
    elif kind=="main_menu":
        for row in target["labels"]:
            tim.fill(*row["rect"],0)
            labels.append(draw_label(tim,row["rect"],row["en"],outline=1,
                                     edge=(0,80,32),gradient=((238,255,238),(0,160,64))))
    elif kind in ("disclaimer","narration"):
        box=target["regions"][0]
        tim.fill(*box,int(tim.idx[box[1],5]))
        for row in target["labels"]:
            labels.append(draw_label(tim,row["rect"],row["en"]))
    elif kind=="options":
        for row in target["labels"]:
            tim.fill(*row["rect"],tim.nearest(row["background"]))
            scale=2 if row["rect"][3]-row["rect"][1]>=24 else 1
            labels.append(draw_label(tim,row["rect"],row["en"],scale,color=row["color"]))
    elif kind=="encyclopedia_index":
        box=target["regions"][0]
        tim.fill(*box,tim.nearest((0,8,8)))
        labels.append(draw_label(tim,box,INDEX_TEXT))
        # Same index buckets, unchanged order; captions use native Latin pixels.
        tim.idx[35:52,46:266]=tim.idx[51:52,46:266]
        for index,tab in enumerate(target["tabs"]):
            labels.append(draw_label(tim,(46+22*index,35,68+22*index,52),tab,color=(16,16,16)))
    elif kind=="encyclopedia_entry":
        box=target["regions"][0];paper_label(tim,box)
        labels.append(draw_label(tim,box,target.get("en",APPEARANCE_TEXT),color=(65,65,57)))
    elif kind=="artwork_logo":
        if "restoration_delta" in target:
            payload=json.loads((ROOT/target["restoration_delta"]).read_text(encoding="utf-8"))
            if payload["rect"] not in target["regions"]:
                raise ValueError("Sparse artwork restoration rectangle is not approved by manifest")
            tim=gfx.Tim(zh_sparse_tim.apply(data,payload))
        else:
            restored=Image.open(ROOT/target["background"]).convert("RGB")
            if restored.size!=(tim.w,tim.h):
                raise ValueError("Artwork restoration dimensions differ from TIM")
            palette=np.asarray(tim.palette,np.int32);rgb=np.asarray(restored,np.int32)
            if "restoration_mask" in target:
                mask=np.asarray(Image.open(ROOT/target["restoration_mask"]).convert("L"))>0
                if mask.shape!=tim.idx.shape:raise ValueError("Artwork restoration mask dimensions differ")
                allowed=np.zeros_like(mask)
                for x0,y0,x1,y1 in target["regions"]:allowed[y0:y1,x0:x1]=True
                if np.any(mask&~allowed):raise ValueError("Artwork mask exceeds localized title band")
                ys,xs=np.nonzero(mask)
                distance=((rgb[ys,xs,None,:]-palette[None,:,:])**2).sum(axis=2);distance[:,0]=2**30
                tim.idx[ys,xs]=distance.argmin(axis=1)
            else:
                for x0,y0,x1,y1 in target["regions"]:
                    for y in range(y0,y1):
                        distance=((rgb[y,x0:x1,None,:]-palette[None,:,:])**2).sum(axis=2)
                        distance[:,0]=2**30
                        tim.idx[y,x0:x1]=distance.argmin(axis=1)
        for index,row in enumerate(target["labels"]):
            labels.append(draw_label(tim,row["rect"],row["en"],scale=2 if index==0 else 1,outline=1))
    elif kind=="battle_callout":
        for row in target["labels"]:
            box=list(row["rect"])
            if allow_callout_expansion:
                box[3]=box[1]+12
                tim.fill(*box,0)
                labels.append(draw_label(tim,box,row["en"],indices=(1,4)))
            else:
                labels.append(compact_callout(tim,box))
    else:
        raise ValueError("Unsupported raster target "+kind)
    return tim.bytes(),labels


def font_codepoints(path):
    """Read Unicode cmap formats4/12 without adding a fontTools dependency."""
    data=path.read_bytes();tables=struct.unpack_from(">H",data,4)[0];cmap_offset=None
    for index in range(tables):
        tag,_,offset,_=struct.unpack_from(">4sIII",data,12+16*index)
        if tag==b"cmap":cmap_offset=offset;break
    if cmap_offset is None:raise ValueError("Font has no cmap")
    count=struct.unpack_from(">H",data,cmap_offset+2)[0];result=set()
    for index in range(count):
        platform,encoding,relative=struct.unpack_from(">HHI",data,cmap_offset+4+8*index)
        if platform not in (0,3):continue
        offset=cmap_offset+relative;fmt=struct.unpack_from(">H",data,offset)[0]
        if fmt==12:
            groups=struct.unpack_from(">I",data,offset+12)[0]
            for group in range(groups):
                start,end,glyph=struct.unpack_from(">III",data,offset+16+12*group)
                result.update(range(start+(glyph==0),end+1))
        elif fmt==4:
            segments=struct.unpack_from(">H",data,offset+6)[0]//2
            ends=offset+14;starts=ends+2*segments+2;deltas=starts+2*segments;ranges=deltas+2*segments
            for segment in range(segments):
                end=struct.unpack_from(">H",data,ends+2*segment)[0]
                start=struct.unpack_from(">H",data,starts+2*segment)[0]
                delta=struct.unpack_from(">h",data,deltas+2*segment)[0]
                relative=struct.unpack_from(">H",data,ranges+2*segment)[0]
                for point in range(start,min(end,0xfffe)+1):
                    glyph=(point+delta)&65535 if relative==0 else struct.unpack_from(">H",data,ranges+2*segment+relative+2*(point-start))[0]
                    if glyph:result.add(point)
    if not result:raise ValueError("Font has no supported Unicode cmap")
    return result


def validate_glyphs(selected):
    cmap=font_codepoints(FONT)
    texts=[INDEX_TEXT,APPEARANCE_TEXT,"关卡0123456789"]
    for target in selected:
        if isinstance(target.get("en"),str):texts.append(target["en"])
        texts.extend(row["en"] for row in target.get("labels",[]))
        texts.extend(target.get("tabs",[]))
    raw_missing=sorted({c for text in texts for c in clean(text) if not c.isspace() and ord(c) not in cmap})
    missing=[c for c in raw_missing if c not in GLYPH_VARIANTS or ord(GLYPH_VARIANTS[c]) not in cmap]
    if missing:
        raise ValueError("Cubic11 missing glyphs: "+repr(missing))
    compact_missing=[ch for ch in "会心" if ord(ch) not in font_codepoints(COMPACT_FONT)]
    if compact_missing:raise ValueError("Compact callout font missing "+repr(compact_missing))
    required={c for s in texts for c in clean(s) if not c.isspace()}
    levels=set()
    for char in required:
        display=GLYPH_VARIANTS.get(char,char)
        levels.update(np.asarray(font().getmask(display)).tolist())
    if levels-{0,255}:raise ValueError("Cubic11 native point-size rendering introduced antialiasing: "+repr(sorted(levels)))
    return {"required_characters":len(required),"missing":[],
            "source_characters_requiring_visual_variant":raw_missing,
            "visual_glyph_variants":{ch:GLYPH_VARIANTS[ch] for ch in raw_missing},
            "font_point_size":NATIVE_SIZE,"native_han_ink_pixels":11,"binary_pixel_values":sorted(levels),
            "font_sha256":hashlib.sha256(FONT.read_bytes()).hexdigest(),
            "compact_callout_font_sha256":hashlib.sha256(COMPACT_FONT.read_bytes()).hexdigest()}


def compare_image(before,after):
    a,b=zh_graphics.rgb(before),zh_graphics.rgb(after)
    pair=Image.new("RGB",(a.width+b.width+8,max(a.height,b.height)),(45,0,45))
    pair.paste(a,(0,0));pair.paste(b,(a.width+8,0))
    return pair


def patch_files(files,manifest=None,previews=False,output_dir=None,allow_callout_expansion=False):
    """Patch caller-owned files atomically; return precise coverage and QA report.

    allow_callout_expansion is only valid after the caller patches both runtime
    Critical quads to 24x12 and verifies their larger texture rectangle is free.
    It is false by default. No runtime geometry is patched by this module.
    """
    selected=targets(manifest);glyphs=validate_glyphs(selected)
    output=Path(output_dir) if output_dir else PREVIEW
    report=[];omitted=[];preserved=[];working=dict(files);images=[]
    for archive in sorted({target["archive"] for target in selected}):
        key=archive+".DAT";entries=repack.dat_entries(files[key]);original_entries=list(entries)
        changed_entries=set()
        for target in [t for t in selected if t["archive"]==archive]:
            asset=zh_graphics.name(target);kind=target["kind"]
            if kind=="encyclopedia_tab_font":
                preserved.append({"asset":asset,"kind":kind,"reason":"Native encyclopedia category sprites and Japanese-reading bucket structure preserved; this atlas is separate from the Chinese font pages."})
                continue
            dependency=target.get("restoration_delta",target.get("background"))
            if kind=="artwork_logo" and (not dependency or not (ROOT/dependency).is_file()):
                omitted.append({"asset":asset,"kind":kind,"texts":[row["en"] for row in target["labels"]],
                                "reason":"Required original text-free artwork restoration is absent; preserve original art rather than destroy it.",
                                "missing_dependency":dependency})
                continue
            effective=deepcopy(target)
            if kind=="battle_callout" and allow_callout_expansion:
                effective["regions"]=[list(r[:3])+[r[1]+12] for r in target["regions"]]
            index=target["entry"]
            old_blocks=cm.blocks(entries[index]) if "block" in target else None
            before=old_blocks[target["block"]] if old_blocks is not None else entries[index]
            after,labels=render(before,target,allow_callout_expansion)
            qa=zh_graphics.verify(before,after,effective)
            if kind=="episode":
                background=gfx.Tim(before).idx[5,5];new=gfx.Tim(after)
                for digit in range(10):
                    x=digit*24
                    assert np.all(new.idx[104:128,x:x+6]==background)
                    assert np.all(new.idx[104:128,x+18:x+24]==background)
                assert np.all(new.idx[100:,240:256]==background)
                assert np.all(new.idx[100:,308:]==background)
            if old_blocks is not None:
                block=target["block"]
                entries[index]=zh_graphics.replace_cm(entries[index],{block:after})
                new_blocks=cm.blocks(entries[index])
                assert new_blocks[block]==after
                assert len(old_blocks)==len(new_blocks)
                assert all(old==new for i,(old,new) in enumerate(zip(old_blocks,new_blocks)) if i!=block)
            else:
                entries[index]=after
            changed_entries.add(index)
            report.append({"asset":asset,"archive":archive,"entry":index,"block":target.get("block"),
                           "kind":kind,"regions":effective["regions"],**qa,"labels":labels,"runtime_verified":False})
            if previews:
                output.mkdir(parents=True,exist_ok=True)
                pair=compare_image(before,after)
                pair.resize((pair.width*2,pair.height*2),Image.Resampling.NEAREST).save(output/(asset+"_before_after.png"))
                (output/(asset+".tim")).write_bytes(after)
                images.append((asset,kind,zh_graphics.rgb(after)))
        assert all(old==new for i,(old,new) in enumerate(zip(original_entries,entries)) if i not in changed_entries)
        working[key]=repack.dat_pack(entries)
        packed=repack.dat_entries(working[key])
        assert len(packed)==len(entries)
        assert all(actual==expected+bytes((-len(expected))%2048)
                   for actual,expected in zip(packed,entries)),"DAT repack changed content beyond zero sector padding"
    summary={"status":"structural_checks_passed_runtime_pending","manifest_targets":len(selected),
             "patched_assets":len(report),"patched_kinds":dict(Counter(r["kind"] for r in report)),
             "rendered_label_instances":sum(len(r["labels"]) for r in report),
             "omitted_text_assets":len(omitted),"preserved_font_atlas_targets":len(preserved),
             "native_font_size":NATIVE_SIZE,"native_han_ink_pixels":11,"allowed_integer_scales":[1,2],"glyph_coverage":glyphs,
             "compact_callout_exception":{"font":"Misaki Gothic","native_size":8,"text":"会心","geometry":"original 24x8","resampled":False},
             "stage_card_geometry":"Compatible with existing stage_cards.patch_script; prefix is 关卡.",
             "callout_runtime_geometry_expansion_required":any(r["kind"]=="battle_callout" for r in omitted),
             "sources_written":False,"font_atlas_pixels_modified":False,
             "not_verified":["emulator/runtime", "Complete raster discovery outside the manifest", "Original background restoration artistic accuracy"]}
    result={"summary":summary,"assets":report,"omitted":omitted,"preserved":preserved}
    if previews:
        for page,start in enumerate(range(0,len(images),20),1):
            group=images[start:start+20];columns=4;width,height=324,276
            sheet=Image.new("RGB",(columns*width,((len(group)+columns-1)//columns)*height),(30,30,30))
            draw=ImageDraw.Draw(sheet)
            for index,(asset,kind,image) in enumerate(group):
                x,y=index%columns*width,index//columns*height
                draw.text((x+2,y+2),asset+" "+kind,fill=(255,255,0))
                sheet.paste(image,(x,y+18))
            sheet.save(output/("contact_%02d.png"%page))
        (output/"raster_full_report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    files.update({key:working[key] for key in working if key in {t["archive"]+".DAT" for t in selected}})
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,default=MANIFEST)
    parser.add_argument("--disc-dir",type=Path,default=ROOT/"work/source/disc")
    parser.add_argument("--output",type=Path,default=PREVIEW)
    parser.add_argument("--preview",action="store_true")
    parser.add_argument("--allow-callout-expansion",action="store_true")
    args=parser.parse_args()
    selected=targets(args.manifest)
    files={archive+".DAT":(args.disc_dir/(archive+".DAT")).read_bytes() for archive in {t["archive"] for t in selected}}
    result=patch_files(files,args.manifest,args.preview,args.output,args.allow_callout_expansion)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"raster_full_report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result["summary"],ensure_ascii=False,indent=2))
    if result["omitted"]:print(json.dumps(result["omitted"],ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
