"""Place the Russian takes, synchronise captions and mix the glass percussion score."""
import json
import subprocess
from pathlib import Path
import numpy as np
from scipy.io import wavfile

root = Path(__file__).resolve().parent
local = root/'local'
local.mkdir(exist_ok=True)
story = json.loads((root/'story.json').read_text('utf-8'))
sr = 48000
frames = 1304
duration = frames/30
times = np.arange(round(duration*sr))/sr
speech = np.zeros(len(times))
music = np.zeros((len(times),2))
captions = []
starts = [round(s[0]*30)/30 for s in story]

def place(t, a, pan=0):
    start = round(t*sr)
    count = min(len(a),len(music)-start)
    if count>0:
        music[start:start+count] += a[:count,None]*np.sqrt([(1-pan)/2,(1+pan)/2])

def bell(t,hz,level,decay,pan=0):
    x=np.arange(round((decay*6+.01)*sr))/sr
    attack=1-np.exp(-x/.003)
    sound=(np.sin(2*np.pi*hz*x)+.23*np.sin(2*np.pi*hz*2.72*x)*np.exp(-12*x))
    place(t,level*sound*attack*np.exp(-x/decay),pan)

# 111 BPM, low sine bass and sparse glass notes with small stereo echoes.
rng=np.random.default_rng(811)
beat=60/111
for n in range(int(duration/beat)+1):
    t=n*beat
    bass=[55,43.654,51.913,48.999][n//8%4]
    if n%2==0:
        x=np.arange(round(.27*sr))/sr
        place(t,.105*np.exp(-18*x)*np.sin(2*np.pi*(46*x+.94*(1-np.exp(-x/.024)))),0)
    if n%4==0: bell(t+.025,bass,.105,.31,-.03)
    if n%4 in (1,3):
        hz=bass*[8,10,12,15][(n//2)%4]
        bell(t+.012,hz,.033,.135,.4*(-1)**(n//2))
        bell(t+.207,hz,.009,.14,-.45*(-1)**(n//2))
    x=np.arange(round(.066*sr))/sr
    hiss=np.diff(rng.normal(0,.008,len(x)+1))*np.exp(-73*x)
    place(t+beat/2,hiss,.3*(-1)**n)
for i,t in enumerate(starts):
    bell(t+.02,[550,660,784,880][i%4],.08,.115,-.16)
    if i in (0,4,7):bell(t+.14,1100,.039,.18,.32)
for i,offset in [(1,1.15),(1,1.81),(2,2.16),(3,3.05),(4,1.45),(5,1.79),(6,1.22),(6,1.89),(6,2.56),(7,1.65)]:
    bell(starts[i]+offset,930,.049,.061,.12)
for i,(_,lines) in enumerate(story):
    data = subprocess.check_output(['ffmpeg','-v','error','-i',str(local/f'voices/chapter-{i}.mp3'),'-ar',str(sr),'-ac','1','-f','f32le','-'])
    raw = np.frombuffer(data,'<f4')
    active = np.flatnonzero(abs(raw)>.008)
    if not len(active): raise ValueError(f'Empty voice {i}')
    take = raw[max(0,active[0]-int(.03*sr)):min(len(raw),active[-1]+int(.08*sr))].copy()
    take *= min(.90/np.max(np.abs(take)), .175/np.sqrt(np.mean(take[abs(take)>.02]**2)))
    t=starts[i]+.16
    pos=round(t*sr)
    assert t+len(take)/sr < (starts+[duration])[i+1], 'Voice overlaps next chapter'
    speech[pos:pos+len(take)]=take
    windows=take[:len(take)//480*480].reshape(-1,480)
    energies=np.sqrt(np.mean(windows**2,axis=1))
    weights=np.array([len(line.replace(' ','')) for line in lines],float)
    fractions=np.cumsum(weights)/sum(weights)
    captions.append([starts[i],lines[0]])
    for j,fraction in enumerate(fractions[:-1]):
        guess=fraction*len(energies)
        candidates=np.arange(max(2,int(guess-17)),min(len(energies)-2,int(guess+17)))
        cost=energies[candidates]+abs(candidates-guess)*.00065
        boundary=candidates[np.argmin(cost)]/100
        captions.append([round(t+boundary,3),lines[j+1]])
mix=music*np.interp(times,[0,.08,duration-.55,duration],[.25,1,1,0])[:,None]+speech[:,None]
wavfile.write(local/'premix.wav',sr,(mix.clip(-.999,.999)*32767).astype(np.int16))
subprocess.run(['ffmpeg','-y','-v','error','-i',str(local/'premix.wav'),'-af','loudnorm=I=-16:TP=-1.6:LRA=7','-ar',str(sr),str(local/'mix.wav')],check=True)
(local/'cuts.js').write_text('window.cut='+json.dumps(dict(duration=duration,starts=starts,caps=captions),ensure_ascii=False)+';',encoding='utf-8')
print('Prepared',frames,'frames and',len(captions),'captions')
