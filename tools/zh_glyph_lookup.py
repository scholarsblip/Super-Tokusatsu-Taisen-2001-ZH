"""Native R3000 lookup with an optional resident Chinese atlas on page10.

No external assembler is required. The instruction subset is independently
executed for all2136 test codes before its bytes can be written to an EXE.
Original codes0..1789 retain their coordinates, width and palette. The current
resident_ui layout uses codes1790..2293 on page10,y48..239. Legacy layouts are
retained to reproduce the VRAM regression investigation.
"""
import struct

BASE=0x8004a7d8
END=0x8004a954
EXE_BASE=0x80010000
R={'zero':0,'v0':2,'v1':3,'a0':4,'a1':5,'a2':6,'t0':8,'t1':9,'t2':10,'t3':11,'t4':12,'ra':31}

def assemble(layout='dual_plane'):
    assert layout in ('dual_plane','upper13','resident_ui')
    out=[];labels={};fix=[]
    def i(op,rs,rt,n):out.append((op<<26)|(R[rs]<<21)|(R[rt]<<16)|(n&65535))
    def r(fn,rs='zero',rt='zero',rd='zero',sh=0):out.append((R[rs]<<21)|(R[rt]<<16)|(R[rd]<<11)|(sh<<6)|fn)
    def branch(op,rs,rt,label):fix.append((len(out),label));i(op,rs,rt,0);out.append(0)
    def label(name):labels[name]=len(out)
    i(12,'a1','t0',65535)
    if layout in ('upper13','resident_ui'):
        i(11,'t0','v0',1790);branch(5,'v0','zero','native')
        i(11,'t0','v0',2294 if layout=='resident_ui' else 2462);branch(4,'v0','zero','native')
        if layout=='resident_ui':
            i(9,'t0','v0',-1790);i(9,'zero','v1',252)
            r(27,'v0','v1');r(18,rd='t3');r(16,rd='t4')
            i(9,'t3','t2',240);i(9,'zero','v1',21)
            r(27,'t4','v1');r(18,rd='v0');r(16,rd='v1')
            r(0,rt='v0',rd='v0',sh=4);i(9,'v0','v0',48);i(40,'a0','v0',15)
            r(0,rt='v1',rd='a2',sh=1);r(33,'a2','v1','a2');r(0,rt='a2',rd='a2',sh=2)
            i(40,'a0','a2',14);i(9,'zero','t1',10);i(9,'zero','v1',12)
            branch(4,'zero','zero','store')
        else:
            i(9,'t0','t0',-336)
        label('native')
    i(9,'zero','t1',28);i(9,'zero','t2',240)
    i(11,'t0','v0',320);branch(5,'v0','zero','narrow')
    i(9,'t0','v0',-110);i(9,'zero','v1',336)
    r(27,'v0','v1');r(18,rd='t3');r(16,rd='t4')
    i(9,'t3','t1',28);i(9,'zero','v1',21)
    r(27,'t4','v1');r(18,rd='v0');r(16,rd='v1')
    r(0,rt='v0',rd='v0',sh=4);i(40,'a0','v0',15)
    r(0,rt='v1',rd='a2',sh=1);r(33,'a2','v1','a2');r(0,rt='a2',rd='a2',sh=2)
    i(40,'a0','a2',14);i(9,'zero','v1',12)
    i(11,'t0','v0',782);branch(5,'v0','zero','common')
    i(9,'t1','t1',-2)
    i(11,'t0','v0',1454);branch(5,'v0','zero','layer1')
    i(11,'t0','v0',1790);branch(5,'v0','zero','common')
    i(11,'t0','v0',2126);branch(4,'v0','zero','common')
    i(9,'t1','t1',-1)
    label('layer1');i(9,'zero','t2',241);branch(4,'zero','zero','common')
    label('narrow')
    i(12,'t0','v0',31);r(0,rt='v0',rd='v0',sh=3);i(40,'a0','v0',14)
    r(2,rt='t0',rd='v0',sh=5);r(0,rt='v0',rd='v0',sh=4);i(40,'a0','v0',15)
    i(9,'zero','v1',8)
    label('common')
    if layout=='upper13':
        i(12,'a1','t0',65535)
        i(11,'t0','v0',1790);branch(5,'v0','zero','store')
        i(11,'t0','v0',2462);branch(4,'v0','zero','store')
        i(9,'zero','t1',13)
    if layout in ('upper13','resident_ui'):
        label('store')
    i(41,'a0','v1',8);i(41,'a0','t1',12);i(41,'a0','t2',18)
    i(9,'zero','v0',48);i(41,'a0','v0',16)
    i(9,'zero','v0',16);i(41,'a0','v0',10)
    r(8,rs='ra');i(43,'a0','zero',0)
    for index,name in fix:out[index]|=(labels[name]-index-1)&65535
    blob=struct.pack('<%dI'%len(out),*out)
    assert len(blob)<=END-BASE
    return blob+bytes(END-BASE-len(blob)),out

