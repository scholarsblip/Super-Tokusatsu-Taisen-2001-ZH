#!/usr/bin/env python3
"""Private copy of the HLE frontend for reproducible intro-video recording.

Uses the official PCSX-ReARMed native core and its documented built-in HLE
BIOS. It does not capture the desktop, install an app, or change OS settings.
Input schedule JSON: [{"start": 300,"end": 310,"buttons": ["start"]}, ...]
"""
import argparse
import ctypes as C
import hashlib
import json
from pathlib import Path
from fractions import Fraction
import re
import sys
import time

import numpy as np
from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
ROOT = PROJECT.parent/'emulator'
sys.path.insert(0,str(PROJECT/'tools/movie_runtime/pythonlib'))
import av
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
parser.add_argument('--record-video',type=Path)
parser.add_argument('--record-fps',type=int,choices=(12,15,20,30,60),default=12)
parser.add_argument('--record-start',type=int,default=1)
parser.add_argument('--record-end',type=int)
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
dirs={9:str(ROOT/'system').encode(),31:str(out/'saves').encode(),30:str(out).encode()}
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
record_container=None
record_stream=None
record_count=0
record_last_frame=-1
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
 global last_frame,last_raw,record_container,record_stream,record_count,record_last_frame
 if data and data!=C.c_void_p(-1).value:
  last_raw=(C.string_at(data,pitch*h),w,h,pitch)
 if args.record_video and last_raw and frame!=record_last_frame and frame>=args.record_start and (args.record_end is None or frame<=args.record_end) and (frame-args.record_start)%(60//args.record_fps)==0:
  raw,rw,rh,rpitch=last_raw
  image=convert(raw,rw,rh,rpitch)
  if record_container is None:
   args.record_video.parent.mkdir(parents=True,exist_ok=True)
   record_container=av.open(str(args.record_video),'w',options={'movflags':'+faststart'})
   record_stream=record_container.add_stream('libx264',rate=args.record_fps)
   record_stream.width=rw;record_stream.height=rh;record_stream.pix_fmt='yuv420p'
   record_stream.options={'crf':'12','preset':'fast'}
  assert (rw,rh)==(record_stream.width,record_stream.height),'Native recording dimensions changed'
  encoded=av.VideoFrame.from_image(image);encoded.pts=record_count;encoded.time_base=Fraction(1,args.record_fps)
  for packet in record_stream.encode(encoded):record_container.mux(packet)
  record_count+=1;record_last_frame=frame
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
if record_container:
 for packet in record_stream.encode(None):record_container.mux(packet)
 record_container.close()
report={'core':si.library_name.decode(),'version':si.library_version.decode(),'game':path.decode(),'frames':args.frames,'seconds':round(time.monotonic()-t,2),'bios':'HLE','settings':{k:v.decode() for k,v in settings.items()},'captures':events,'checkpoint_states':checkpoint_events}
if args.record_video:
 components=[Path(args.game).resolve()]
 if components[0].suffix.lower()=='.cue':
  components+=[(components[0].parent/name).resolve() for name in re.findall(r'^\s*FILE\s+"([^"]+)"',components[0].read_text(),re.M|re.I)]
 def sha(p):
  with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
 report['recording']={'path':str(args.record_video.resolve()),'sha256':sha(args.record_video),
  'frames':record_count,'fps':args.record_fps,'emulation_fps':60,'start_emulation_frame':args.record_start,
  'end_emulation_frame':record_last_frame,'native_width':record_stream.width,'native_height':record_stream.height,
  'game_components_sha256':{str(p):sha(p) for p in components},
  'loaded_matching_build_state':str(Path(args.load_state).resolve()) if args.load_state else None,
  'loaded_state_sha256':sha(Path(args.load_state)) if args.load_state else None,
  'input_schedule':schedule,'frontend_sha256':sha(Path(__file__))}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print('DONE',json.dumps({'frames':args.frames,'seconds':report['seconds'],'captures':len(events)}),flush=True)
