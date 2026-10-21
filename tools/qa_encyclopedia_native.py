#!/usr/bin/env python3
"""Minimal local libretro frontend for screenshot-based PS1 translation QA.

Uses the official PCSX-ReARMed native core and its documented built-in HLE
BIOS. It does not capture the desktop, install an app, or change OS settings.
Input schedule JSON: [{"start": 300,"end": 310,"buttons": ["start"]}, ...]
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2] / 'emulator'
parser = argparse.ArgumentParser()
parser.add_argument('game')
parser.add_argument('--core',default=str(ROOT/'cores/pcsx_rearmed_libretro.dylib'))
parser.add_argument('--frames',type=int,default=1800)
parser.add_argument('--captures',default='60,300,600,900,1200,1800')
parser.add_argument('--schedule')
parser.add_argument('--output',default=str(ROOT/'captures'))
parser.add_argument('--save-state')
parser.add_argument('--load-state')
parser.add_argument('--checkpoint-states',default='',help='Comma-separated frame numbers to save matching-build diagnostic states')
parser.add_argument('--dump-memory',action='store_true',help='Dump exposed libretro RAM/VRAM at the end of the run')
parser.add_argument('--dry-run',action='store_true')
args=parser.parse_args()
capture_frames={int(x) for x in args.captures.split(',') if x}
checkpoint_frames={int(x) for x in args.checkpoint_states.split(',') if x}
schedule=json.loads(Path(args.schedule).read_text()) if args.schedule else []
out=Path(args.output).resolve()
settings={
 'pcsx_rearmed_bios':b'HLE',
 'pcsx_rearmed_region':b'Auto',
 'pcsx_rearmed_show_bios_bootlogo':b'disabled',
 'pcsx_rearmed_drc':b'disabled',
 'pcsx_rearmed_gpu_thread_rendering':b'disabled',
 'pcsx_rearmed_spu_thread':b'disabled',
}
dirs={9:str(ROOT/'system').encode(),31:str(ROOT/'saves').encode(),30:str(ROOT).encode()}
buttons={'b':0,'y':1,'select':2,'start':3,'up':4,'down':5,'left':6,'right':7,'a':8,'x':9,'l':10,'r':11,'l2':12,'r2':13,'l3':14,'r3':15}
if args.dry_run:
 print(json.dumps({'game':str(Path(args.game).resolve()),'core':args.core,'frames':args.frames,'captures':sorted(capture_frames),'checkpoint_states':sorted(checkpoint_frames),'schedule':schedule,'bios':'built-in HLE','output':str(out)},indent=2));raise SystemExit(0)
out.mkdir(parents=True,exist_ok=True)
for b in dirs.values():Path(b.decode()).mkdir(exist_ok=True)
core=C.CDLL(str(Path(args.core).resolve()))
frame=0
pix_fmt=0
last_frame=None
last_raw=None
events=[]
refs=[]
ENV=C.CFUNCTYPE(C.c_bool,C.c_uint,C.c_void_p)
VIDEO=C.CFUNCTYPE(None,C.c_void_p,C.c_uint,C.c_uint,C.c_size_t)
AUDIO=C.CFUNCTYPE(None,C.c_int16,C.c_int16)
AUDIO_BATCH=C.CFUNCTYPE(C.c_size_t,C.POINTER(C.c_int16),C.c_size_t)
INPUT_POLL=C.CFUNCTYPE(None)
INPUT_STATE=C.CFUNCTYPE(C.c_int16,C.c_uint,C.c_uint,C.c_uint,C.c_uint)

class Variable(C.Structure):_fields_=[('key',C.c_char_p),('value',C.c_char_p)]
class SystemInfo(C.Structure):_fields_=[('library_name',C.c_char_p),('library_version',C.c_char_p),('valid_extensions',C.c_char_p),('need_fullpath',C.c_bool),('block_extract',C.c_bool)]
class GameInfo(C.Structure):_fields_=[('path',C.c_char_p),('data',C.c_void_p),('size',C.c_size_t),('meta',C.c_char_p)]

@ENV
def env(cmd,data):
 global pix_fmt
 cmd=cmd&0xffff
 if cmd==10:
  pix_fmt=C.cast(data,C.POINTER(C.c_int))[0];return pix_fmt in (0,1,2)
 if cmd in dirs:
  C.cast(data,C.POINTER(C.c_char_p))[0]=dirs[cmd];return True
 if cmd==15:
  v=C.cast(data,C.POINTER(Variable)).contents
  k=v.key.decode()
  if k in settings:v.value=settings[k];return True
  return False
 if cmd==16:
  v=C.cast(data,C.POINTER(Variable));i=0
  while v[i].key:
   k=v[i].key.decode();raw=v[i].value or b''
   if k not in settings and b'; ' in raw:settings[k]=raw.split(b'; ',1)[1].split(b'|')[0]
   i+=1
  return True
 if cmd==17:
  C.cast(data,C.POINTER(C.c_bool))[0]=False;return True
 if cmd==3:
  C.cast(data,C.POINTER(C.c_bool))[0]=True;return True
 if cmd==51:return True
 if cmd==52:
  C.cast(data,C.POINTER(C.c_uint))[0]=0;return True
 if cmd==39:
  C.cast(data,C.POINTER(C.c_uint))[0]=0;return True
 if cmd==49:
  C.cast(data,C.POINTER(C.c_bool))[0]=True;return True
 if cmd in (1,6,11,18,32,35,37):return True
 return False

def convert(data,w,h,pitch):
 raw=data if isinstance(data,bytes) else C.string_at(data,pitch*h)
 if pix_fmt==1:
  a=np.frombuffer(raw,dtype=np.uint8).reshape(h,pitch)[:,:w*4].reshape(h,w,4)
  return Image.fromarray(a[:,:,[2,1,0]],'RGB')
 a=np.frombuffer(raw,dtype='<u2').reshape(h,pitch//2)[:,:w]
 if pix_fmt==2:r=(a>>11)&31;g=(a>>5)&63;b=a&31;gm=63
 else:r=(a>>10)&31;g=(a>>5)&31;b=a&31;gm=31
 rgb=np.stack([(r.astype(np.uint32)*255//31),(g.astype(np.uint32)*255//gm),(b.astype(np.uint32)*255//31)],axis=-1).astype(np.uint8)
 return Image.fromarray(rgb,'RGB')

@VIDEO
def video(data,w,h,pitch):
 global last_frame,last_raw
 if data and data!=C.c_void_p(-1).value:
  last_raw=(C.string_at(data,pitch*h),w,h,pitch)
 if frame in capture_frames and last_raw:
  raw,w,h,pitch=last_raw
  im=convert(raw,w,h,pitch);p=out/('frame_%06d.png'%frame);im.save(p)
  events.append({'frame':frame,'image':str(p),'width':w,'height':h,'pixel_format':pix_fmt,'nonzero':bool(np.asarray(im).any())})
  print('CAPTURE',frame,w,h,flush=True)
  last_frame=im

@AUDIO
def audio(l,r):pass
@AUDIO_BATCH
def audio_batch(data,n):return n
@INPUT_POLL
def poll():pass
@INPUT_STATE
def inp(port,device,index,ident):
 if port!=0 or device!=1:return 0
 active=set()
 for row in schedule:
  if row['start']<=frame<=row['end']:active.update(buttons[b] for b in row['buttons'])
 if ident==256:return sum(1<<b for b in active)
 return int(ident in active)

for name,fn in [('environment',env),('video_refresh',video),('audio_sample',audio),('audio_sample_batch',audio_batch),('input_poll',poll),('input_state',inp)]:
 f=getattr(core,'retro_set_'+name);f.argtypes=[type(fn)];f(fn);refs.append(fn)
core.retro_api_version.restype=C.c_uint
core.retro_init.argtypes=[];core.retro_init()
si=SystemInfo();core.retro_get_system_info.argtypes=[C.POINTER(SystemInfo)];core.retro_get_system_info(C.byref(si))
print('CORE',si.library_name,si.library_version,'fullpath',si.need_fullpath,flush=True)
path=str(Path(args.game).resolve()).encode();content=None
if not si.need_fullpath:
 blob=Path(args.game).read_bytes();content=C.create_string_buffer(blob)
gi=GameInfo(path,C.cast(content,C.c_void_p) if content else None,len(blob) if content else 0,None)
core.retro_load_game.argtypes=[C.POINTER(GameInfo)];core.retro_load_game.restype=C.c_bool
assert core.retro_load_game(C.byref(gi)),'retro_load_game failed'
core.retro_set_controller_port_device.argtypes=[C.c_uint,C.c_uint];core.retro_set_controller_port_device(0,1)
core.retro_serialize_size.restype=C.c_size_t
if args.load_state:
 state=Path(args.load_state).read_bytes();buf=C.create_string_buffer(state)
 core.retro_unserialize.argtypes=[C.c_void_p,C.c_size_t];core.retro_unserialize.restype=C.c_bool
 assert core.retro_unserialize(buf,len(state)),'state restore failed'

# Controlled RAM-only diagnostic: call the game's native encyclopedia resource
# loader, bypassing only the fresh-card menu gate; no image/save is changed.
import os,struct as TS
core.retro_get_memory_data.argtypes=[C.c_uint];core.retro_get_memory_data.restype=C.c_void_p
ram_ptr=core.retro_get_memory_data(2);assert ram_ptr
ram=(C.c_ubyte*0x200000).from_address(ram_ptr)
regs=(C.c_uint32*210).in_dll(core,'psxRegs')
print('NATIVE_ENTRY_PC',hex(regs[130]),'SP',hex(regs[29]),'GP',hex(regs[28]),flush=True)
assert 0x80000000<=regs[130]<0xc0000000
old_table=bytes.fromhex('3000f000100004003000f000100002002001f00010000200c001000120000001')
width_only=bytearray(old_table);TS.pack_into('<H',width_only,12,32)
self_copy=bytearray(width_only);TS.pack_into('<H',self_copy,16,48);TS.pack_into('<H',self_copy,20,32)
dark_copy=bytearray(self_copy);TS.pack_into('<H',dark_copy,18,250)
assert bytes(ram[0x10f40:0x10f60]) in (old_table,width_only,self_copy,dark_copy)
fixed=os.environ.get('STT_ENCYC_FIX')=='1'
ram[0x10f40:0x10f60]=old_table # private RAM baseline control on either build
if fixed:
 table=bytearray(old_table);TS.pack_into('<H',table,12,32);TS.pack_into('<H',table,16,48);TS.pack_into('<H',table,20,32);TS.pack_into('<H',table,18,250)
 ram[0x10f40:0x10f60]=table
if fixed and os.environ.get('STT_ENCYC_DARK_PATCH')=='1':
 # Make this old-base RAM TIM upload exactly match the final BATTLE538-only
 # palette change. The native loader still parses/uploads the modified TIM.
 assert TS.unpack('<I',bytes(ram[0x5c8a4:0x5c8a8]))[0]==0x3c048018
 values=[]
 for subrow in range(2):
  for bank in range(2):
   plane=subrow+bank*2
   values += [0x94a5 if i&(1<<plane) else 0 for i in range(16)]
 words=TS.unpack('<32I',TS.pack('<64H',*values))
 program=[0x3c048018,0x3484e800,0x3c088018,0x3508ea94]
 for i,w in enumerate(words):
  program += [0x3c090000|(w>>16),0x35290000|(w&65535),0xad090000|(i*4)]
 program += [0x08000000|((0x8005c8ac>>2)&0x3ffffff),0]
 blob=TS.pack('<%dI'%len(program),*program)
 ram[0x1fc000:0x1fc000+len(blob)]=blob
 for i,value in enumerate(TS.pack('<I',0x08000000|((0x801fc000>>2)&0x3ffffff))):ram[0x5c8a4+i]=value
 print('NATIVE_DARK_TIM_BUFFER_STUB',len(blob),flush=True)
stop=0x801fd000
for addr,word in [(stop,0x08000000|((stop>>2)&0x3ffffff)),(stop+4,0),(0x8005c9d8,0x08000000|((stop>>2)&0x3ffffff))]:
 for i,value in enumerate(TS.pack('<I',word)):ram[(addr&0x1fffff)+i]=value
regs[46]=(regs[46]&~15)|((regs[46]>>2)&15) # finish saved IRQ's RFE status restoration
if os.environ.get('STT_ENCYC_RENDER')=='1':
 # Invoke the ordinary menu/resource function for menu8, which maps to
 # encyclopedia item52; return to the saved VSync context afterward.
 for i,value in enumerate(TS.pack('<I',0x24040006)):ram[0x5c9d8+i]=value
 regs[31]=regs[48];regs[4]=8;regs[5]=0;regs[6]=0;regs[130]=0x8005c5b0
else:
 regs[29]=0x801fff00;regs[31]=stop;regs[130]=0x8005c728
print('NATIVE_LOADER_REDIRECT','fixed',fixed,flush=True)

t=time.monotonic()
checkpoint_events=[]
def save_state_to(destination):
 n=core.retro_serialize_size();buf=C.create_string_buffer(n)
 core.retro_serialize.argtypes=[C.c_void_p,C.c_size_t];core.retro_serialize.restype=C.c_bool
 assert core.retro_serialize(buf,n),'state save failed'
 Path(destination).write_bytes(buf.raw)
for frame in range(1,args.frames+1):
 core.retro_run()
 if frame in checkpoint_frames:
  checkpoint=out/('frame_%06d.state'%frame);save_state_to(checkpoint)
  checkpoint_events.append({'frame':frame,'state':str(checkpoint)})
  print('CHECKPOINT',frame,str(checkpoint),flush=True)
print('NATIVE_EXIT_PC',hex(regs[130]),'SP',hex(regs[29]),flush=True)
if args.save_state:save_state_to(args.save_state)
if args.dump_memory:
 core.retro_get_memory_size.argtypes=[C.c_uint];core.retro_get_memory_size.restype=C.c_size_t
 core.retro_get_memory_data.argtypes=[C.c_uint];core.retro_get_memory_data.restype=C.c_void_p
 for ident,label in [(0,'save_ram'),(1,'rtc'),(2,'system_ram'),(3,'video_ram')]:
  n=core.retro_get_memory_size(ident);ptr=core.retro_get_memory_data(ident)
  if ptr and n:
   p=out/(label+'.bin');p.write_bytes(C.string_at(ptr,n));print('MEMORY',ident,label,n,str(p),flush=True)
  else:print('MEMORY_UNAVAILABLE',ident,label,n,flush=True)
core.retro_unload_game();core.retro_deinit()
report={'core':si.library_name.decode(),'version':si.library_version.decode(),'game':path.decode(),'frames':args.frames,'seconds':round(time.monotonic()-t,2),'bios':'HLE','settings':{k:v.decode() for k,v in settings.items()},'captures':events,'checkpoint_states':checkpoint_events}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print('DONE',json.dumps({'frames':args.frames,'seconds':report['seconds'],'captures':len(events)}),flush=True)
