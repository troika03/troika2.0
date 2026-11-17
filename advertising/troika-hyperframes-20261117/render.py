"""Render the reviewed projects, master their audio, and verify the MP4 files."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import re
import subprocess
from verify import ROOT, CLI, ENV

FINAL=ROOT/'final'
RAW=ROOT/'materials/renders'
NAMES={'coffee':'Troika-Coffee','shorter':'Troika-Shorter','tabs':'Troika-Tabs'}

def one(ep):
    project=ROOT if ep['id']=='coffee' else ROOT/'episodes'/ep['id']
    assert json.loads((project/'check.json').read_text(encoding='utf-8-sig'))['ok']
    base=NAMES[ep['id']]
    raw=RAW/(base+'.mp4');dest=FINAL/(base+'.mp4')
    with (RAW/(base+'.log')).open('w',encoding='utf-8') as log:
        subprocess.run(['node',str(CLI),'render','--quality','delivery','--workers','1','-o',str(raw)],cwd=project,env=ENV,stdout=log,stderr=log,check=True)
    first=subprocess.run(['ffmpeg','-hide_banner','-i',str(raw),'-af','loudnorm=I=-14:TP=-1:LRA=7:print_format=json','-f','null','-'],capture_output=True,text=True,encoding='utf-8',check=True)
    stats=json.loads(re.findall(r'\{[^{}]+\}',first.stderr)[-1])
    norm='loudnorm=I=-14:TP=-1:LRA=7:linear=true:measured_I={input_i}:measured_TP={input_tp}:measured_LRA={input_lra}:measured_thresh={input_thresh}:offset={target_offset}'.format(**stats)
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(raw),'-map','0:v:0','-map','0:a:0','-c:v','copy','-af',norm,'-ar','48000','-c:a','aac','-b:a','192k','-movflags','+faststart',str(dest)],check=True)
    # Decode every stream once; container metadata is checked separately.
    subprocess.run(['ffmpeg','-v','error','-i',str(dest),'-f','null','-'],check=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(dest)]))
    v=next(s for s in probe['streams'] if s['codec_type']=='video')
    a=next(s for s in probe['streams'] if s['codec_type']=='audio')
    assert (v['width'],v['height'],v['r_frame_rate'])==(1080,1920,'30/1')
    assert int(v['nb_frames'])==round(ep['duration']*30)
    second=subprocess.run(['ffmpeg','-hide_banner','-i',str(dest),'-af','loudnorm=I=-14:TP=-1:LRA=7:print_format=json','-f','null','-'],capture_output=True,text=True,encoding='utf-8',check=True)
    measured=json.loads(re.findall(r'\{[^{}]+\}',second.stderr)[-1])
    assert abs(float(measured['input_i'])+14)<1
    assert float(measured['input_tp'])<=-.7
    frames=FINAL/'inspection'/ep['id'];frames.mkdir(parents=True,exist_ok=True)
    for i,b in enumerate(ep['beats']):
        at=min(ep['duration']-1/30,b['start']+b['duration']/2)
        subprocess.run(['ffmpeg','-v','error','-y','-ss',str(at),'-i',str(dest),'-frames:v','1','-vf','scale=360:640',str(frames/f'{i:02}.png')],check=True)
    result={'id':ep['id'],'file':dest.name,'seconds':float(v['duration']),'frames':int(v['nb_frames']),'width':1080,'height':1920,'fps':30,'video':v['codec_name'],'audio':a['codec_name'],'bytes':dest.stat().st_size,'lufs':float(measured['input_i']),'truePeakDb':float(measured['input_tp']),'fullDecode':'passed'}
    (RAW/(base+'-verified.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(base,'verified',flush=True)
    return result

if __name__=='__main__':
    FINAL.mkdir(exist_ok=True);RAW.mkdir(parents=True,exist_ok=True)
    episodes=json.loads((ROOT/'timelines.json').read_text(encoding='utf-8'))
    with ThreadPoolExecutor(max_workers=1) as pool:rows=list(pool.map(one,episodes))
    (FINAL/'verification.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
