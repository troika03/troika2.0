"""Export the portrait GSAP composition at 30 fps."""
from pathlib import Path
from importlib.util import module_from_spec, spec_from_file_location
import argparse
import json
import subprocess

root=Path(__file__).resolve().parent
local=root/'local'
parser=argparse.ArgumentParser()
parser.add_argument('--preview',action='store_true')
args=parser.parse_args()
spec=spec_from_file_location('series',root.parent/'six-drafts/render.py')
renderer=module_from_spec(spec)
spec.loader.exec_module(renderer)
renderer.root,renderer.local=root,local
cut=json.loads((local/'cuts.js').read_text('utf-8').split('=',1)[1].strip().rstrip(';'))
if args.preview:
    frames=[0]+[round((s+min(1.0,d*.65))*30) for s,d in zip(cut['starts'],cut['lengths'])]
    renderer.section(('preview',frames,False))
    renderer.sheet()
else:
    renderer.section(('film',range(round(cut['duration']*30)),True))
    subprocess.run(['ffmpeg','-y','-v','error','-i',str(local/'part-film.mp4'),'-i',str(local/'mix.wav'),
        '-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-ar','48000','-ac','2','-b:a','224k',
        '-movflags','+faststart','-t',str(cut['duration']),str(root/'Тройка — Место у окна.mp4')],check=True)
