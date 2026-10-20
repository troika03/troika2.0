"""Rebuild vector exports, coverage, a compact preview, and the Figma handoff."""
import csv
import json
import re
import zipfile
from html import escape
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from render import vector

ROOT=Path(__file__).resolve().parents[1]
scenes=json.loads((ROOT/'figma'/'scenes.json').read_text(encoding='utf-8'))
def normalize(node):
    if node.get('svg'):
        node['svg']=re.sub(r'url\(&quot;#([^&]+)&quot;\)',r'url(#\1)',node['svg'])
        node['svg']=re.sub(r'''url\(["']#([^"']+)["']\)''',r'url(#\1)',node['svg'])
    for child in node.get('children',[]):normalize(child)
for scene in scenes:
    normalize(scene['root'])
    target=ROOT/'svg'/scene['platform']/scene['theme']/(scene['page']+'.svg')
    target.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{scene["width"]}" height="{scene["height"]}" viewBox="0 0 {scene["width"]} {scene["height"]}"><title>{escape(scene["name"])}</title><style>@font-face{{font-family:"Golos Text";src:url("../../../fonts/GolosText-Variable.ttf");font-weight:100 900}}</style>{vector(scene["root"],scene["id"])}</svg>',encoding='utf-8')
(ROOT/'figma'/'scenes.json').write_text(json.dumps(scenes,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
logical={s['page']:s for s in scenes}
with (ROOT/'PAGE_COVERAGE.csv').open('w',encoding='utf-8-sig',newline='') as file:
    writer=csv.writer(file);writer.writerow(['id','Страница','Раздел','Платформы','Темы','Источник дизайна','Статус'])
    for item in sorted(logical.values(),key=lambda s:s['index']):
        writer.writerow([item['page'],item['name'],item['group'],'ПК' if item['page']=='compact' else 'Android / ПК','Тёмная / Светлая','pages.js / conversation.js / extra-pages.js / workbench.js','Макет; состояние runtime проверяется отдельно'])
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
for platform in ['android','desktop']:
    for theme in ['dark','light']:
        subset=sorted([s for s in scenes if s['platform']==platform and s['theme']==theme],key=lambda s:s['index'])
        cols=6 if platform=='android' else 4;cw=210 if platform=='android' else 330;ch=480 if platform=='android' else 255
        sheet=Image.new('RGB',(cols*cw,((len(subset)+cols-1)//cols)*ch),'#E8ECE7');draw=ImageDraw.Draw(sheet)
        for i,s in enumerate(subset):
            im=Image.open(ROOT/'previews'/platform/theme/(s['page']+'.png')).convert('RGB');im.thumbnail((cw-16,ch-48))
            x=(i%cols)*cw+8;y=(i//cols)*ch+36;draw.text((x,y-28),f"{s['index']+1}. {s['name'][:24]}",font=font,fill='#1f2923');sheet.paste(im,(x,y))
        sheet.save(ROOT/'review'/f'all-{platform}-{theme}.jpg',quality=85)
with zipfile.ZipFile(ROOT/'Troika-Figma-editable.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
    for folder in ['figma','fonts']:
        for p in (ROOT/folder).rglob('*'):
            if p.is_file():archive.write(p,p.relative_to(ROOT).as_posix())
    for name in ['FIGMA.md','README.md','PAGE_COVERAGE.csv']:
        if (ROOT/name).exists():archive.write(ROOT/name,name)
print(json.dumps({'logical_pages':len(logical),'frames':len(scenes),'svg':len(list((ROOT/'svg').rglob('*.svg'))),'archive_bytes':(ROOT/'Troika-Figma-editable.zip').stat().st_size}))
