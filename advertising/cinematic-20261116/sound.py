from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, sosfilt

RATE = 48000
DURATION = 12.075
DROP_SOURCE = 46.480
DROP_TARGET = 0.048 + 5 * 0.4838
N = round(RATE * DURATION)
BASE = Path(__file__).resolve().parent
rng = np.random.default_rng(116)

def clock(length):
    return np.arange(round(length * RATE)) / RATE

def noise(time, low, high):
    filt = butter(2, (low, high), btype="bandpass", fs=RATE, output="sos")
    values = sosfilt(filt, rng.standard_normal(len(time)))
    return values / max(1e-9, np.std(values))

def edge(time, rise, tail):
    return np.minimum(time / rise, 1) * np.minimum((time[-1]-time) / tail, 1)

def place(start, signal, gain, pan=0, width=0):
    offset = round(start * RATE)
    left = max(0, offset)
    right = min(N, offset + len(signal))
    position = np.broadcast_to(np.asarray(pan), (len(signal),))
    envelope = np.stack([np.sqrt((1-position)/2), np.sqrt((1+position)/2)], axis=1)
    stereo = signal[:, None] * envelope
    if width:
        stereo[:, 1] += width * np.roll(signal, round(.005*RATE))
        stereo[:, 0] += width * np.roll(signal, round(.009*RATE))
    mix[left:right] += gain * stereo[left-offset:right-offset]

def impact(at, duration, pitch, gain, airy=0.05):
    time = clock(duration)
    bend = 2*np.pi*(pitch*time + .39*pitch*.066*(1-np.exp(-time/.066)))
    hit = np.sin(bend) * np.exp(-9*time)
    knock = .11*np.sin(2*np.pi*198*time) * np.exp(-22*time)
    breath = airy * noise(time, 290, 3700) * np.exp(-19*time)
    place(at, edge(time,.008,.05)*(hit+knock+breath), gain, width=.035)

def click(at, strength, pan, pitch, length=.052):
    time = clock(length)
    key = (.67*np.sin(2*np.pi*pitch*time)+.20*np.sin(2*np.pi*1.74*pitch*time)) * np.exp(-time/.006)
    tick = .26*noise(time, 1350, 6100)*np.exp(-time/.0033)
    place(at, edge(time,.00055,.006)*(key+tick),strength,pan)

def passby(peak, pre, post, gain, pan_from, pan_to, low, high):
    time = clock(pre+post)
    env = np.where(time<pre, (time/pre)**2.35, np.exp(-(time-pre)/(post*.28)))
    frequency = 191 + 535*(time/(pre+post))**1.7
    pulse = np.sin(2*np.pi*np.cumsum(frequency)/RATE)*.21
    swept = .73*noise(time,low,high)+pulse
    place(peak-pre, env*edge(time,.01,.047)*swept,gain,np.linspace(pan_from,pan_to,len(time)),.065)

def shimmer(at):
    time = clock(.55)
    ring = sum(amp*np.sin(2*np.pi*hz*time)*np.exp(-taper*time)
               for amp,hz,taper in [(.67,1369,8),(.35,2093,11),(.25,3226,15),(.1,4671,24)])
    place(at,ring*edge(time,.007,.054),.075,.24,.22)

rate, source = wavfile.read(BASE/"music-source.wav")
if rate != RATE:
    raise ValueError(f"Expected {RATE} Hz source")
first = round((DROP_SOURCE-DROP_TARGET)*RATE)
music = source[first:first+N].astype(np.float64)
t = clock(DURATION)
ramp = np.interp(t,[0,.06,1.7,2.35,2.51,3.72,4.04,4.97,5.3,8.15,10.04,12.075],
                 [0,.50,.56,.57,.57,.57,.51,.51,.58,.57,.54,.54])
mix = music*ramp[:, None]

impact(.10,.39,73,.18)
click(2.330,.13,.35,906)
passby(2.402,.31,.27,.103,.72,-.46,420,4550)
passby(3.370,.18,.18,.105,-.57,.68,380,4200)
click(3.830,.14,.44,1100)
for i, at in enumerate(np.arange(4.04,5.001,.032)):
    click(float(at),.030*(.74+.35*rng.random()),(i%6-2.5)*.068,825+198*rng.random(),.032)
passby(5.305,.36,.25,.17,.33,-.35,270,4680)
impact(6.240,.27,104,.118)
click(6.248,.053,-.14,1430)
passby(7.174,.14,.12,.064,-.52,.52,690,4280)
impact(8.175,.48,64,.18)
passby(10.043,.33,.43,.17,-.12,.27,115,2940)
impact(10.043,.73,48,.22)
shimmer(10.05)
passby(12.063,.175,.072,.058,.51,-.04,325,3620)

mix *= np.interp(t,[0,.008,DURATION-.06,DURATION],[0,1,1,.77])[:,None]
wavfile.write(BASE/"audio-premaster.wav",RATE,mix.astype(np.float32))
