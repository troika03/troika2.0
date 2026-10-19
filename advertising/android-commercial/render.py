"""Editable 25-second animation of the original Troika Android design assets.

No UI is generated. SVG geometry, icons, wording, type and palette come from
the local source of the named Figma file. Only demo field values and documented
voice states change. This is a design animation, not installed-client footage.
"""
from __future__ import annotations
import argparse
import copy
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import wave
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PROJECT = json.loads((HERE / 'project.json').read_text(encoding='utf-8'))
DEFAULT_OUTPUT = HERE if (HERE/'assets').exists() else REPO/'work/troika-commercial-20261019'
OUT = Path(os.environ.get('TROIKA_FILM_OUTPUT', str(DEFAULT_OUTPUT)))
ASSETS = OUT / 'assets'
CACHE = OUT / 'layers'
W, H, FPS, SECONDS = 1080, 1920, 60, 25
S, SW, SH = 3, 364, 780
INK, PAPER, AMBER = (12, 11, 10), (243, 240, 234), (245, 166, 35)
NS = 'http://www.w3.org/2000/svg'
ET.register_namespace('', NS)


def smooth(x):
    x = min(1., max(0., x))
    return x*x*(3-2*x)


def lerp(a, b, u):
    return a+(b-a)*u


@functools.lru_cache(None)
def font(size, weight=400):
    f = ImageFont.truetype(str(ASSETS/'GolosText-Variable.ttf'), round(size))
    f.set_variation_by_axes([weight])
    return f


