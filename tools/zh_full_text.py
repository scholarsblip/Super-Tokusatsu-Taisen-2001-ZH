"""Chinese text encoder and source-coordinate translation adapter.

Container relocation is shared with insert.py. The adapter uses frozen UIDs,
not guessed Japanese/English replacements, and preserves native icons/control
codes. It is independent of the font atlas implementation.
"""
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import unicodedata

import dump_script as D
import insert as I

ROOT=Path(__file__).resolve().parents[1]
CTRL=dict(I.CTRL)
CTRL['<p>']=0xFFFC
PH_WIDTH={'[HERO1]':96,'[HERO2]':60,'[HERO3]':96,'[HERO4]':60,
          '[VAR5]':96,'[VAR6]':72}
TOKEN=re.compile(r'<[^<>]*>|\[(?:HERO[1-4]|VAR[56])\]|\{[^{}]*\}|\r\n|\n|\r|[A-Za-z0-9]+(?:[\u0027\u2019-][A-Za-z0-9]+)*|.',re.S)
CONTROLS=re.compile(r'<c[123]>|</c>|<p>|\[(?:HERO[1-4]|VAR[56])\]|\{[^{}]*\}')


class Encoder:
    def __init__(self,plan,encode_plain):
        self.plan=plan
        self.encode_plain=encode_plain
        self.stats=Counter()
        self.valid_codes=set(range(320))|set(plan['encode'].values())|set(plan.get('reserved_wide_codes',[]))

    def plain(self,text):
        return self.encode_plain(text,self.plan)

    @staticmethod
    def width(codes):
        # The full font's new glyphs use 11px. A conservative 12px budget
        # also accommodates legacy wide symbols, names and old save files.
        return sum(8 if code<320 else 12 for code in codes if code<0xFF00)

    def atoms(self,text,icons):
        for token in TOKEN.findall(text):
            if token in CTRL:
                yield [CTRL[token]],PH_WIDTH.get(token,0),token
            elif token in ('\r\n','\n','\r'):
                yield [0xFFFB],0,'\n'
            elif token.startswith('{') and token.endswith('}'):
                # Lowercase {c287} is the decoder's name for native icon287,
                # not hexadecimal C287. Raw hexadecimal tokens are uppercase.
                if re.fullmatch(r'\{[0-9A-F]{4}\}',token):
                    code=int(token[1:-1],16)
                elif icons.get(token):
                    code=icons[token].pop(0)
                else:
                    raise ValueError('No original icon code for '+token)
                yield [code],0 if code>=0xFF00 else (8 if code<320 else 12),token
            elif token.startswith('<'):
                if token not in ('<L2>','<R2>','<L/R>'):
                    raise ValueError('Unsupported text control '+token)
                codes=self.plain('＜'+token[1:-1]+'＞')
                yield codes,self.width(codes),token
            else:
                codes=self.plain(token)
                yield codes,self.width(codes),token

    def encode(self,text,orig_words,font,width=None,max_lines=3):
        icons=I.icon_queue(orig_words,font)
        output=[];x=0;line=1
        for codes,advance,token in self.atoms(text,icons):
            if token=='<p>':
                output+=codes;x=0;line=1;continue
            if token=='\n':
                if width and line>=max_lines:
                    output.append(0xFFFC);line=1;self.stats['inserted_pages']+=1
                else:
                    output.append(0xFFFB);line+=1
                x=0;continue
            if width and advance>width:
                # A Latin asset/name must not escape the frame as one token.
                # Preserve every encoded character while breaking the run.
                chunks=[([c],8 if c<320 else 12) for c in codes]
            else:
                chunks=[(codes,advance)]
            for piece,pixels in chunks:
                if width and x+pixels>width:
                    if line>=max_lines:
                        output.append(0xFFFC);line=1;self.stats['inserted_pages']+=1
                    else:
                        output.append(0xFFFB);line+=1
                    x=0
                if token==' ' and x==0:continue
                output+=piece;x+=pixels
        if any(code<0xFF00 and code not in self.valid_codes for code in output):
            raise ValueError('Encoded glyph has no allocated or preserved cell')
        return output

    def line_tokens(self,tokens,icons,enc=None):
        output=[]
        for codes,_,_ in self.atoms(''.join(tokens),icons):output+=codes
        return output


