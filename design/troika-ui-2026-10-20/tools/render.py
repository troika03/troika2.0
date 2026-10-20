"""Render local design frames and inspect the same DOM used by the prototype."""
import argparse
import asyncio
import json
from pathlib import Path
from html import escape
from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]

def css(c):
    return f"rgba({round(c['r']*255)},{round(c['g']*255)},{round(c['b']*255)},{c.get('a',1)})" if c else 'none'

def vector(node, uid):
    x,y,w,h=(round(node.get(k,0),2) for k in ['x','y','w','h'])
    name=escape(node.get('name',''),quote=True)
    if node['kind']=='text':
        baseline=node.get('baseline',node['fontSize'])+(node['lineHeight']-h)/2
        return f'<text x="{x}" y="{round(y+baseline,2)}" font-family="{escape(node["fontFamily"])}" font-size="{node["fontSize"]}" font-weight="{node["fontWeight"]}" letter-spacing="{node.get("letterSpacing",0)}" fill="{css(node["color"])}" data-name="{name}">{escape(node["text"])}</text>'
    if node['kind']=='svg':
        import re
        svg=node['svg']
        svg=re.sub(r'url\(&quot;#([^&]+)&quot;\)',r'url(#\1)',svg)
        svg=re.sub(r'''url\(["']#([^"']+)["']\)''',r'url(#\1)',svg)
        svg=re.sub(r'(<svg\b[^>]*\b)width="[^"]*"',r'\1width="'+str(w)+'"',svg,count=1)
        svg=re.sub(r'(<svg\b[^>]*\b)height="[^"]*"',r'\1height="'+str(h)+'"',svg,count=1)
        svg=svg.replace('<svg ',f'<svg x="{x}" y="{y}" ',1)
        # SVG ids must remain unique when all frames are collected on one canvas.
        svg=re.sub(r'id="([^"]+)"',lambda m:f'id="{uid}-{node["id"]}-{m[1]}"',svg)
        svg=re.sub(r'url\(#([^)]+)\)',lambda m:f'url(#{uid}-{node["id"]}-{m[1]})',svg)
        return svg
    fill=css(node.get('fill'));stroke=css(node.get('stroke')) if node.get('strokeWidth') else 'none'
    radius=min(node.get('radius',0),w/2,h/2)
    if node['kind']=='checkbox':
        radius=min(w,h)/2 if node.get('round') else 3
        fill=css(node.get('accent')) if node.get('checked') and not node.get('round') else 'none';stroke=css(node.get('accent'));node['strokeWidth']=1
    rect=f'<rect width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="{node.get("strokeWidth",0)}"/>'
    check=''
    if node['kind']=='checkbox' and node.get('checked'):
        if node.get('round'):check=f'<circle cx="{w/2}" cy="{h/2}" r="{min(w,h)*.225}" fill="{css(node.get("accent"))}"/>'
        else:check=f'<path d="M{w*.22} {h*.5} L{w*.43} {h*.72} L{w*.8} {h*.28}" fill="none" stroke="{"#FAFCF9" if "-light-" in uid else "#202322"}" stroke-width="1.5"/>'
    children=''.join(vector(c,uid) for c in node.get('children',[]))
    clip_id=f'clip-{uid}-{node["id"]}'
    clip=f'<defs><clipPath id="{clip_id}"><rect width="{w}" height="{h}" rx="{radius}"/></clipPath></defs>' if node.get('clip') else ''
    inside=f'<g clip-path="url(#{clip_id})">{rect}{check}{children}</g>' if node.get('clip') else rect+check+children
    return f'<g transform="translate({x} {y})" opacity="{node.get("opacity",1)}" data-name="{name}">{clip}{inside}</g>'

