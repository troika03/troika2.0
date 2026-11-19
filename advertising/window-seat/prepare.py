"""Prepare voice-driven cuts, a sparse electronic score and the stereo master."""
from pathlib import Path
import json
import math
import subprocess
import numpy as np
from scipy.io import wavfile

root = Path(__file__).resolve().parent
local = root/'local'
local.mkdir(exist_ok=True)
sr = 48000
def decode(file):
    raw = subprocess.check_output(['ffmpeg','-v','error','-i',str(file),'-ac','1','-ar',str(sr),'-f','f32le','-'])
    return np.frombuffer(raw,np.float32)
voices = []
for path in sorted((root/'audio').glob('*.mp3')):
    raw = decode(path)
    audible = np.flatnonzero(np.abs(raw) > .007)
    start = max(0,audible[0]-int(.065*sr))
    end = min(len(raw),audible[-1]+int(.12*sr))
    line = raw[start:end].copy()
    line *= min(.9/np.max(np.abs(line)), .18/np.sqrt(np.mean(line[np.abs(line)>.018]**2)))
    voices.append(line)
assert len(voices)==12
pauses = [.25,.50,.53,.35,.56,.64,.28,.65,.61,.44,.70,.7]
starts = []
cursor = .22
for voice,pause in zip(voices,pauses):
    starts.append(round(cursor,3))
    cursor += len(voice)/sr + pause
duration = math.ceil((cursor+.35)*30)/30
times = np.arange(round(duration*sr))/sr
score = np.zeros((len(times),2))
dialogue = np.zeros(len(times))
def put(t,signal,pan=0):
    a=round(t*sr)
    n=min(len(signal),len(score)-a)
    if n>0:
        score[a:a+n] += signal[:n,None]*np.sqrt([(1-pan)/2,(1+pan)/2])
def note(t,hz,vol,decay,pan):
    x=np.arange(int(5*decay*sr))/sr
    tone=np.sin(2*np.pi*hz*x)+.27*np.sin(4*np.pi*hz*x)*np.exp(-9*x)
    put(t,vol*tone*np.exp(-x/decay)*(1-np.exp(-x/.008)),pan)
beat=.51
for i in range(math.ceil(duration/beat)):
    t=i*beat
    base=[55,46.25,51.913,41.203][(i//8)%4]
    if i%4==0: note(t,base,.12,.24,-.06)
    if i%4 in (1,3): note(t,base*[6,8,9,10][i//2%4],.043,.14,.3*(-1)**(i//2))
    if i%2==0:
        x=np.arange(int(.14*sr))/sr
        put(t,.07*np.sin(2*np.pi*(48*x+1.5*(1-np.exp(-x/.018))))*np.exp(-25*x),0)
duck=np.interp(times,[0,.15,starts[7],starts[8]-.25,starts[9],starts[10],starts[11],duration-.7,duration],[0,.82,.8,.15,.24,.62,.95,.85,0])
score *= duck[:,None]
for cue,hz in [(.015,660),(.105,880),(starts[2],520),(starts[5],620),(starts[8],784),(starts[11],660)]:
    note(cue,hz,.08,.075,.18)
for start,voice in zip(starts,voices):
    a=round(start*sr)
    dialogue[a:a+len(voice)] += voice
mix=score+dialogue[:,None]*.86
wavfile.write(local/'premix.wav',sr,np.int16(np.clip(mix,-.995,.995)*32767))
subprocess.run(['ffmpeg','-y','-v','error','-i',str(local/'premix.wav'),'-af','loudnorm=I=-16:TP=-1.8:LRA=7','-ar',str(sr),str(local/'mix.wav')],check=True)
story=json.loads((root/'story.json').read_text('utf-8'))+[['user','Ссылка в шапке профиля.']]
cuts=dict(starts=starts, lengths=[round(len(x)/sr,3) for x in voices], duration=duration, story=story)
(local/'cuts.js').write_text('window.cut='+json.dumps(cuts,ensure_ascii=False)+';',encoding='utf-8')
print(json.dumps({k:cuts[k] for k in ('starts','lengths','duration')}))