def execute(program,code):
    """Small independent interpreter including MIPS branch delay slots."""
    reg=[0]*32;reg[4]=0x1000;reg[5]=code;reg[31]=0xffffffff
    mem=bytearray(32);pc=0;pending=None;hi=lo=0
    def signed(n):return n-65536 if n&32768 else n
    for step in range(300):
        if pc==0xffffffff:return mem
        word=program[pc];op=word>>26;rs=(word>>21)&31;rt=(word>>16)&31;rd=(word>>11)&31;sh=(word>>6)&31;fn=word&63;im=word&65535
        nextpc=pc+1;oldpending=pending;pending=None
        if op==0:
            if fn==0:reg[rd]=(reg[rt]<<sh)&0xffffffff
            elif fn==2:reg[rd]=reg[rt]>>sh
            elif fn==8:pending=reg[rs]
            elif fn==16:reg[rd]=hi
            elif fn==18:reg[rd]=lo
            elif fn==27:lo,hi=divmod(reg[rs],reg[rt])
            elif fn==33:reg[rd]=(reg[rs]+reg[rt])&0xffffffff
            else:raise ValueError(hex(word))
        elif op==9:reg[rt]=(reg[rs]+signed(im))&0xffffffff
        elif op==11:reg[rt]=int(reg[rs]<(signed(im)&0xffffffff))
        elif op==12:reg[rt]=reg[rs]&im
        elif op in (4,5):
            if (reg[rs]==reg[rt])==(op==4):pending=pc+1+signed(im)
        elif op in (40,41,43):
            size={40:1,41:2,43:4}[op];addr=reg[rs]+signed(im)-0x1000
            mem[addr:addr+size]=(reg[rt]&((1<<(8*size))-1)).to_bytes(size,'little')
        else:raise ValueError(hex(word))
        reg[0]=0;pc=oldpending if oldpending is not None else nextpc
    raise ValueError('Lookup did not return')

def reference(code,layout='dual_plane'):
    if layout=='resident_ui' and 1790<=code<2294:
        plane,index=divmod(code-1790,252)
        row,col=divmod(index,21)
        return (12,16,10,col*12,48+row*16,48,240+plane)
    if layout=='upper13' and 1790<=code<2462:
        plane,index=divmod(code-1790,336)
        return (12,16,13,(index%21)*12,(index//21)*16,48,240+plane)
    if code<320:return (8,16,28,(code%32)*8,(code//32)*16,48,240)
    page,r=divmod(code-110,336);layer=240
    if code>=782:
        page-=2
        if code<1454:layer=241
    if 1790<=code<2126:page-=1;layer=241
    return (12,16,28+page,(r%21)*12,(r//21)*16,48,layer)

def verify(layout='dual_plane'):
    blob,program=assemble(layout)
    count=2294 if layout=='resident_ui' else 2462 if layout=='upper13' else 2136
    for code in range(count):
        m=execute(program,code)
        actual=(int.from_bytes(m[8:10],'little'),int.from_bytes(m[10:12],'little'),int.from_bytes(m[12:14],'little'),m[14],m[15],int.from_bytes(m[16:18],'little'),int.from_bytes(m[18:20],'little'))
        assert actual==reference(code,layout),(code,actual,reference(code,layout))
        assert m[:4]==bytes(4)
    return {'codes_executed':count,'routine_bytes':len(program)*4,'reserved_bytes':len(blob),'original_ranges_preserved':'0..1789','new_range':'1790..2293 -> resident page10, y48..239' if layout=='resident_ui' else '1790..2461 -> upper page13' if layout=='upper13' else '1790..2125 -> third page F1'}

def patch(exe,layout='dual_plane'):
    verify(layout);blob,_=assemble(layout);result=bytearray(exe);off=BASE-EXE_BASE+0x800
    result[off:off+len(blob)]=blob
    return bytes(result)

if __name__=='__main__':print(verify())