def compact(value):
    if isinstance(value,float): return round(value,3)
    if isinstance(value,list):return [compact(v) for v in value]
    if isinstance(value,dict):return {k:compact(v) for k,v in value.items() if v is not None}
    return value

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', default='home,text,tasks,files,development')
    parser.add_argument('--all', action='store_true')
    args = parser.parse_args()
    checks, manifest, scenes, errors = [], [], [], []
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='msedge', headless=True)
        page = await browser.new_page(viewport={'width':1280,'height':840}, device_scale_factor=1, reduced_motion='reduce')
        page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto((ROOT/'app.html').as_uri())
        registry = await page.evaluate('TROIKA_PAGES')
        selected = registry if args.all else [r for r in registry if r['id'] in args.pages.split(',')]
        for platform in ['android','desktop']:
            await page.set_viewport_size({'width':390 if platform=='android' else 1280,'height':844 if platform=='android' else 840})
            for theme in ['dark','light']:
                for item in selected:
                    if item.get('only') and item['only'] != platform:
                        continue
                    await page.goto((ROOT/'app.html').as_uri()+f"?platform={platform}&theme={theme}&page={item['id']}")
                    await page.wait_for_function('()=>window.TROIKA_UI && window.TROIKA_REVISIONS && window.TROIKA_WORKBENCH && document.querySelector("#app").innerText.length>40')
                    await page.evaluate('document.fonts.ready')
                    await page.wait_for_timeout(35)
                    dest=ROOT/'previews'/platform/theme/f"{item['id']}.png"
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    await page.locator('#app').screenshot(path=str(dest),animations='disabled')
                    scene=await page.locator('#app').evaluate((ROOT/'tools'/'extract.js').read_text(encoding='utf-8'))
                    scene.update(id=f"{platform}-{theme}-{item['id']}",page=item['id'],name=item['name'],platform=platform,theme=theme,index=item['index'],group=item['group'])
                    scene=compact(scene);scenes.append(scene)
                    svg_dest=ROOT/'svg'/platform/theme/f"{item['id']}.svg";svg_dest.parent.mkdir(parents=True,exist_ok=True)
                    svg_dest.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{scene["width"]}" height="{scene["height"]}" viewBox="0 0 {scene["width"]} {scene["height"]}"><title>{escape(scene["name"])}</title>{vector(scene["root"],scene["id"])}</svg>',encoding='utf-8')
                    metrics=await page.locator('#app').evaluate('''el=>({width:el.clientWidth,height:el.clientHeight,scrollWidth:el.scrollWidth,ready:!!(window.TROIKA_UI&&window.TROIKA_REVISIONS&&el.innerText.length>40),placeholder:el.innerText.includes('Этот макет появится'),overflow:[...el.querySelectorAll('*')].filter(n=>{let r=n.getBoundingClientRect(),s=getComputedStyle(n);return r.width>0 && r.right>el.getBoundingClientRect().right+1 && s.position!=='fixed'}).slice(0,8).map(n=>n.className?.baseVal||n.className)})''')
                    entry=dict(id=item['id'],name=item['name'],platform=platform,theme=theme,path=dest.relative_to(ROOT).as_posix(),**metrics)
                    manifest.append(entry)
                    if metrics['overflow'] or metrics['placeholder'] or not metrics['ready'] or platform=='android' and metrics['height']!=844: checks.append(entry)
                    if len(manifest)%40==0:print(f'Rendered {len(manifest)} frames',flush=True)
        await browser.close()
    if not args.all:
        # Keep a full handoff when refreshing only the affected page families.
        keys={(m['id'],m['platform'],m['theme']) for m in manifest}
        scene_ids={s['id'] for s in scenes}
        old_manifest=ROOT/'review'/'manifest.json';old_scenes=ROOT/'figma'/'scenes.json';old_checks=ROOT/'review'/'layout-check.json'
        if old_manifest.exists():manifest=[m for m in json.loads(old_manifest.read_text(encoding='utf-8')) if (m['id'],m['platform'],m['theme']) not in keys]+manifest
        if old_scenes.exists():scenes=[s for s in json.loads(old_scenes.read_text(encoding='utf-8')) if s['id'] not in scene_ids]+scenes
        if old_checks.exists():checks=[m for m in json.loads(old_checks.read_text(encoding='utf-8')) if (m['id'],m['platform'],m['theme']) not in keys]+checks
        order={item['id']:item['index'] for item in registry}
        manifest.sort(key=lambda m:(m['platform']=='desktop',m['theme']=='light',order[m['id']]))
        scenes.sort(key=lambda m:(m['platform']=='desktop',m['theme']=='light',m['index']))
    (ROOT/'review'/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'review'/'layout-check.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'review'/'script-errors.json').write_text(json.dumps(errors,ensure_ascii=False,indent=2),encoding='utf-8')
    (ROOT/'figma'/'scenes.json').write_text(json.dumps(scenes,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    for platform in ['android','desktop']:
        subset=[m for m in manifest if m['platform']==platform and m['theme']=='dark' and m['id'] in ['home','text','tasks','files','development']]
        if not subset: continue
        scale=0.72 if platform=='android' else 0.5
        thumbs=[]
        for m in subset:
            im=Image.open(ROOT/m['path']).convert('RGB'); im.thumbnail((int(im.width*scale),int(im.height*scale)))
            thumbs.append((m,im))
        columns=5 if platform=='android' else 2
        cellw=max(i.width for _,i in thumbs)+24; cellh=max(i.height for _,i in thumbs)+52
        sheet=Image.new('RGB',(columns*cellw,((len(thumbs)+columns-1)//columns)*cellh),'#e5e2da'); draw=ImageDraw.Draw(sheet)
        font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)
        for j,(m,im) in enumerate(thumbs):
            x=(j%columns)*cellw+12;y=(j//columns)*cellh+36
            draw.text((x,y-25),f"{j+1}. {m['name']}",font=font,fill='#191813');sheet.paste(im,(x,y))
        sheet.save(ROOT/'review'/f'first-five-{platform}.png')
    print(json.dumps({'frames':len(manifest),'layout_issues':len(checks),'script_errors':len(errors)},ensure_ascii=True))

if __name__=='__main__': asyncio.run(main())
