"""Table-free native R3000 glyph lookup for the static11px Chinese atlas.

Custom codes0x1000..0x1fff encode page, plane, row and column directly.
The original0..1789 coordinates and8/12px advances remain available for
runtime player-name components and icon codes. No EXE growth is required.
"""
import struct
import zh_glyph_lookup as native
import zh_full_font as font

BASE=native.BASE
END=native.END
EXE_BASE=native.EXE_BASE
R=native.R


def assemble():
    out=[];labels={};fix=[]
    def i(op,rs,rt,n):out.append((op<<26)|(R[rs]<<21)|(R[rt]<<16)|(n&65535))
    def r(fn,rs='zero',rt='zero',rd='zero',sh=0):out.append((R[rs]<<21)|(R[rt]<<16)|(R[rd]<<11)|(sh<<6)|fn)
    def branch(op,rs,rt,label):fix.append((len(out),label));i(op,rs,rt,0);out.append(0)
    def label(name):labels[name]=len(out)
    i(12,'a1','t0',65535)
    i(12,'t0','v0',0xf000);i(9,'zero','v1',0x1000);branch(5,'v0','v1','native')
    # u = (code&31)*11. The output cell is exactly11pixels wide.
    i(12,'t0','v1',31);r(0,rt='v1',rd='a2',sh=3);r(0,rt='v1',rd='v0',sh=1)
    r(33,'a2','v0','a2');r(33,'a2','v1','a2');i(40,'a0','a2',14)
    r(2,rt='t0',rd='v0',sh=5);i(12,'v0','v0',15);r(0,rt='v0',rd='v0',sh=4);i(40,'a0','v0',15)
    r(2,rt='t0',rd='t1',sh=11);i(12,'t1','t1',1);i(9,'t1','t1',28)
    r(2,rt='t0',rd='t2',sh=9);i(12,'t2','t2',1);i(9,'t2','t2',240)
    r(2,rt='t0',rd='t3',sh=10);i(12,'t3','t3',1);r(0,rt='t3',rd='t3',sh=4);i(9,'t3','t3',48)
    i(9,'zero','v1',11);branch(4,'zero','zero','store')
    label('native')
    i(9,'zero','t1',28);i(9,'zero','t2',240)
    i(11,'t0','v0',320);branch(5,'v0','zero','narrow')
    i(9,'t0','v0',-110);i(9,'zero','v1',336)
    r(27,'v0','v1');r(18,rd='t3');r(16,rd='t4')
    r(33,'t1','t3','t1');i(9,'zero','v1',21)
    r(27,'t4','v1');r(18,rd='v0');r(16,rd='v1')
    r(0,rt='v0',rd='v0',sh=4);i(40,'a0','v0',15)
    r(0,rt='v1',rd='a2',sh=1);r(33,'a2','v1','a2');r(0,rt='a2',rd='a2',sh=2)
    i(40,'a0','a2',14);i(9,'zero','v1',12)
    i(11,'t0','v0',782);branch(5,'v0','zero','native_common')
    i(9,'t1','t1',-2);i(11,'t0','v0',1454);branch(4,'v0','zero','native_common')
    i(9,'zero','t2',241);branch(4,'zero','zero','native_common')
    label('narrow')
    i(12,'t0','v0',31);r(0,rt='v0',rd='v0',sh=3);i(40,'a0','v0',14)
    r(2,rt='t0',rd='v0',sh=5);r(0,rt='v0',rd='v0',sh=4);i(40,'a0','v0',15)
    i(9,'zero','v1',8)
    label('native_common');i(9,'zero','t3',48)
    label('store')
    i(41,'a0','v1',8);i(41,'a0','t1',12);i(41,'a0','t2',18);i(41,'a0','t3',16)
    i(9,'zero','v0',16);i(41,'a0','v0',10);r(8,rs='ra');i(43,'a0','zero',0)
    for index,name in fix:out[index]|=(labels[name]-index-1)&65535
    blob=struct.pack('<%dI'%len(out),*out)
    assert len(blob)<=END-BASE,(len(blob),END-BASE)
    return blob+bytes(END-BASE-len(blob)),out


def reference(code):
    if 0x1000<=code<0x2000:
        x,y,plane=font.location(code)
        return (11,16,28+x//256,x%256,y,48+(plane>>1)*16,240+(plane&1))
    return native.reference(code,'dual_plane')


def verify():
    blob,program=assemble();codes=list(range(1790))
    codes.extend(c for c in range(0x1000,0x2000) if c&31<23)
    for code in codes:
        m=native.execute(program,code)
        actual=(int.from_bytes(m[8:10],'little'),int.from_bytes(m[10:12],'little'),
                int.from_bytes(m[12:14],'little'),m[14],m[15],
                int.from_bytes(m[16:18],'little'),int.from_bytes(m[18:20],'little'))
        assert actual==reference(code),(code,actual,reference(code))
        assert m[:4]==bytes(4)
    return {'codes_executed':len(codes),'routine_bytes':len(program)*4,'reserved_bytes':len(blob),
            'native_codes_preserved':'0..1789','custom_range':'0x1000..0x1fff sparse positions',
            'custom_cell_width':11,'texture_pages':[28,29],'clut_columns':[48,64],
            'color_style_stride_rows':2,'exe_growth':0}


def patch(exe,plan=None):
    verify();blob,_=assemble();result=bytearray(exe);offset=BASE-EXE_BASE+0x800
    result[offset:offset+len(blob)]=blob
    assert len(result)==len(exe)
    return bytes(result)


if __name__=='__main__':print(verify())