def prepare():
    for p in [OUT, ASSETS, CACHE, OUT/'previews', OUT/'audio', OUT/'clips']:
        p.mkdir(parents=True, exist_ok=True)
    design = REPO/PROJECT['design_source']/'svg/android/dark'
    names = sorted({s['screen'] for s in PROJECT['scenes']})
    for n in names:
        shutil.copy2(design/(n+'.svg'), ASSETS/(n+'.svg'))
    for f in ['GolosText-Variable.ttf', 'OFL.txt']:
        shutil.copy2(REPO/'brand/troika/fonts'/f, ASSETS/f)
    shutil.copy2(REPO/'brand/troika/exports/png/logos/logo-ru-reverse.png', ASSETS/'logo.png')
    # The only photographed UI is an actual Samsung keyboard, cropped to keys.
    keyboard = Image.open(REPO/'work/troika-ad-20261017/keyboard.png')
    keyboard.crop((0, 928, 720, 1600)).save(ASSETS/'samsung-keyboard.png')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': SW, 'height': SH}, device_scale_factor=S)
        for n in names:
            original = ET.parse(ASSETS/(n+'.svg')).getroot()
            nav_i = next(i for i, e in enumerate(original) if 'Основные разделы' in e.get('data-name', ''))
            nav_y = float(original[nav_i].get('y'))
            for kind in ['header', 'content', 'nav', 'full']:
                root = copy.deepcopy(original)
                children = list(root)
                root.set('height', str(SH))
                root.set('viewBox', f'0 0 {SW} {SH}')
                for e in list(root):
                    root.remove(e)
                defs = ET.SubElement(root, f'{{{NS}}}defs')
                clip = ET.SubElement(defs, f'{{{NS}}}clipPath', {'id': 'content-clip'})
                ET.SubElement(clip, f'{{{NS}}}rect', {'x':'0','y':'112','width':'364','height':'590'})
                for i,e in enumerate(children):
                    ident = e.get('id', '')
                    num = int(ident.rsplit('-layer-',1)[-1]) if '-layer-' in ident else 0
                    if num == 1:
                        if kind == 'full':
                            e.set('height',str(SH)); root.append(e)
                        continue
                    if e.tag.endswith('title'):
                        continue
                    group = 'header' if 2 <= num <= 9 else ('nav' if i>=nav_i else 'content')
                    if kind not in (group, 'full'):
                        continue
                    # Home's original contour is animated with the same Android formula.
                    if n == '05-home' and num in [12,13,14,15]:
                        continue
                    # Input demo values are editable, while the original field remains.
                    if n == '15-new-project' and num in [16,19,20]:
                        continue
                    if n == '09-new-task' and num == 15:
                        e.text='Посмотреть план запуска'; e.set('fill','rgb(243,240,234)')
                    if group == 'nav':
                        g=ET.SubElement(root,f'{{{NS}}}g',{'transform':f'translate(0 {702-nav_y})'})
                        g.append(e)
                    else:
                        root.append(e)
                raw=ET.tostring(root,encoding='unicode')
                html='<style>@font-face{font-family:"Golos Text";src:url(data:font/ttf;base64,FONT)}*{box-sizing:border-box}html,body{margin:0;background:transparent}</style>'+raw
                import base64
                html=html.replace('FONT',base64.b64encode((ASSETS/'GolosText-Variable.ttf').read_bytes()).decode())
                page.set_content(html)
                page.evaluate('document.fonts.ready')
                page.screenshot(path=str(CACHE/(n+'-'+kind+'.png')),omit_background=True)
        browser.close()
    manifest = {'source':PROJECT['source_kind'],'figma':PROJECT['figma'],'assets':[]}
    for p in sorted(ASSETS.iterdir()):
        manifest['assets'].append({'file':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    (OUT/'asset-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Original Android assets prepared',flush=True)


@functools.lru_cache(None)
def layer(screen, kind):
    return Image.open(CACHE/(screen+'-'+kind+'.png')).convert('RGBA')


@functools.lru_cache(None)
def keyboard():
    im=Image.open(ASSETS/'samsung-keyboard.png').convert('RGBA')
    return im.resize((SW*S,round(im.height/im.width*SW*S)),Image.Resampling.LANCZOS)


def label(im, words, xy, size=14, color=PAPER, weight=400, anchor=None):
    ImageDraw.Draw(im).text(tuple(v*S for v in xy),words,font=font(size*S,weight),fill=color,anchor=anchor)


@functools.lru_cache(None)
def glow():
    wh=260*S
    y,x=np.mgrid[:wh,:wh]
    r=np.sqrt((x-wh/2)**2+(y-wh/2)**2)/S
    alpha=np.clip(60*np.exp(-(r/75)**2)+135*np.maximum(0,1-r/65)**1.5,0,255)
    a=np.zeros((wh,wh,4),dtype=np.uint8);a[:,:,:3]=AMBER;a[:,:,3]=alpha.astype('uint8')
    return Image.fromarray(a)


def orb(im,t,mode='idle',press=1):
    center=(182,326)
    breath=(1-math.cos(t*math.pi/(.76 if mode=='listening' else 2.6)))/2
    phase=t*2*math.pi/(1.2 if mode=='listening' else 8)
    radius=260*.34*(.93+breath*.08)*press
    amplitude=8 if mode=='listening' else (3 if mode=='thinking' else 2+breath*2)
    im.alpha_composite(glow(),(52*S,196*S))
    pts=[]
    for i in range(97):
        a=i/96*2*math.pi
        r=radius+math.sin(a*3+phase)*amplitude+math.cos(a*2-phase*.7)*amplitude*.45
        pts.append(((center[0]+math.cos(a)*r)*S,(center[1]+math.sin(a)*r)*S))
    d=ImageDraw.Draw(im)
    d.line(pts,fill=(*AMBER,158),width=round(1.5*S),joint='curve')
    cx,cy=center[0]*S,center[1]*S
    if mode=='listening':
        for i in range(5):
            h=(12+(math.sin(phase*2+i*.9)+1)/2*28)*S
            x=cx+(i-2)*8*S
            d.rounded_rectangle((x-2*S,cy-h/2,x+2*S,cy+h/2),radius=2*S,fill=(255,248,231,230))
    elif mode=='thinking':
        r=23*S
        d.arc((cx-r,cy-r,cx+r,cy+r),math.degrees(phase),math.degrees(phase)+250,fill=PAPER,width=round(2.5*S))
    else:
        # Same outline microphone as the Android brand icon.
        d.rounded_rectangle((cx-5*S,cy-15*S,cx+5*S,cy+3*S),radius=5*S,outline=(255,248,231),width=2*S)
        d.arc((cx-10*S,cy-9*S,cx+10*S,cy+11*S),0,180,fill=(255,248,231),width=2*S)
        d.line((cx,cy+11*S,cx,cy+17*S),fill=PAPER,width=2*S)
        d.line((cx-6*S,cy+17*S,cx+6*S,cy+17*S),fill=PAPER,width=2*S)


# Actual button centres, in source SVG coordinates after a scroll when present.
TAPS=[(.62,182,326,'voice'),(2.62,182,326,'voice'),(3.64,120,534,'text'),
      (6.44,137,743,'nav'),(8.24,182,238,'development'),(10.04,182,577,'new-project'),
      (10.53,116,259,'field'),(11.59,153,352,'field'),(13.13,285,759,'keyboard-hide'),
      (13.64,182,610,'estimate'),(15.44,182,540,'start'),(18.74,137,743,'nav'),
      (19.29,317,155,'plus'),(19.93,306,444,'switch'),(20.64,182,615,'add'),
      (21.19,48,743,'home')]


def press_strength(t,name):
    p=0
    for at,x,y,n in TAPS:
        if n==name:
            p=max(p,smooth((t-at+.06)/.06)*(1-smooth((t-at-.03)/.11)))
    return 1-.03*p


def compress_button(im,box,t,name):
    scale=press_strength(t,name)
    if scale>.999: return
    box=tuple(round(v*S) for v in box)
    patch=im.crop(box)
    ImageDraw.Draw(im).rectangle(box,fill=INK)
    ww,hh=patch.size
    patch=patch.resize((round(ww*scale),round(hh*scale)),Image.Resampling.LANCZOS)
    im.alpha_composite(patch,(box[0]+(ww-patch.width)//2,box[1]+(hh-patch.height)//2))


def screen_image(screen,t):
    im=layer(screen,'full').copy()
    if screen=='14-development' or (screen=='15-new-project' and 10.53<t<13.4):
        content=layer(screen,'content').copy()
        clip_top=220 if screen=='14-development' else 112
        if screen=='14-development':
            ImageDraw.Draw(content).rectangle((0,0,SW*S,220*S-1),fill=(0,0,0,0))
            ImageDraw.Draw(im).rectangle((0,220*S,SW*S,702*S-1),fill=INK)
            offset=55*smooth((t-9.05)/.52)
        else:
            im=Image.new('RGBA',(SW*S,SH*S),(*INK,255))
            offset=22*(1-smooth((t-13.14)/.26))
        moved=Image.new('RGBA',im.size)
        moved.alpha_composite(content,(0,-round(offset*S)))
        content=moved
        clip=Image.new('L',im.size)
        ImageDraw.Draw(clip).rectangle((0,clip_top*S,SW*S,702*S-1),fill=255)
        content.putalpha(Image.fromarray(np.minimum(np.asarray(content.getchannel('A')),np.asarray(clip))))
        im.alpha_composite(content)
        im.alpha_composite(layer(screen,'header'))
        im.alpha_composite(layer(screen,'nav'))
    d=ImageDraw.Draw(im)
    if screen=='05-home':
        mode='listening' if .70<=t<2.70 else ('thinking' if 2.70<=t<3.33 else 'idle')
        orb(im,t,mode,press_strength(t,'voice'))
        status='Слушаю' if mode=='listening' else ('Разбираюсь' if mode=='thinking' else 'Нажми и говори')
        label(im,status,(182,466),16,weight=500,anchor='ms')
        hint='Подготовь план запуска проекта.' if mode=='listening' else 'Можно начать с любой задачи'
        if mode=='listening': hint=hint[:round(len(hint)*smooth((t-.9)/1.2))]
        label(im,hint,(182,488),12,color=(178,176,163),anchor='ms')
        if t<3.33:
            d.rectangle((15*S,571*S,350*S,700*S),fill=INK)
        elif t<3.75:
            u=smooth((t-3.33)/.42)
            patch=im.crop((15*S,571*S,350*S,700*S))
            d.rectangle((15*S,571*S,350*S,700*S),fill=INK)
            patch.putalpha(round(u*255))
            im.alpha_composite(patch,(15*S,round((571+14*(1-u))*S)))
        compress_button(im,(75,513,165,555),t,'text')
    if screen=='06-text':
        u=smooth((t-4.33)/.7)
        if u<1:
            d.rectangle((20*S,305*S,345*S,488*S),fill=INK)
            p=layer(screen,'content').crop((20*S,305*S,345*S,488*S))
            p.putalpha(round(255*u)); im.alpha_composite(p,(20*S,round((305+14*(1-u))*S)))
    if screen=='14-development':
        compress_button(im,(25,553,339,600),t,'new-project')
    if screen=='15-new-project':
        lift=22*(1-smooth((t-13.14)/.26)) if 10.53<t<13.4 else 0
        title='Сайт студии'; desc='Страница и форма заявки.'
        title=title[:round(len(title)*smooth((t-10.64)/.84))]
        desc=desc[:round(len(desc)*smooth((t-11.72)/1.22))]
        label(im,title,(38,286-lift),14)
        label(im,desc,(38,378-lift),14)
        if 10.53<t<13.14:
            bx=(25,233,339,283) if t<11.65 else (25,325,339,437)
            d.rounded_rectangle(tuple(v*S for v in bx),radius=12*S,outline=AMBER,width=2*S)
            # Actual photographed Samsung keyboard, never redrawn.
            kb=keyboard()
            start=440
            im.alpha_composite(kb,(0,start*S))
            if int(t*3)%2==0:
                tx=38+font(14*S).getlength(title if t<11.65 else desc)/S
                yy=248 if t<11.65 else 340
                d.line((tx*S,yy*S,tx*S,(yy+19)*S),fill=AMBER,width=2*S)
        elif 13.14<=t<13.4:
            u=smooth((t-13.14)/.26)
            im.alpha_composite(keyboard(),(0,round((440+350*u)*S)))
        compress_button(im,(25,588,339,634),t,'estimate')
    if screen=='16-budget':
        compress_button(im,(25,517.8,339,562.8),t,'start')
    if screen=='17-development-detail':
        # In-progress animation only: never invent a successful build or preview.
        progress=lerp(.20,.60,smooth((t-15.7)/2.7))
        d.rectangle((46*S,315.8*S,318*S,319.8*S),fill=(42,42,36))
        d.rectangle((46*S,315.8*S,(46+272*progress)*S,319.8*S),fill=AMBER)
        x=(46+272*progress)*S
        d.ellipse((x-3*S,314.8*S,x+3*S,320.8*S),fill=AMBER)
    if screen=='09-new-task':
        # Preserve the exact square checkbox from the source design.
        u=smooth((t-19.93)/.15)
        checked=im.crop((293*S,431*S,320*S,458*S))
        d.rectangle((293*S,431*S,320*S,458*S),fill=INK)
        d.rounded_rectangle((294*S,432*S,318*S,456*S),radius=4*S,outline=(178,176,163),width=S)
        checked.putalpha(round(u*255)); im.alpha_composite(checked,(293*S,431*S))
        compress_button(im,(25,592,339,638),t,'add')
    if screen=='08-tasks':
        if t<20.8:
            # One existing reminder; the second row arrives after Add is pressed.
            second=im.crop((25*S,411*S,339*S,485*S))
            d.rectangle((25*S,330*S,339*S,485*S),fill=INK)
            im.alpha_composite(second,(25*S,336*S))
            d.rectangle((285*S,303*S,340*S,326*S),fill=INK)
            label(im,'1 дело',(339,318),12,color=(178,176,163),anchor='rs')
        compress_button(im,(25,199,339,277),t,'development')
    return im


def current(t):
    return next(s for s in PROJECT['scenes'] if s['start']<=t<s['end'])


def camera(t):
    keys=[(0,900,182,350,960),(.7,943,182,350,960),(3.4,860,182,370,960),
          (4.3,895,182,370,960),(6.6,825,182,370,960),(8.4,845,182,380,960),
          (10.2,900,182,370,960),(11.8,930,182,365,960),(13.7,820,182,390,960),
          (15.6,860,182,370,960),(18.3,891,182,380,960),(19.5,825,182,390,960),
          (21.35,815,182,390,960),(23.0,510,182,390,755),(25,516,182,390,750)]
    for a,b in zip(keys,keys[1:]):
        if a[0]<=t<=b[0]:
            u=smooth((t-a[0])/(b[0]-a[0]))
            return tuple(lerp(a[i],b[i],u) for i in range(1,5))
    return keys[-1][1:]


@functools.lru_cache(None)
def background():
    y,x=np.mgrid[:H,:W]
    v=np.exp(-((x-540)/700)**2-((y-880)/1150)**2)
    a=np.zeros((H,W,4),dtype=np.uint8)
    for i,c in enumerate([8,7,6]): a[:,:,i]=(c+v*8).astype('uint8')
    a[:,:,3]=255
    return Image.fromarray(a)


def touches(frame,t,cam):
    width,fx,fy,cy=cam; scale=width/SW
    d=ImageDraw.Draw(frame)
    def pos(x,y): return (540+(x-fx)*scale,cy+(y-fy)*scale)
    for at,x,y,name in TAPS:
        age=t-at
        if -.13<age<.38:
            px,py=pos(x,y)
            a=smooth((age+.13)/.10)*(1-smooth((age-.08)/.25))
            rad=18*(1-.2*smooth((age+.04)/.08))
            touch=Image.new('RGBA',frame.size);td=ImageDraw.Draw(touch)
            td.ellipse((px-rad,py-rad,px+rad,py+rad),fill=(255,255,255,round(70*a)),outline=(255,255,255,round(180*a)),width=2)
            if age>=0:
                r=19+53*smooth(age/.38)
                td.ellipse((px-r,py-r,px+r,py+r),outline=(255,255,255,round(100*(1-age/.38))),width=2)
            frame.alpha_composite(touch)
    if 8.96<t<9.65:
        u=smooth((t-9.05)/.45)
        x=276+10*math.sin(u*math.pi); y=560-55*u
        px,py=pos(x,y)
        a=smooth((t-8.96)/.1)*(1-smooth((t-9.50)/.15))
        touch=Image.new('RGBA',frame.size);td=ImageDraw.Draw(touch)
        td.ellipse((px-18,py-18,px+18,py+18),fill=(255,255,255,round(80*a)),outline=(255,255,255,round(180*a)),width=2)
        frame.alpha_composite(touch)


@functools.lru_cache(None)
def logo(): return Image.open(ASSETS/'logo.png').convert('RGBA')


def frame(t):
    sc=current(min(t,24.9999))
    ui=screen_image(sc['screen'],t)
    if 0<t-sc['start']<.25 and sc['start']:
        prev=current(sc['start']-.001)
        before=screen_image(prev['screen'],sc['start']-.001)
        u=smooth((t-sc['start'])/.25)
        old=Image.new('RGBA',ui.size,(*INK,255))
        if sc['screen'] in ['08-tasks','05-home']:
            ui=Image.blend(before,ui,u)
        else:
            old.alpha_composite(before,(-round(u*SW*S*.23),0))
            old.alpha_composite(ui,(round((1-u)*SW*S),0))
            ui=old
    cam=camera(t); width,fx,fy,cy=cam; scale=width/SW
    x=540-fx*scale;y=cy-fy*scale
    out=background().copy()
    # A single stationary phone, with understated graphite rails and real screen pixels.
    pad=9
    body=(x-pad*scale,y-pad*scale,x+(SW+pad)*scale,y+(SH+pad)*scale)
    shadow=Image.new('RGBA',(W//4,H//4))
    ImageDraw.Draw(shadow).rounded_rectangle(tuple(v/4 for v in (body[0]-12,body[1]+32,body[2]+12,body[3]+42)),radius=15,fill=(0,0,0,145))
    out.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(5.5)).resize(out.size,Image.Resampling.BILINEAR))
    d=ImageDraw.Draw(out)
    d.rounded_rectangle(body,radius=55*scale/2.3,fill=(24,23,21),outline=(91,86,77),width=2)
    inner=(x-3*scale,y-3*scale,x+(SW+3)*scale,y+(SH+3)*scale)
    d.rounded_rectangle(inner,radius=43*scale/2.3,fill=INK,outline=(4,4,4),width=3)
    ww=round(width);hh=round(SH*scale)
    ui=ui.resize((ww,hh),Image.Resampling.LANCZOS)
    mask=Image.new('L',ui.size)
    ImageDraw.Draw(mask).rounded_rectangle((0,0,ww,hh),radius=round(17*scale),fill=255)
    ui.putalpha(mask);out.alpha_composite(ui,(round(x),round(y)))
    # Camera aperture stays on the same physical phone through every move.
    d=ImageDraw.Draw(out)
    cx=540;cc=y+13*scale
    d.ellipse((cx-3.5*scale,cc-3.5*scale,cx+3.5*scale,cc+3.5*scale),fill=(4,5,5),outline=(30,30,29),width=1)
    touches(out,t,cam)
    if t<2.2:
        a=1-smooth((t-1.7)/.5)
        ImageDraw.Draw(out).text((540,1870),'Демонстрация интерфейса Android',font=font(23),fill=(150,146,135,round(a*255)),anchor='mm')
    if t>22:
        u=smooth((t-22)/.65)
        asset=logo();lw=625;lh=round(lw*asset.height/asset.width)
        asset=asset.resize((lw,lh),Image.Resampling.LANCZOS)
        asset.putalpha(asset.getchannel('A').point(lambda a:round(a*u)))
        out.alpha_composite(asset,((W-lw)//2,round(1450+20*(1-u))))
        text_layer=Image.new('RGBA',out.size)
        ImageDraw.Draw(text_layer).text((540,1668+20*(1-u)),'От просьбы к действию.',font=font(48,500),fill=(*PAPER,round(255*u)),anchor='mm')
        out.alpha_composite(text_layer)
    return out.convert('RGB')


def audio():
    sr=48000;n=sr*SECONDS;t=np.arange(n)/sr
    music=np.zeros((n,2),dtype=np.float64);sfx=np.zeros_like(music)
    rng=np.random.default_rng(19102026)
    def add(dst,start,sound,gain=1,pan=0):
        at=round(start*sr)
        if at<0 or at>=n:return
        sound=sound[:n-at]*gain
        dst[at:at+len(sound),0]+=sound*math.sqrt((1-pan)/2)
        dst[at:at+len(sound),1]+=sound*math.sqrt((1+pan)/2)
    beat=60/96
    chords=[[50,57,60,64],[46,53,57,60],[53,60,64,67],[48,55,59,62]]
    for bar in range(10):
        start=bar*4*beat;chord=chords[bar%4]
        tt=np.arange(round(3.4*sr))/sr
        env=np.minimum(tt/.24,1)*np.exp(-tt/1.7)
        pad=np.zeros_like(tt)
        for note in chord:
            f=440*2**((note+12-69)/12)
            pad+=(np.sin(2*np.pi*f*tt)+.25*np.sin(2*np.pi*f*1.0017*tt))/len(chord)
        add(music,start,pad*env,.13,-.15)
        for k in range(8):
            at=start+k*beat/2
            pt=np.arange(round(.85*sr))/sr
            note=chord[k%4]+24;f=440*2**((note-69)/12)
            pluck=(np.sin(2*np.pi*f*pt)+.14*np.sin(4*np.pi*f*pt))*np.exp(-pt*7)*np.minimum(pt/.006,1)
            add(music,at+.08,pluck,.065,(-1 if k%2 else 1)*.42)
        if start>.1:
            for k in range(4):
                kt=np.arange(round(.24*sr))/sr
                kick=np.sin(2*np.pi*(47*kt+2.6*(1-np.exp(-kt*25))))*np.exp(-kt*23)
                add(music,start+k*beat,kick,.15 if k%2==0 else .08)
                ht=np.arange(round(.045*sr))/sr
                noise=rng.normal(size=len(ht));noise-=np.roll(noise,1)
                add(music,start+(k+.5)*beat,noise*np.exp(-ht*110),.008,.25)
    for at,x,y,name in TAPS:
        tt=np.arange(round(.085*sr))/sr
        click=(np.sin(2*np.pi*850*tt)*np.exp(-tt*110)+.25*rng.normal(size=len(tt))*np.exp(-tt*200))*np.minimum(tt/.0015,1)
        add(sfx,at,click,.055,(x/SW-.5)*.55)
    for at in [3.8,6.6,8.4,10.2,13.8,15.6,18.9,19.45,20.8,21.35]:
        tt=np.arange(round(.3*sr))/sr
        noise=rng.normal(size=len(tt));noise=np.convolve(noise,np.ones(18)/18,mode='same')
        add(sfx,at-.08,noise*np.sin(np.pi*tt/.3)**2,.08,-.15)
    tt=np.arange(round(.56*sr))/sr
    noise=rng.normal(size=len(tt));noise=np.convolve(noise,np.ones(24)/24,mode='same')
    add(sfx,9.02,noise*np.sin(np.pi*tt/.56)**2,.12,.22)
    for at in [3.33,20.85,22.25]:
        tt=np.arange(round(.75*sr))/sr
        note=(np.sin(2*np.pi*880*tt)+.4*np.sin(2*np.pi*1320*tt))*np.exp(-tt*8)*np.minimum(tt/.005,1)
        add(sfx,at,note,.06,.2)
    for at in np.arange(10.7,11.48,.08).tolist()+np.arange(11.8,13.0,.06).tolist():
        tt=np.arange(round(.032*sr))/sr
        key=rng.normal(size=len(tt))*np.exp(-tt*240)
        add(sfx,float(at),key,.014,float(rng.uniform(-.25,.25)))
    env=np.minimum(t/.5,1)*np.minimum((SECONDS-t)/1.25,1)
    music*=env[:,None]
    # Keep the music behind the tactile accents; measure the mastered result.
    peak=max(np.max(np.abs(music+sfx)),.001)
    gain=.68/peak
    def save(name,arr):
        with wave.open(str(OUT/'audio'/name),'wb') as f:
            f.setnchannels(2);f.setsampwidth(2);f.setframerate(sr)
            f.writeframes(np.clip(arr*gain*32767,-32767,32767).astype('<i2').tobytes())
    save('music.wav',music);save('interaction-sfx.wav',sfx);save('mix.wav',music+sfx)
    print('Original stereo score and interaction sound design ready',flush=True)


def previews():
    times=[.9,2.0,3.5,4.9,7.3,9.75,11.0,12.7,14.6,17.5,20.1,23.8]
    sheet=Image.new('RGB',(1080,3*516),INK)
    for i,t in enumerate(times):
        im=frame(t);im.save(OUT/'previews'/f'{t:05.2f}.jpg',quality=93)
        small=im.resize((270,480),Image.Resampling.LANCZOS)
        sheet.paste(small,((i%4)*270,(i//4)*516))
        ImageDraw.Draw(sheet).text(((i%4)*270+12,(i//4)*516+487),f'{t:05.2f} с',font=font(18),fill=PAPER)
    sheet.save(OUT/'preview-contact.jpg',quality=94)
    frame(23.8).save(OUT/'poster.jpg',quality=95)


def render(preview=False):
    target=OUT/('Troika-Android-preview.mp4' if preview else 'Troika-Android-25s-1080x1920-60fps.mp4')
    ow,oh,rate=(540,960,30) if preview else (W,H,FPS)
    cuts=','.join(str(s['start']) for s in PROJECT['scenes'])
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{ow}x{oh}','-framerate',str(rate),'-i','-',
         '-i',str(OUT/'audio/mix.wav'),'-map','0:v','-map','1:a','-c:v','libx264','-preset','fast','-crf','18','-threads','4','-pix_fmt','yuv420p',
         '-profile:v','high','-level:v','4.2','-force_key_frames',cuts,'-c:a','aac','-b:a','256k','-ar','48000','-af','loudnorm=I=-16:TP=-1.5:LRA=8',
         '-t',str(SECONDS),'-movflags','+faststart','-metadata','title='+PROJECT['title'],'-metadata','comment='+PROJECT['source_kind'],str(target)]
    process=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    for i in range(rate*SECONDS):
        im=frame(i/rate)
        if preview:im=im.resize((ow,oh),Image.Resampling.LANCZOS)
        process.stdin.write(im.tobytes())
        if i%(rate*2)==0: print(f'{"Preview" if preview else "Master"}: {i/rate:.0f}/25 s',flush=True)
    process.stdin.close()
    if process.wait():raise RuntimeError('FFmpeg encoding failed')
    print(target,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--previews',action='store_true')
    parser.add_argument('--preview-video',action='store_true')
    args=parser.parse_args()
    if args.prepare or not (CACHE/'05-home-content.png').exists():prepare()
    if not (OUT/'audio/mix.wav').exists():audio()
    if args.previews:previews()
    else:render(args.preview_video)
