"""Frame-stepped OBSION GSAP renderer for a portrait root."""
import argparse
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

root=Path(__file__).resolve().parent
local=root/'local'
fps=30
duration=24
def section(job):
    tag,frames,encode=job
    target=local/f'part-{tag}.mp4'
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='chrome',args=['--allow-file-access-from-files','--disable-dev-shm-usage'])
        page=browser.new_page(viewport={'width':540,'height':960},device_scale_factor=2 if encode else 1)
        page.goto((root/'index.html').as_uri())
        page.evaluate('async()=>{await Promise.all(Array.from(document.images,i=>i.decode()));await document.fonts.ready}')
        proc=None
        if encode:
            proc=subprocess.Popen(['ffmpeg','-y','-v','error','-f','image2pipe','-threads','1','-filter_threads','1','-framerate',str(fps),'-c:v','mjpeg','-i','-',
                '-c:v','libx264','-pix_fmt','yuv420p','-threads','2','-tune','zerolatency','-preset','veryfast','-crf','16','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709',str(target)],stdin=subprocess.PIPE)
        try:
            for frame in frames:
                page.evaluate('(t)=>{window.__timelines.main.seek(t,false)}',frame/fps)
                buf=page.screenshot(type='jpeg',quality=96,animations='allow')
                if encode: proc.stdin.write(buf)
                else: (local/f'preview-{frame:03}.jpg').write_bytes(buf)
        finally:
            browser.close()
            if proc:
                proc.stdin.close()
                if proc.wait(): raise RuntimeError('Video encoder failed')
def sheet():
    paths=sorted(local.glob('preview-*.jpg'))
    sheet=Image.new('RGB',(180*6,344*((len(paths)+5)//6)), '#1b1b1b')
    draw=ImageDraw.Draw(sheet)
    for i,p in enumerate(paths):
        x,y=i%6*180,i//6*344
        sheet.paste(Image.open(p).resize((180,320),Image.Resampling.LANCZOS),(x,y))
        draw.text((x+6,y+324),f'{int(p.stem.split("-")[1])/fps:.2f} s',fill='white')
    sheet.save(local/'review.jpg',quality=90)
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--preview',action='store_true')
    args=parser.parse_args()
    if args.preview:
        section(('review',[6,27,59,77,109,165,200,280,322,377,430,489,535,573,599,617,647,702],False));sheet()
    else:
        section(('full',range(fps*duration),True))
        subprocess.run(['ffmpeg','-y','-v','error','-i',str(local/'part-full.mp4'),'-i',str(local/'mix.wav'),'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','224k','-t',str(duration),'-movflags','+faststart',str(root/'Шесть раз стёр — Gemini.mp4')],check=True)
