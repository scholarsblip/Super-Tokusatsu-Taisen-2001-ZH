"""Build an explicitly partial Chinese prototype with a uniform native font.

Dry-run (default) prepares reports/previews only. --write rebuilds a local disc.
Only the executable menu map and available translated first-overlay rows are
inserted. Other translation drafts are not silently claimed as inserted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import unicodedata

import cm
import dump_script as D
import repack
import zh_font as Z
import zh_graphics
import zh_glyph_lookup

ROOT=Path(__file__).resolve().parents[1]
TR=ROOT/'work/translation/zh_CN'
DISC=ROOT/'work/source/disc'
OUT=ROOT/'work/output'
TOKEN=re.compile(r'<c[123]>|</c>|<p>|\[(?:HERO[1-4]|VAR[56])\]|\{[^}]+\}|[A-Za-z0-9]+(?:[\u002d\u30fc\uff0d\u0027][A-Za-z0-9]+)*|.',re.S)
PLACE={'[HERO1]':0xff01,'[HERO2]':0xff02,'[HERO3]':0xff03,'[HERO4]':0xff04,'[VAR5]':0xff05,'[VAR6]':0xff06}
PLACE_WIDTH={'[HERO1]':96,'[HERO2]':60,'[HERO3]':96,'[HERO4]':60,'[VAR5]':96,'[VAR6]':72}

def words(ws):return struct.pack('<%dH'%len(ws),*ws)

def runtime_name_glyphs(fonts):
    """Redraw actual runtime name codes, which are absent from literal text.

    Keep encoded values and advances intact. Only normal kana/Latin cells and
    the source's default-name cells are included; weapon/icon cells stay intact.
    """
    db=repack.dat_entries((DISC/'MAPMAIN.DAT').read_bytes())[2]
    table=struct.unpack_from('<3503H',db)
    defaults=[]
    for index in range(0xb36,0xb3e):
        pos=table[index];codes=[]
        while True:
            code=struct.unpack_from('<H',db,pos)[0];pos+=2
            if code>=1454:break
            codes.append(code)
        defaults.append({'index':hex(index),'codes':codes})
    exe=(DISC/'SLPS_028.63').read_bytes();var6=[]
    for addr,limit in [(0x800aa108,6),(0x800aa114,7)]:
        codes=list(struct.unpack_from('<%dH'%limit,exe,addr-0x80010000+0x800))
        assert codes[-1]==0xff05
        var6.append({'address':hex(addr),'codes':codes[:-1]})
    dynamic_codes={c for row in defaults+var6 for c in row['codes']}
    reference=Z.original_map('11')
    # Rows8/9 include badges which resemble kana; exclude them as icons.
    alphabet={code:char for code,char in reference.items() if code<256 and len(char)==1
              and (char==' ' or char.isascii() and char.isalnum() or '\u3040'<=char<='\u30ff')}
    mappings={}
    for font in fonts:
        original=Z.original_map(font);mapping=dict(alphabet)
        for code in dynamic_codes:
            assert original.get(code)==reference.get(code),(font,code,'runtime name differs by font')
            char=original[code]
            assert len(char)==1
            mapping[code]=unicodedata.normalize('NFKC',char) if code<320 else char
        mappings[str(font)]=mapping
    return mappings,{'default_names':defaults,'var6':var6,
                     'alphabet_codes':len(alphabet),'runtime_name_codes':sorted(dynamic_codes),
                     'redraw_codes_per_font':{f:len(m) for f,m in mappings.items()},
                     'excluded':'weapon/icon cells; arbitrary VAR5 expansion outside name alphabet'}

def context_plan(plan,font):
    result=dict(plan);result['variant']=str(font);encoding=dict(plan['encode'])
    for code,char in sorted(Z.original_map(font).items()):
        if len(char)==1:encoding.setdefault(char,code)
    for char,native in Z.ALIASES.items():
        if char not in encoding and native in encoding:encoding[char]=encoding[native]
    result['encode']=encoding
    return result

def compress_replace(buf,replacements):
    pos=0;out=bytearray();index=0
    while buf[pos:pos+2]==b'CM':
        old,nxt=cm.decompress(buf,pos)
        new=replacements.get(index)
        if new is None:out+=buf[pos:nxt]
        else:
            packed=cm.compress(new)
            assert cm.decompress(packed)[0]==new
            out+=packed
        pos=nxt;index+=1
    assert all(i<index for i in replacements)
    return bytes(out)

def encode_body(text,plan,width=236,maxlines=3):
    result=[];x=0;line=1;added_pages=0
    for token in TOKEN.findall(text):
        if token=='<p>':result.append(0xfffc);x=0;line=1;continue
        if token=='</c>':result.append(0xff30);continue
        if token.startswith('<c'):result.append(0xff30+int(token[2]));continue
        if token in PLACE:codes=[PLACE[token]];advance=PLACE_WIDTH[token]
        elif token.startswith('{'):
            code=int(token[1:-1],16);codes=[code];advance=0 if code>=0xff00 else 12
        elif token=='\n':result.append(0xfffb);x=0;line+=1;continue
        else:
            codes=Z.encode_plain(token,plan);advance=sum(8 if code<320 else 12 for code in codes)
            assert advance<=width,(token,'unbreakable token exceeds frame')
        if x+advance>width:
            if line>=maxlines:result.append(0xfffc);line=1;added_pages+=1
            else:result.append(0xfffb);line+=1
            x=0
        if token==' ' and x==0:continue
        result.extend(codes);x+=advance
    return result,added_pages

def build(version,write=False):
    OUT.mkdir(parents=True,exist_ok=True)
    ui=json.loads((TR/'exe_strings.zh.json').read_text())
    ui={k:v for k,v in ui.items() if not k.startswith('_') and v is not None}
    translations={}
    for path in sorted((TR/'out').glob('Z*.json')):
        for row in json.loads(path.read_text())['rows']:
            assert row['uid'] not in translations,row['uid']
            translations[row['uid']]=row
    source_rows=json.loads((ROOT/'work/script/ja/strings.json').read_text())
    rows=[r for r in source_rows if r['file']=='STAGE0005']
    chosen={r['uid'] for r in rows}&set(translations)
    texts=list(ui.values())
    for uid in sorted(chosen):
        r=translations[uid];texts.append(r['zh_CN'])
        if r.get('speaker_zh_CN'):texts.append(r['speaker_zh_CN'])
    for row in rows:
        if row['uid'] in chosen and row.get('speaker_jp'):
            texts.append(translations[row['uid']].get('speaker_zh_CN') or row['speaker_jp'])
    # A scene's existing right-page glyphs remain available in that scene.
    # Allocate shared extension cells only when at least one actual context
    # needs the character. Executable labels use stable glyphs in every bank.
    missing=set()
    for row in rows:
        if row['uid'] not in chosen:continue
        t=translations[row['uid']]
        chars=Z.required_chars([t['zh_CN'],t.get('speaker_zh_CN') or row.get('speaker_jp') or ''])
        existing={v for v in Z.original_map(row['font']).values() if len(v)==1}
        missing|=chars-existing
    plan=Z.plan(list(ui.values())+[''.join(missing)],mode='extension',capacity=672)
    # Narrow native weapon badges must remain icons. Plain Chinese words use
    # ordinary wide cells instead of squeezing a Han character into8pixels.
    for ch in sorted(Z.required_chars(texts)):
        if '\u3400'<=ch<='\u9fff' and plan['encode'].get(ch,320)<320:
            code=1454+len(plan['new_glyphs']);assert code<2126
            plan['new_glyphs'][ch]=code;plan['encode'][ch]=code
    # Keep the original battle/encyclopedia range0..1789 available. New text
    # uses a resident atlas outside the complete cached portrait sheet.
    remap_new={code:1790+code-1454 for code in plan['new_glyphs'].values()}
    plan['new_glyphs']={ch:remap_new[code] for ch,code in plan['new_glyphs'].items()}
    plan['encode']={ch:remap_new.get(code,code) for ch,code in plan['encode'].items()}
    assert len(plan['new_glyphs'])<=504,'Resident atlas capacity exceeded'
    plan['new_glyph_count']=len(plan['new_glyphs']);plan['layout']='resident_ui'
    plan['slots_available']=504
    plan['original_resource_pixels_preserved']=False
    plan['original_non_target_pixels_preserved']=True
    plan['risk']='Resident atlas needs runtime checks; full-game and battle coverage are not claimed.'
    cells=Z.render_cells(plan,ROOT/'incoming/Cubic11/Cubic_11.ttf')
    used={}
    def collect(text,font,encoding):
        mapping=used.setdefault(str(font),{})
        for char in Z.required_chars([text]):
            code=encoding['encode'][char]
            if code>=1454:continue
            drawn=unicodedata.normalize('NFKC',char) if code<320 else char
            if len(drawn)!=1:drawn=char
            assert code not in mapping or mapping[code]==drawn,(font,code,char,mapping.get(code))
            mapping[code]=drawn
    for text in ui.values():collect(text,'11',plan)
    for row in rows:
        if row['uid'] not in chosen:continue
        tr=translations[row['uid']];cp=context_plan(plan,row['font'])
        collect(tr['zh_CN'],row['font'],cp)
        if row.get('speaker_jp'):collect(tr.get('speaker_zh_CN') or row['speaker_jp'],row['font'],cp)
    runtime_maps,runtime_report=runtime_name_glyphs(sorted(set(used)|{'11'}))
    for font,mapping in runtime_maps.items():
        target=used.setdefault(font,{})
        for code,char in mapping.items():
            assert code not in target or target[code]==char,(font,code,'runtime/literal glyph conflict')
            target[code]=char
    mainchars={}
    for font,mapping in used.items():
        for code,char in mapping.items():
            if code<320 or code in Z.FIXED:
                assert code not in mainchars or mainchars[code]==char
                mainchars[code]=char
    mainchars.update({c:ch for c,ch in used.get('11',{}).items() if c in Z.VARIABLE})
    maincells=Z.render_code_cells(mainchars,narrow='compress')
    (OUT/('STT2001_ZH_v'+version+'_font_plan.json')).write_text(json.dumps(plan,ensure_ascii=False,indent=1))
    Z.preview(list(ui.values())[:20],plan,cells,OUT/('STT2001_ZH_v'+version+'_preview.png'))
    exe=bytearray(zh_glyph_lookup.patch((DISC/'SLPS_028.63').read_bytes(),layout='resident_ui'));uicheck=[]
    # The resident portrait upload gains a64-word prefix. The original image
    # remains at its original physical coordinates; this changes the upload
    # origin, not any portrait pixels or draw-list coordinates.
    portrait_origin=0x800a7158-0x80010000+0x800
    assert struct.unpack_from('<H',exe,portrait_origin)[0]==704
    struct.pack_into('<H',exe,portrait_origin,640)
    for key,text in ui.items():
        a=int(key,16);q=a
        while int.from_bytes(exe[q:q+2],'little') not in (0xfffe,0xfffd):q+=2
        encoded=Z.encode_plain(text,plan)
        assert Z.decode_plain(encoded,plan)==Z.normalize_aliases(text,plan)
        assert len(encoded)*2<=q-a,(key,text,len(encoded)*2,q-a)
        old=D.words(exe,a,q);oldpx=sum(8 if w<320 else 12 for w in old)
        newpx=sum(8 if w<320 else 12 for w in encoded)
        exe[a:q]=words(encoded)+bytes(q-a-len(encoded)*2)
        uicheck.append({'offset':key,'zh_CN':text,'source_px':oldpx,'target_px':newpx,'available_bytes':q-a,'written_bytes':len(encoded)*2})
    mm=repack.dat_entries((DISC/'MAPMAIN.DAT').read_bytes())
    ev=repack.dat_entries((DISC/'EVENT.DAT').read_bytes())
    fontchecks=[]
    for arr,index,label in [(mm,7,'MAPMAIN7'),(ev,10,'EVENT10')]:
        old=arr[index];arr[index]=Z.patch_tim(old,maincells,mode='extension',layout='dual_plane',allow_redraw=True)
        fontchecks.append({'asset':label,**Z.validate_tim(old,arr[index],maincells,mode='extension',layout='dual_plane',allow_redraw=True)})
    blocks=cm.blocks(mm[25]);new=Z.patch_tim(blocks[3],maincells,mode='extension',layout='dual_plane',allow_redraw=True)
    fontchecks.append({'asset':'MAPMAIN25_block3',**Z.validate_tim(blocks[3],new,maincells,mode='extension',layout='dual_plane',allow_redraw=True)})
    mm[25]=compress_replace(mm[25],{3:new})
    for font,mapping in used.items():
        varchars={c:ch for c,ch in mapping.items() if c in Z.VARIABLE}
        if not varchars:continue
        vcells=Z.render_code_cells(varchars,narrow='compress');idx=int(font)
        old=ev[idx];ev[idx]=Z.patch_tim(old,vcells,sheet='variant',mode='unused',layout='dual_plane',allow_redraw=True)
        fontchecks.append({'asset':'EVENT'+font,**Z.validate_tim(old,ev[idx],vcells,sheet='variant',mode='unused',layout='dual_plane',allow_redraw=True)})
    old=mm[8];mm[8]=Z.patch_resident_atlas(old,cells)
    fontchecks.append({'asset':'MAPMAIN8_resident_atlas',**Z.validate_resident_atlas(old,mm[8],cells)})
    stage=repack.dat_entries((DISC/'STAGE.DAT').read_bytes());old=stage[5]
    strings=D.overlay_strings(old,0);nptr=strings[0][0]//4
    ptrs=struct.unpack_from('<%dI'%nptr,old,0);body=bytearray();remap={};changed=[]
    at={r['off']:r for r in rows}
    for off,ws,term in strings:
        remap[off]=4*nptr+len(body);r=at.get(off);out=list(ws)
        if r and r['uid'] in chosen:
            tr=translations[r['uid']];out=[]
            rowplan=context_plan(plan,r['font'])
            if r.get('speaker_jp'):
                speaker=tr.get('speaker_zh_CN') or r['speaker_jp']
                out=[0xff33]+encode_body(speaker,rowplan,width=1000,maxlines=1)[0]+[0xff30,0xfffb]
            encoded,added=encode_body(tr['zh_CN'],rowplan,width=208 if r.get('speaker_jp') else 236);out+=encoded
            assert added<=1,(r['uid'],'too many new pages')
            tokens=lambda s:re.findall(r'<c[123]>|</c>|<p>|\[(?:HERO[1-4]|VAR[56])\]|\{[^}]+\}',s)
            assert tokens(r['jp'])==tokens(tr['zh_CN']),(r['uid'],'tokens changed')
            changed.append({'uid':r['uid'],'source_offset':off,'source_font':r['font'],'added_pages':added})
        body+=words(out+[term])
    newptr=[0x800e0000+remap[p-0x800e0000] for p in ptrs]
    new=struct.pack('<%dI'%nptr,*newptr)+body;new+=bytes(-len(new)%4)
    assert len(new)<=0x12c00
    stage[5]=new;stage[630]=compress_replace(stage[630],{4:new})
    assert cm.blocks(stage[630])[4]==new
    # Every pointer still targets one of the new string starts.
    assert set(p-0x800e0000 for p in newptr)<=set(remap.values())
    files={'SLPS_028.63':bytes(exe),'MAPMAIN.DAT':repack.dat_pack(mm),'EVENT.DAT':repack.dat_pack(ev),'STAGE.DAT':repack.dat_pack(stage)}
    graphics_report=zh_graphics.patch_files(files,previews=True)
    report={'version':version,'language':'zh_CN','status':'dry_run' if not write else 'built_runtime_verification_pending',
      'scope':'58 executable labels and available Chinese rows in first stage overlay only',
      'ui_strings_inserted':len(uicheck),'unique_stage_units_inserted':len(chosen),'stage_occurrences_inserted':len(changed),
      'first_stage_unique_units':len(set(r['uid'] for r in rows)),
      'font_new_glyphs':len(cells),'font_uniform_redraw_codes':{k:len(v) for k,v in used.items()},'font_runtime_name_redraw':runtime_report,'font_checks':fontchecks,'ui_checks':uicheck,'stage_checks':changed,'glyph_routine':zh_glyph_lookup.verify('resident_ui'),
      'warnings':['Resident atlas requires scene/portrait validation; a complete playthrough is not verified.','Only selected main-menu/options/raster labels are included; battle encyclopedia, database and other raster translations are not included.','Most game content remains Japanese.'],
      'graphics':graphics_report,'emulator_verified':False,'source_bin_sha256':'219d9c4f64caf670b5e400612fa19677ed9a3f59a7ebdb72c12c425412795465'}
    if write:
        name='STT2001_ZH_v'+version;dst=OUT/(name+'.bin')
        repack.rebuild(str(ROOT/'Super Tokusatsu Taisen 2001 (Japan).bin'),str(dst),files)
        (OUT/(name+'.cue')).write_text('FILE "'+name+'.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
        report['output_bytes']=dst.stat().st_size
        h=hashlib.sha256()
        with dst.open('rb') as f:
            for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
        report['output_sha256']=h.hexdigest()
    (OUT/('STT2001_ZH_v'+version+'_report.json')).write_text(json.dumps(report,ensure_ascii=False,indent=1))
    print(json.dumps({k:v for k,v in report.items() if k not in ('font_checks','ui_checks','stage_checks','graphics')},ensure_ascii=False,indent=1))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('version');p.add_argument('--write',action='store_true');a=p.parse_args();build(a.version,a.write)