class Translator:
    def __init__(self,encoder,translation_file,inputs,ui_dir):
        self.encoder=encoder
        self.inputs=Path(inputs)
        self.targets={r['uid']:r for r in json.loads(Path(translation_file).read_text())['rows']}
        self.units={r['uid']:r for r in json.loads((self.inputs/'units.json').read_text())}
        self.sources={r['uid']:r for r in (json.loads(x) for x in (self.inputs/'all_units.input.jsonl').read_text().splitlines())}
        self.override_rows={}
        for override_name in ('build_overrides.v0.2.1.json','build_choice_fixes.v0.2.1.json','build_runtime_fixes.v0.2.4.json'):
            overrides=ROOT/'work/translation/zh_CN'/override_name
            if not overrides.exists():continue
            import hashlib
            for edit in json.loads(overrides.read_text())['rows']:
                uid=edit['uid']
                expected=hashlib.sha256(self.sources[uid]['text'].encode()).hexdigest()
                if edit['source_sha256']!=expected:raise ValueError('Build override source drift '+uid)
                self.targets[uid]={**self.targets[uid],'zh_CN':edit['zh_CN']}
                self.override_rows[uid]=edit
        self.rows=json.loads((self.inputs/'strings.json').read_text())+json.loads((self.inputs/'extra_occurrences.json').read_text())
        self.by_occ={}
        for row in self.rows:
            key=(row['file'],row['off'])
            if key in self.by_occ and self.by_occ[key]['uid']!=row['uid']:
                raise ValueError('Conflicting source coordinates '+str(key))
            self.by_occ[key]=row
        self.by_text={}
        for uid,unit in self.units.items():
            self.by_text[(unit.get('speaker_jp'),unit['jp'])]=self.targets[uid]['zh_CN']
        self.manual=json.loads((Path(ui_dir)/'manual.zh.json').read_text())
        self.by_codes={};self.seen=Counter();self.occurrences=set();self.problems=[]
        self.report=[];self.defaults=[]

    def words_for(self,src,ws,font,occ=None):
        source=self.by_occ.get(occ)
        if source is not None:self.by_codes[(src,tuple(ws))]=source
        else:source=self.by_codes.get((src,tuple(ws)))
        sp,body=D.decode(ws,font,dialogue=src in ('stage','bquote'))
        if source is None:
            text=self.by_text.get((sp,body))
            if text is None and sp is None:text=self.manual.get(body)
            if text is None:
                if any(16<=c<1790 for c in ws):self.problems.append({'kind':'unmapped_string','src':src,'occ':occ,'source_preview':body[:80]})
                return None
            target={'zh_CN':text,'speaker_zh_CN':None}
            uid=None
        else:
            uid=source['uid'];target=self.targets[uid]
            self.seen[uid]+=1
            if occ:self.occurrences.add(occ)
            # Some extra encyclopedia pieces do not carry decoded JP fields.
            # Compare controls to the authoritative selected source in that case.
            reference=source.get('jp',self.sources[uid]['text'])
            if CONTROLS.findall(reference)!=CONTROLS.findall(target['zh_CN']):
                raise ValueError(str((uid,'source control stream changed')))
        text=target['zh_CN']
        if uid=='U20900':
            # The eight save-name components are bounded native code strings.
            # Keep FF05 separators and legacy code values for the surnames;
            # six newly reserved legacy cells make the given names Chinese.
            legacy=self.encoder.plan.get('legacy_default_names')
            if legacy is None:
                self.defaults.append({'uid':uid,'policy':'original_code_values_retained'})
                return list(ws)
            result=[]
            for index,codes in enumerate(legacy):
                if index:result.append(0xFF05)
                result+=codes
            result.append(0xFF05)
            # Preserve the final action label after the eighth separator.
            tail=text.split('[VAR5]')[-1]
            result+=self.encoder.encode(tail,ws,font)
            assert all(len(c)<=limit for c,limit in zip(legacy,(8,5,8,5,8,5,8,5)))
            self.defaults.append({'uid':uid,'policy':'Chinese_legacy_code_cells','components':legacy})
            return result
        if src=='db' and I.GRID.match(body) and len(ws)>=20:
            # The original name-entry program expects one native 8px cell per
            # selectable code. Use the corrected Latin keyboard reference.
            chosen=self.sources.get(uid,{}).get('text',text)
            if re.search(r'[^\x00-\x7f]',chosen):chosen=text
            result=I.grid_words(chosen,len(ws))
            self.report.append({'uid':uid,'kind':'native_name_entry_grid','cells':len(ws)})
            return result
        is_dialogue=src in ('stage','bquote')
        speaker=target.get('speaker_zh_CN')
        if sp is not None and speaker is None:
            raise ValueError(str((uid,'source speaker was lost')))
        result=[]
        if sp is not None:
            header=self.encoder.encode(speaker,ws,font)
            if self.encoder.width(header)>220:
                self.problems.append({'kind':'speaker_header_too_wide','uid':uid,'speaker':speaker,'pixels':self.encoder.width(header)})
            result=[0xFF33]+header+[0xFF30,0xFFFB]
        choice=is_dialogue and I.CHOICE.match(body.strip())
        if choice:
            source_lines=body.strip().count('\n')+1
            lines=text.strip().splitlines()
            if len(lines)!=source_lines:
                quoted=re.findall(r'"([^"\n]*)"|“([^”\n]*)”|「([^」\n]*)」|『([^』\n]*)』',text)
                options=[next((part for part in groups if part),'') for groups in quoted]
                if len(options)!=source_lines:
                    # The MT may omit the outermost closing quote. Interior
                    # close/open pairs still unambiguously separate options.
                    separated=re.split(r'["”」]\s*["“「]',text.strip())
                    if len(separated)==source_lines:
                        options=[part.strip().strip('"“”「」') for part in separated]
                if len(options)!=source_lines:
                    raise ValueError(str((uid,'choice option count changed',source_lines,len(lines),len(options))))
                lines=['"'+option+'"' for option in options]
                self.report.append({'uid':uid,'kind':'restored_choice_line_structure','options':len(lines)})
            encoded=self.encoder.encode('\n'.join(lines),ws,font)
            for line in lines:
                if self.encoder.width(self.encoder.encode(line,ws,font))>220:
                    self.problems.append({'kind':'choice_option_too_wide','uid':uid,'text':line})
        else:
            width=208 if sp is not None else 236
            if src=='encyc':width=264
            if not is_dialogue and src!='encyc':width=None
            encoded=self.encoder.encode(text,ws,font,width=width,max_lines=2 if src=='bquote' else 3 if src=='stage' else 99)
        result+=encoded
        if is_dialogue and sp is None and result and result[0]==0xFF33:result.insert(0,0xFF30)
        I.STATS['translated_'+src]+=1
        return result
