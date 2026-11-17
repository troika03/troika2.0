"""Package standalone projects, timed captions, and final verification evidence."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from html import unescape
import json
import re
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parent
FINAL=ROOT/'final'
NAMES={'coffee':'Troika-Coffee','shorter':'Troika-Shorter','tabs':'Troika-Tabs'}
EPISODES=json.loads((ROOT/'timelines.json').read_text(encoding='utf-8'))

def stamp(value):
    ms=round(value*1000);hours,ms=divmod(ms,3600000);minutes,ms=divmod(ms,60000);seconds,ms=divmod(ms,1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'

def projects():
    for ep in EPISODES:
        project=ROOT if ep['id']=='coffee' else ROOT/'episodes'/ep['id']
        yield ep,project

def run():
    for ep,project in projects():
        captions=[]
        for beat in ep['beats']:
            html=(project/'compositions'/f"{ep['id']}-{beat['id']}.html").read_text(encoding='utf-8')
            for start,duration,text in re.findall(r'data-start="([\d.]+)" data-duration="([\d.]+)"[^>]*><div class="caption">(.*?)</div>',html):
                at=beat['start']+float(start)
                captions.append(f'{len(captions)+1}\n{stamp(at)} --> {stamp(at+float(duration))}\n{unescape(text)}\n')
        (FINAL/(NAMES[ep['id']]+'.srt')).write_text('\n'.join(captions),encoding='utf-8-sig')
        frames=sorted((FINAL/'inspection'/ep['id']).glob('*.png'))
        sheet=Image.new('RGB',(360*len(frames),670),'#141719')
        for i,path in enumerate(frames):
            sheet.paste(Image.open(path),(i*360,30))
            ImageDraw.Draw(sheet).text((i*360+15,8),f'{ep["id"]} / {i+1}',fill='white')
        sheet.save(FINAL/'inspection'/(ep['id']+'-decoded.jpg'),quality=90)

    storyboard=['# Раскадровка', 'Новые истории Тройки. Все действия — демонстрационные примеры.']
    for ep in EPISODES:
        storyboard+=['','## '+ep['title']]
        for b in ep['beats']:
            storyboard.append(f"- {b['start']:.2f}–{b['start']+b['duration']:.2f} с: {b['title'].replace(chr(10),' / ')}. "+b.get('say','Знак Тройки и приглашение попробовать свою задачу.'))
    (ROOT/'STORYBOARD.md').write_text('\n'.join(storyboard)+'\n',encoding='utf-8')

    dest=FINAL/'Troika-HyperFrames-Editable.zip'
    with ZipFile(dest,'w',ZIP_DEFLATED,compresslevel=6) as archive:
        for name in ['README.md','ASSETS.md','REVIEW.md','SPEC.md','STORYLINES.md','STORYBOARD.md','episodes.json','timelines.json']:
            archive.write(ROOT/name,name)
        archive.write(FINAL/'verification.json','verification.json')
        for ep,project in projects():
            for name in ['index.html','hyperframes.json','meta.json','package.json','timeline.json']:
                archive.write(project/name,ep['id']+'/'+name)
            for folder in ['assets','compositions']:
                for path in sorted((project/folder).rglob('*')):
                    if path.is_file():archive.write(path,ep['id']+'/'+path.relative_to(project).as_posix())
            archive.write(FINAL/(NAMES[ep['id']]+'.srt'),ep['id']+'/captions.srt')
    with ZipFile(dest) as archive:
        assert archive.testzip() is None
        names=set(archive.namelist())
        for ep,project in projects():
            for htmlpath in [project/'index.html',*(project/'compositions').glob('*.html')]:
                html=htmlpath.read_text(encoding='utf-8')
                refs=re.findall(r'(?:src|data-composition-src)="([^"]+)"|url\([\x27\x22]?([^\x27\x22)]+)',html)
                for pair in refs:
                    source=next(s for s in pair if s)
                    if source.startswith(('http','data:','#')):continue
                    assert ep['id']+'/'+source in names,source
    print('ZIP verified:',dest.stat().st_size,'bytes;',len(names),'entries')

if __name__=='__main__':run()
