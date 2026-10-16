from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET
import zipfile
from PIL import Image, ImageDraw

root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
visuals=json.loads((root/'quality-visuals.json').read_text(encoding='utf-8'))
importer=json.loads((root/'figma/importer-check.json').read_text(encoding='utf-8'))
live_path=root/'figma/live-import-state.json'
live=json.loads(live_path.read_text(encoding='utf-8')) if live_path.exists() else None
assert not manifest['validation']['javascriptErrors']
assert not manifest['validation']['overflow']
assert not visuals['javascriptErrors'] and not visuals['overflow']
assert all(check['passed'] for check in visuals['checks'])

svg_files=list((root/'svg').rglob('*.svg'))+list((root/'boards').glob('*.svg'))+list((root/'components').glob('*.svg'))
text_count=path_count=0
for file in svg_files:
    tree=ET.parse(file)
    assert not tree.findall('.//{http://www.w3.org/2000/svg}image'),file
    assert not tree.findall('.//{http://www.w3.org/2000/svg}script'),file
    text_count+=len(tree.findall('.//{http://www.w3.org/2000/svg}text'))
    path_count+=len(tree.findall('.//{http://www.w3.org/2000/svg}path'))
for screen in manifest['screens']:
    assert (root/screen['svg']).is_file()
    assert (root/screen['preview']).is_file()

source_font=root.parents[1]/'brand/troika/fonts/GolosText-Variable.ttf'
assert hashlib.sha256(source_font.read_bytes()).digest()==hashlib.sha256((root/'fonts/GolosText-Variable.ttf').read_bytes()).digest()

for platform in ['android','desktop']:
    for theme in ['dark','light']:
        items=[s for s in manifest['screens'] if s['platform']==platform and s['theme']==theme]
        width,height=(190,460) if platform=='android' else (300,310)
        cols=6 if platform=='android' else 4
        canvas=Image.new('RGB',(cols*width,((len(items)+cols-1)//cols)*height),(232,228,220))
        draw=ImageDraw.Draw(canvas)
        for index,screen in enumerate(items):
            image=Image.open(root/screen['preview']).convert('RGB')
            image.thumbnail((width-16,height-42))
            x=(index%cols)*width+8;y=(index//cols)*height+28
            canvas.paste(image,(x,y));draw.text((x,y-20),screen['screen'],fill=(35,32,28))
        canvas.save(root/'review'/(platform+'-'+theme+'.jpg'),quality=88)

report={
    'date':'2026-10-15',
    'screens':len(manifest['screens']),
    'android':len([s for s in manifest['screens'] if s['platform']=='android']),
    'desktop':len([s for s in manifest['screens'] if s['platform']=='desktop']),
    'themes':['dark','light'],
    'voiceComponents':len(manifest['components']),
    'svgFiles':len(svg_files),
    'svgTextElements':text_count,
    'svgVectorPaths':path_count,
    'rasterImagesInSvg':0,
    'javascriptErrors':[],
    'horizontalOverflow':[],
    'browserChecks':visuals['checks'],
    'nativeFigmaApiModel':importer,
    'actualFigmaImportVerified':bool(live and live['status']=='complete'),
    'actualFigmaImport':({key:live[key] for key in ['date','status','fileUrl','importedScreenCount','android','desktop','voiceStatesImported','pendingScreenIds','pendingVoiceStateIds','checks','blocker']} if live else None),
    'nativeClientsModified':False,
    'fontMatchesBrandSource':True,
    'notes':['SVG text may be converted into vector outlines by Figma. The local importer creates native Text nodes.',
             'SVG and Figma voice components are static. Continuous animation remains in the interactive prototypes.',
             'No accounts, keys, private conversations or device recordings are used in the design examples.']
}
(root/'quality-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
archive=root.parent/'Troika-UI-Figma-2026-10-15.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as package:
    for file in sorted(root.rglob('*')):
        if file.is_file():package.write(file,root.name+'/'+file.relative_to(root).as_posix())
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None
    files=len(package.infolist())
digest=hashlib.sha256(archive.read_bytes()).hexdigest()
(root.parent/'Troika-UI-Figma-2026-10-15.sha256').write_text(digest+'  '+archive.name+'\n',encoding='utf-8')
print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'files':files,'sha256':digest,'screens':len(manifest['screens'])},ensure_ascii=False))
