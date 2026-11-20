"""Frame-stepped Chrome/GSAP render with the shared portrait renderer."""
import argparse
from pathlib import Path
from importlib.util import spec_from_file_location, module_from_spec
import subprocess

root=Path(__file__).resolve().parent
local=root/'local'
spec=spec_from_file_location('portrait',root.parent/'six-drafts/render.py')
portrait=module_from_spec(spec)
spec.loader.exec_module(portrait)
portrait.root,portrait.local=root,local
frames=1304
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--preview',action='store_true')
    args=parser.parse_args()
    if args.preview:
        portrait.section(('preview',[0,51,145,216,327,409,533,606,710,792,881,953,1032,1113,1172,1260],False))
        portrait.sheet()
    else:
        portrait.section(('visual',range(frames),True))
        subprocess.run(['ffmpeg','-y','-v','error','-i',str(local/'part-visual.mp4'),'-i',str(local/'mix.wav'),'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-ar','48000','-ac','2','-b:a','224k','-t',str(frames/30),'-movflags','+faststart',str(root/'Тройка — Чёрное стекло.mp4')],check=True)
