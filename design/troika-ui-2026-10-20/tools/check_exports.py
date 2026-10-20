"""Validate vector references and inspect a browser-rendered SVG sample."""
import asyncio
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from playwright.async_api import async_playwright
from PIL import Image,ImageChops,ImageStat

ROOT=Path(__file__).resolve().parents[1]
async def main():
    errors=[];files=list((ROOT/'svg').rglob('*.svg'));text_count=0
    for path in files:
        doc=ET.parse(path);nodes=list(doc.getroot().iter());ids={n.get('id') for n in nodes if n.get('id')};text_count+=sum(n.tag.endswith('}text') for n in nodes)
        if any(n.tag.endswith('}image') for n in nodes):errors.append(str(path)+' contains raster image')
        for node in nodes:
            for value in node.attrib.values():
                for ref in re.findall(r'url\(#([^)]+)\)',value):
                    if ref not in ids:errors.append(str(path)+' missing '+ref)
    samples=[]
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        page=await browser.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
        for theme,name in [('dark','home'),('light','home'),('dark','text')]:
            await page.goto((ROOT/'svg'/'android'/theme/(name+'.svg')).as_uri())
            await page.evaluate('document.fonts.ready');await page.wait_for_timeout(70)
            target=ROOT/'review'/f'svg-{theme}-{name}.png';await page.screenshot(path=str(target))
            a=Image.open(target).convert('RGB');b=Image.open(ROOT/'previews'/'android'/theme/(name+'.png')).convert('RGB');diff=ImageChops.difference(a,b);mean=sum(ImageStat.Stat(diff).mean)/3;samples.append({'page':name,'theme':theme,'mean_channel_difference':round(mean,2)})
        await browser.close()
    report={'files':len(files),'editable_svg_text_layers':text_count,'reference_errors':errors,'samples':samples,'note':'Text rendering and backdrop blur differ between SVG and HTML. Native Figma contains editable text and background blur.'}
    (ROOT/'review'/'export-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report))
    if errors:raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())
