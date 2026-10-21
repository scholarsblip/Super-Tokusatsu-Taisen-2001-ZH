"""Extend native copy/concat/measure helpers to accept custom Chinese codes.

The source uses SLTIU immediate1454 as a printable-character bound. The new
bound8192 covers every sparse custom atlas code and still excludes FFxx
control/terminator words. FF00 must not be used as an SLTIU immediate: MIPS
sign extension would make that comparison accept every16bit terminator.
"""
import struct

EXE_BASE=0x80010000
THRESHOLD=0x2000
PATCHES=[
    (0x8004d4c0,3,'copy first'),(0x8004d4e0,3,'copy loop'),
    (0x8004d50c,2,'concat destination first'),(0x8004d524,2,'concat destination loop'),
    (0x8004d538,3,'concat source first'),(0x8004d558,3,'concat source loop'),
    (0x8004d7e4,3,'measure first'),(0x8004d81c,3,'measure loop'),
]


def patch(exe):
    result=bytearray(exe)
    for addr,source,kind in PATCHES:
        offset=addr-EXE_BASE+0x800;word=struct.unpack_from('<I',result,offset)[0]
        prefix=(11<<26)|(source<<21)|(2<<16)
        assert word in (prefix|1454,prefix|THRESHOLD),(hex(addr),kind,hex(word))
        struct.pack_into('<I',result,offset,prefix|THRESHOLD)
    verify(bytes(result))
    return bytes(result)


def _run(exe,entry,source,destination=()):
    """Independent bounded R3000 interpreter for the three exact helpers."""
    reg=[0]*32;reg[4]=0x3000;reg[5]=0x2000;reg[31]=0xffffffff
    memory={};pc=entry;pending=None
    def write(addr,value):memory[addr]=value&255;memory[addr+1]=(value>>8)&255
    def read(addr):return memory.get(addr,0)|(memory.get(addr+1,0)<<8)
    for i,w in enumerate(source):write(0x2000+i*2,w)
    for i,w in enumerate(destination):write(0x3000+i*2,w)
    if entry==0x8004d7dc:reg[4]=0x2000
    def signed16(n):return n-65536 if n&32768 else n
    def signed32(n):return n-0x100000000 if n&0x80000000 else n
    for steps in range(2000):
        if pc==0xffffffff:return reg[2],[read(0x3000+i*2) for i in range(len(source)+len(destination)+2)]
        word=struct.unpack_from('<I',exe,pc-EXE_BASE+0x800)[0]
        op=word>>26;rs=(word>>21)&31;rt=(word>>16)&31;rd=(word>>11)&31;sh=(word>>6)&31;fn=word&63;im=word&65535
        nextpc=pc+4;old=pending;pending=None
        if op==0:
            if fn==0:reg[rd]=(reg[rt]<<sh)&0xffffffff
            elif fn==3:reg[rd]=(signed32(reg[rt])>>sh)&0xffffffff
            elif fn==8:pending=reg[rs]
            elif fn==33:reg[rd]=(reg[rs]+reg[rt])&0xffffffff
            else:raise ValueError(hex(word))
        elif op==9:reg[rt]=(reg[rs]+signed16(im))&0xffffffff
        elif op==11:reg[rt]=int(reg[rs]<(signed16(im)&0xffffffff))
        elif op==37:reg[rt]=read(reg[rs]+signed16(im))
        elif op==41:write(reg[rs]+signed16(im),reg[rt])
        elif op in (4,5):
            if (reg[rs]==reg[rt])==(op==4):pending=pc+4+signed16(im)*4
        elif op==2:pending=((pc+4)&0xf0000000)|((word&0x3ffffff)<<2)
        else:raise ValueError(hex(word))
        reg[0]=0;pc=old if old is not None else nextpc
    raise ValueError('Native text helper did not terminate')


def verify(exe):
    samples=[[224,0x1140,0x17f6,0x1ff6,0xfffe],[0xfffe],[1118,1123,0xff05]]
    checks=0
    for source in samples:
        count,target=_run(exe,0x8004d4b8,source)
        assert target[:len(source)]==source and count==len(source)-1
        checks+=1
        dest=[225,0x1141,0xfffe]
        count,target=_run(exe,0x8004d504,source,dest)
        expected=dest[:-1]+source
        assert target[:len(expected)]==expected and count==len(expected)-1
        checks+=1
        count,_=_run(exe,0x8004d7dc,source)
        assert count==sum(8 if w<320 else 12 for w in source[:-1])
        checks+=1
    return {'status':'pass','interpreter_checks':checks,'threshold':THRESHOLD,
            'comparisons_patched':len(PATCHES),'copy_concat_terminators_preserved':True,
            'measure_uses_conservative_12px_wide_advance':True,
            'addresses':[hex(x[0]) for x in PATCHES]}
