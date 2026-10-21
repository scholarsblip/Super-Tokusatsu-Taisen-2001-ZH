#!/usr/bin/env python3
"""Cold-boot first-battle capture using the existing native HLE frontend.

Read-only plan unless --write is supplied. This replays the verified METAL
opening, moves the selected hero one tile up, selects the first weapon and
attacks the enemy to the left. It never loads a state from another build.
Captured frames still require visual review; a run alone is not a QA pass.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
EMU=ROOT.parent/'emulator'
TAIL=[(80030,'up'),(80090,'a'),(80400,'a'),(80640,'a'),
      (80880,'left'),(80940,'a'),(81200,'a')]
CAPTURES=[3000,5800,16800,18000,38400,40000,44000,48000,56000,
          80000,80380,80560,80780,81080,81600,81800,82100,82500,85000]
CHECKPOINTS=[5800,40000,56000,80560,81080,81800,82500]


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--game',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--write',action='store_true')
    a=p.parse_args()
    game=a.game.resolve();out=a.output.resolve()
    schedule=json.loads((EMU/'advance_metal_80000.json').read_text())
    assert max(r['end'] for r in schedule)<80000
    schedule += [{'start':f,'end':f+6,'buttons':[b]} for f,b in TAIL]
    plan={'mode':'write' if a.write else 'dry_run','game':str(game),'output':str(out),
          'bios':'PCSX-ReARMed built-in HLE','frames':85000,'cold_boot':True,
          'cross_build_state_loaded':False,'schedule_rows':len(schedule),
          'battle_tail':schedule[-len(TAIL):],'captures':CAPTURES,
          'checkpoint_states':CHECKPOINTS}
    print(json.dumps(plan,indent=2),flush=True)
    if not a.write:return
    if out.exists() and any(out.iterdir()):raise FileExistsError(out)
    out.mkdir(parents=True,exist_ok=True)
    (out/'input_schedule.json').write_text(json.dumps(schedule,indent=1)+'\n')
    (out/'qa_plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    cmd=[sys.executable,'-B',str(EMU/'run_psx_headless.py'),str(game),
         '--frames','85000','--captures',','.join(map(str,CAPTURES)),
         '--schedule',str(out/'input_schedule.json'),'--output',str(out),
         '--save-state',str(out/'end.state'),'--dump-memory',
         '--checkpoint-states',','.join(map(str,CHECKPOINTS))]
    result=subprocess.run(cmd,check=False)
    game_files=[game]
    if game.suffix.lower()=='.cue':
        for name in re.findall(r'^\s*FILE\s+"([^"]+)"',game.read_text(),re.M|re.I):
            game_files.append((game.parent/name).resolve())
    report={'status':'captured_unreviewed' if result.returncode==0 else 'runner_failed',
            'return_code':result.returncode,'game_file_sha256':digest(game),
            'game_components_sha256':{str(p):digest(p) for p in game_files},
            'input_schedule_sha256':digest(out/'input_schedule.json'),
            'cold_boot':True,'cross_build_state_loaded':False,
            'review_required':['Weapon list labels and values','Prebattle status/menu',
                               'Battle speaker and dialogue','Portrait and glyph integrity',
                               'Damage/result and return to map']}
    (out/'battle_qa_manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(result.returncode)


if __name__=='__main__':main()
