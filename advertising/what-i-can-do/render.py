"""Render staged Android/Windows scenes. The review copy has music and full captions."""
import argparse
from importlib.util import spec_from_file_location,module_from_spec
from pathlib import Path
import subprocess
import numpy as np
from scipy.io import wavfile

root=Path(__file__).resolve().parent
local=root/'local'
spec=spec_from_file_location('commercial_renderer',root.parent/'six-drafts/render.py')
renderer=module_from_spec(spec)
spec.loader.exec_module(renderer)
renderer.root=root
renderer.local=local

def music():
    rate=24000
    track=np.zeros((84*rate,2),dtype=np.float32)
    rng=np.random.default_rng(71)
    def put(start,x,pan):
        i=int(start*rate); n=min(len(x),len(track)-i)
        if n>0: track[i:i+n]+=x[:n,None]*np.sqrt([(1-pan)/2,(1+pan)/2])
    for beat in range(139):
        t=beat*.60
        notes=[(50,57,64,66),(47,54,62,69),(43,50,59,64),(45,52,61,66)][(beat//4)%4]
        x=np.arange(rate*2)/rate
        for off,n,amp,pan in [(0,notes[beat%4]+12,.12,.22),(.32,notes[(beat+2)%4]+12,.046,-.36)]:
            hz=440*2**((n-69)/12)
            snd=amp*np.sin(2*np.pi*hz*x+.8*np.sin(2*np.pi*2*hz*x)*np.exp(-5*x))*np.exp(-4.1*x)*(1-np.exp(-x/.015))
            put(t+off,snd,pan)
        if beat%2==0:
            hz=440*2**((notes[0]-12-69)/12)
            put(t,.19*np.sin(2*np.pi*hz*x)*np.exp(-4.3*x)*(1-np.exp(-x/.012)),0)
        short=x[:3200]
        noise=rng.normal(0,.066,len(short))
        put(t+.3,np.diff(noise,prepend=0)*np.exp(-78*short)*(1-np.exp(-short/.002)),.3)
    time=np.arange(len(track))/rate
    vol=np.interp(time,[0,.25,59.65,60.18,62.45,63,80.9,81.5,83.1,84],[0,.87,.87,.18,.18,.85,.82,1,.84,0])
    wavfile.write(local/'music.wav',rate,(track*vol[:,None]*32767).astype(np.int16))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--preview',action='store_true');args=parser.parse_args()
    if args.preview:
        renderer.section(('qa',[round(t*30) for t in [1,6,12,15,22,27,36,40,45,49,55,61,64,67,72,74,77,82.5]],False));renderer.sheet()
    else:
        music()
        renderer.section(('overview',range(84*30),True))
        subprocess.run(['ffmpeg','-y','-v','error','-i',str(local/'part-overview.mp4'),'-i',str(local/'music.wav'),'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','160k','-movflags','+faststart','-t','84',str(root/'Что умеет Тройка — монтаж.mp4')],check=True)
