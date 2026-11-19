"""Build the OBSION portrait cut from the shared series renderer."""
import argparse
import json
import math
import re
import subprocess
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

root = Path(__file__).resolve().parent
local = root / 'local'
local.mkdir(exist_ok=True)
parser = argparse.ArgumentParser()
parser.add_argument('--preview', action='store_true')
parser.add_argument('--voice', type=Path)
parser.add_argument('--starts', type=Path, help='JSON array of line start times from the WAV')
args = parser.parse_args()
lines = json.loads((root / 'story.json').read_text('utf-8'))
duration = 27.8
if args.voice:
    length = subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(args.voice)],text=True)
    duration = math.ceil((float(length) + .42) * 30) / 30
    if args.starts is None:
        parser.error('Provide verified line start times with --starts')
    starts = json.loads(args.starts.read_text('utf-8'))
    assert len(starts) == len(lines) and starts == sorted(starts) and starts[-1] < duration
    for line, start in zip(lines, starts):
        line[0] = start
svg = (root/'assets/reminders.svg').read_text('utf-8')
svg = re.sub(r'<style>.*?</style>', '', svg, flags=re.S).replace('font-family="Golos Text"', 'font-family="Golos"')
data = dict(lines=lines, duration=duration, reminder=svg)
(root/'timing.js').write_text('window.film = '+json.dumps(data,ensure_ascii=False)+';',encoding='utf-8')
spec = spec_from_file_location('portrait', root.parent/'six-drafts/render.py')
renderer = module_from_spec(spec)
spec.loader.exec_module(renderer)
renderer.root, renderer.local = root, local
if args.preview:
    renderer.section(('preview', [int(t*30) for t in (0,1.7,4,9,11.99,14.3,17,19.8,22,26.5)], False))
    renderer.sheet()
    raise SystemExit
renderer.section(('visual',range(round(duration*30)),True))
music = root/'assets/music.mp3'
inputs = ['-i',str(local/'part-visual.mp4'),'-i',str(music)]
audio = f'[1:a]atrim=duration={duration},volume=0.62,afade=t=out:st={duration-.65}:d=0.65[bed]'
label = '[bed]'
if args.voice:
    inputs += ['-i', str(args.voice)]
    audio += ';[2:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=1.4[voice];[bed][voice]amix=inputs=2:normalize=0:duration=longest,loudnorm=I=-16:TP=-1.5:LRA=7[out]'
    label = '[out]'
name = 'Я создал своего Джарвиса' + (' — Gemini' if args.voice else ' — монтаж') + '.mp4'
subprocess.run(['ffmpeg','-y','-v','error',*inputs,'-filter_complex',audio,'-map','0:v','-map',label,'-c:v','copy','-c:a','aac','-ar','48000','-ac','2','-b:a','224k','-t',str(duration),'-movflags','+faststart',str(root/name)],check=True)
print(name,flush=True)
