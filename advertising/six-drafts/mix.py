"""Build the original instrumental bed and stereo master, with the dialogue in front."""
from pathlib import Path
import subprocess
import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

root = Path(__file__).resolve().parent / 'local'
sr = 48000
dur = 24
rng = np.random.default_rng(310)
bed, dialogue, fx = [np.zeros((sr*dur,2)) for _ in range(3)]
def place(track,t,signal,pan=0):
    offset = round(sr*t)
    limit = min(len(signal),len(track)-offset)
    if limit > 0:
        track[offset:offset+limit] += signal[:limit,None] * np.sqrt([(1-pan)/2,(1+pan)/2])
def times(d): return np.arange(round(sr*d))/sr
def filtered_noise(x,band):
    return sosfilt(butter(3,band,btype='bandpass',fs=sr,output='sos'),rng.normal(0,1,len(x)))
def pluck(start,midi,vol,pan,decay):
    f=440*2**((midi-69)/12)
    t=times(decay*5)
    tone=sum(np.sin(2*np.pi*f*h*t+.09*h)*np.exp(-t*h*.72/decay)/h**1.45 for h in (1,2,3,4,6))
    s=vol*tone*np.exp(-t/decay)*(1-np.exp(-t/.009))
    place(bed,start,s,pan);place(bed,start+.195,s*.18,-pan)
def percussion(start,part,gain):
    t=times(.38)
    if part=='kick':
        s=np.sin(2*np.pi*(46*t+1.36*(1-np.exp(-t/.027))))*np.exp(-t/.094)
    else:
        s=filtered_noise(t,[650,4300] if part=='rim' else [6400,10800])*np.exp(-t/(.034 if part=='rim' else .023))
    place(bed,start,gain*s*(1-np.exp(-t/.002)),.18 if part=='hat' else -.1)
# Sparse electric-piano motif, brushed percussion and a warm low end.
beat=.625
chords=[(50,57,64,66),(47,54,61,62),(43,50,57,59),(45,52,59,61)]
for bar in range(9):
    origin=bar*4*beat
    c=chords[bar%4]
    for step,n,v in [(0,1,.075),(.51,2,.045),(1.52,3,.064),(2.99,2,.039)]:
        pluck(origin+beat*step+.025,c[n]+12,v,(-1)**n*.36,.36)
    for n in [0,2.48]:
        pluck(origin+beat*n,c[0]-12,.15,-.06,.32)
        percussion(origin+beat*n,'kick',.16)
    for n in [1.01,3.015]: percussion(origin+beat*n,'rim',.1)
    for n in [.50,1.53,2.53,3.49]: percussion(origin+beat*n,'hat',.039)
clock=times(dur)
bed *= np.interp(clock,[0,.18,8.78,9.19,10.33,10.9,12.31,12.62,15.1,15.9,17.3,19.32,19.53,21.4,23.99],
 [0,1,.82,.57,.47,.10,.13,.41,.39,.7,.53,.5,1.12,.96,0])[:,None]
for i,start in enumerate([.42,5.24,9.17,12.34,17.54]):
    buf=subprocess.check_output(['ffmpeg','-v','error','-i',str(root/'voices'/f'line-{i}.mp3'),'-f','f32le','-ac','1','-ar',str(sr),'-'])
    s=np.frombuffer(buf,np.float32).astype(float)
    active=s[np.abs(s)>.014]
    s*=min(.88/max(abs(s)),.20/max(np.sqrt(np.mean(active**2)),.001))
    place(dialogue,start,s,-.055 if i%2==0 else .07)
    # Very short reflection adds space without smearing words.
    place(dialogue,start+.043,s*.035,.53 if i%2==0 else -.48)
def touch(t,gain=.04):
    x=times(.065)
    place(fx,t,gain*(filtered_noise(x,[900,4400])+np.sin(2*np.pi*450*x)*.3)*np.exp(-x/.013),.22)
for start in [.38,2.43,5.27,9.2,12.36]:touch(start)
for start in [16.58,16.78,16.93,17.85,18.14,18.31,18.61,18.82]:touch(start,.032)
for start,f,vol in [(19.26,583,.11),(19.34,874,.09)]:
    t=times(.43);s=vol*(np.sin(2*np.pi*f*t)+.11*np.sin(4*np.pi*f*t))*(1-np.exp(-t/.011))*np.exp(-t/.085)
    place(fx,start,s,.14)
total=bed+dialogue+fx
wavfile.write(root/'premix.wav',sr,np.asarray(np.clip(total,-1,1)*32767,dtype=np.int16))
subprocess.run(['ffmpeg','-y','-v','error','-i',str(root/'premix.wav'),'-af','loudnorm=I=-16:TP=-1.5:LRA=8','-ar',str(sr),'-c:a','pcm_s16le',str(root/'mix.wav')],check=True)
