"""Render the film's stereo pulse and glass notes on the visual timeline."""
import numpy as np

def glass_score(duration, starts, reply, events=None, sr=48000):
    events = events or {}
    music = np.zeros((round(duration*sr), 2))
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
        bell(events.get((i,offset), starts[i]+offset),930,.049,.061,.12)
    bell(.27,735,.045,.08,-.24)
    bell(reply,980,.052,.14,.28)
    return music
