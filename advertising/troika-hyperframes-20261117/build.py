"""Build three editable HyperFrames projects from the original scripts.

Real product captures and marks are copied without repainting. Conversation,
reminder and output examples are explicitly labelled as staged scenarios.
"""
from pathlib import Path
from html import escape
import json
import math
import shutil
import subprocess
import wave
import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SPEC = json.loads((ROOT / 'episodes.json').read_text(encoding='utf-8'))
SR = 48000

def command(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL)

def decode(path, start=None, duration=None):
    args=['ffmpeg','-v','error']
    if start is not None: args += ['-ss',str(start)]
    args += ['-i',str(path)]
    if duration is not None: args += ['-t',str(duration)]
    return np.frombuffer(subprocess.check_output(args+['-ac','1','-ar',str(SR),'-f','f32le','-']),dtype='<f4').copy()

def trim(data):
    block=480
    rms=np.array([np.sqrt(np.mean(data[i:i+block]**2)) for i in range(0,len(data),block)])
    active=np.flatnonzero(rms>max(.0025,float(rms.max())*.022))
    if not len(active): raise ValueError('Silent speech')
    return data[max(0,active[0]*block-1920):min(len(data),(active[-1]+1)*block+4800)]

def wav(path, data):
    with wave.open(str(path),'wb') as w:
        w.setparams((1,2,SR,0,'NONE','not compressed'))
        w.writeframes((np.clip(data,-.98,.98)*32767).astype('<i2').tobytes())

CSS='''
@font-face{font-family:"Golos Text";src:url('assets/fonts/GolosText-Variable.ttf') format('truetype');font-weight:100 900}
*{box-sizing:border-box}#root{position:absolute;inset:0;overflow:hidden;font-family:"Golos Text",sans-serif;color:var(--ink,#F4F5F7);background:var(--ground,#0B0C10)}
.scene{position:absolute;inset:0;background:radial-gradient(ellipse at 20% 68%,#123e32 0,transparent 57%),#0B0C10}
.headline{position:absolute;left:100px;top:195px;width:820px;margin:0;font-size:76px;font-weight:750;line-height:1.06;letter-spacing:-3px;z-index:4;white-space:pre-line}
.headline em{font-style:normal;color:var(--accent,#3DDC97)}
.stage{position:absolute;inset:0;perspective:1600px}
.phone{position:absolute;left:240px;top:435px;width:560px;height:1212px;padding:12px;border:2px solid #707b77;border-radius:61px;background:#080b0c;box-shadow:17px 24px 0 #020404,34px 54px 65px #0008;transform-style:preserve-3d;overflow:hidden}
.phone-screen{width:532px;height:1184px;border-radius:48px;overflow:hidden;position:relative;background:#0B0C10}
.home{position:absolute;inset:0;width:100%;height:100%;object-fit:fill}
.native{position:absolute;inset:0;padding:31px 25px;background:radial-gradient(ellipse at 35% 5%,#143b30,transparent 54%),#0B0C10}
.top{height:70px;display:flex;gap:14px;align-items:center;font-size:30px;font-weight:650}.top img{width:45px;height:45px;border-radius:12px}.top span{margin-left:auto;color:#9aaba3;font-size:29px;font-weight:400}
.screen-title{font-size:36px;line-height:1.2;font-weight:600;margin:35px 0 28px}
.bubble{padding:22px 24px;border-radius:24px;background:#1f3c31;border:1px solid #32604e;margin:25px 0 24px 42px;font-size:29px;line-height:1.42}
.reply{font-size:31px;line-height:1.4;margin:27px 0;padding:0 8px}.reply strong{color:#3DDC97;font-weight:600}
.input{position:absolute;bottom:105px;left:20px;right:20px;background:#202b27;border:1px solid #3c4a44;border-radius:35px;padding:23px;color:#b6c2bc;font-size:26px}
.nav{position:absolute;bottom:19px;left:20px;right:20px;display:flex;justify-content:space-around;border:1px solid #3c4a44;border-radius:28px;padding:21px 0;background:#1f2724;color:#c1cec7;font-size:21px}.nav b{color:#3DDC97;font-weight:500}
.task{padding:22px;background:#18251f;border:1px solid #395346;border-radius:23px;margin-top:28px;font-size:30px;line-height:1.4}.task small{display:block;font-size:25px;color:#b2c4b9;margin-top:8px}.tick{font-size:33px;color:#3DDC97}
.memory{margin-top:32px;border-top:1px solid #405248;padding-top:26px;font-size:30px;line-height:1.5}.memory span{font-size:24px;color:#b2c4b9}
.clock{font-size:115px;font-weight:450;letter-spacing:-5px;margin-top:56px;text-align:center}.clock-date{text-align:center;font-size:27px;color:#b8c6bf}
.notification{padding:28px;margin-top:66px;background:#263a30;border:1px solid #56836d;border-radius:32px;box-shadow:0 25px 50px #0004;font-size:35px;line-height:1.3}.notification small{display:flex;align-items:center;gap:15px;font-size:25px;margin-bottom:24px}.notification img{width:38px;height:38px;border-radius:8px}
.caption{position:absolute;left:100px;top:1185px;width:820px;min-height:112px;font-size:43px;line-height:1.22;font-weight:650;text-align:center;padding:18px 21px;border-radius:23px;background:#07110ff2;box-shadow:0 8px 38px #0008;z-index:15}
.demo-label{position:absolute;left:102px;top:1350px;font-size:28px;color:#a8bbb0;z-index:20}
.desktop{position:absolute;left:94px;top:490px;width:880px;height:550px;border:3px solid #76877e;border-radius:24px;overflow:hidden;background:#0b0c10;box-shadow:0 35px 70px #0008}.desktop img{width:100%;height:100%}
.desktop:after{content:'';position:absolute;inset:0;border-radius:20px;box-shadow:inset 0 0 0 1px #fff2;pointer-events:none}
.slide{position:absolute;left:42px;top:120px;right:42px;height:360px;background:#f5f7f1;color:#15261e;border-radius:6px;padding:32px;font-size:35px;line-height:1.25;box-shadow:0 12px 35px #0007}.slide small{font-size:23px;color:#526358;display:block;margin-bottom:20px}.slide h2{font-size:54px;line-height:1.05;letter-spacing:-2px;margin:0 0 20px}.slide p{font-size:29px;margin:0}.filecard{position:absolute;left:140px;top:1055px;width:760px;border-radius:27px;background:#1b3328;border:1px solid #53826b;padding:22px 25px;font-size:34px;z-index:6}.filecard small{display:block;color:#aac1b2;font-size:27px;margin-top:8px}.filecard b{color:#60e8aa}
.hero-message{position:absolute;left:90px;top:650px;width:835px;padding:40px;background:#24362e;border:1px solid #5c7969;border-radius:38px;font-size:95px;font-weight:650;line-height:1.15;box-shadow:0 35px 90px #0008}.hero-message small{display:block;font-size:30px;font-weight:450;color:#b7cbbf;margin-bottom:20px}
.budget-slide{position:absolute;left:90px;top:540px;width:850px;height:550px;background:#f4f6ef;color:#14291c;padding:80px 65px;box-shadow:0 30px 75px #0009;font-size:100px;font-weight:750;letter-spacing:-5px;line-height:1.05}.budget-slide small{font-size:28px;color:#526858;letter-spacing:0;display:block;margin-bottom:40px}
.source{padding:24px;background:#192d23;border:1px solid #3f7055;border-radius:24px;margin-top:35px;font-size:29px;line-height:1.4}.source small{display:block;font-size:24px;color:#acc5b5;margin-bottom:18px}.keys{display:flex;gap:9px;align-items:center;font-size:30px;margin-top:26px}.keys b{border:1px solid #50715c;border-radius:8px;background:#223c2d;padding:8px 12px}
.tab-stack{position:absolute;left:100px;top:520px;width:825px}.tab-row{height:84px;margin-bottom:14px;background:#1e2d26;border:1px solid #425a4b;border-radius:16px;display:flex;align-items:center;gap:25px;padding:18px 25px;font-size:31px;color:#d5e1d9}.tab-row i{width:24px;height:24px;border:2px solid #64a980;border-radius:50%}.tab-row span{margin-left:auto;color:#94b4a1}.count{position:absolute;left:130px;top:620px;font-size:410px;font-weight:650;letter-spacing:-25px;line-height:1;color:#3DDC97}.count-note{position:absolute;left:160px;top:1040px;font-size:45px;color:#d6e4dc}
.end-mark{position:absolute;left:330px;top:490px;width:380px;height:380px;border-radius:88px;box-shadow:0 30px 75px #0008}.end-name{position:absolute;left:100px;top:920px;width:820px;font-size:102px;line-height:1;text-align:center;font-weight:650;letter-spacing:-4px}.end-platform{position:absolute;left:100px;top:1060px;width:820px;font-size:37px;text-align:center;color:#b9d1c1}.end-cta{position:absolute;left:100px;top:1220px;width:820px;font-size:34px;text-align:center;color:#3DDC97}
.score{position:absolute;left:115px;top:655px;width:800px;font-size:115px;line-height:1.25;font-weight:700;letter-spacing:-5px}.score em{font-style:normal;color:#3DDC97}
'''

CSS += '''
.headline{left:125px;top:300px;width:750px;font-size:64px;letter-spacing:-2px;line-height:1.06}
.phone{top:535px}
.caption{left:125px;top:1070px;width:650px;min-height:92px;font-size:38px;line-height:1.2;padding:16px 18px}
.demo-label{left:125px;top:1205px;font-size:28px}
.desktop{left:125px;top:500px;width:790px;height:450px}
.slide{left:30px;right:30px;top:95px;height:310px;padding:24px}
.slide h2{font-size:48px}.slide p{font-size:28px}
.filecard{left:125px;top:955px;width:650px;font-size:30px;padding:15px 20px}
.filecard small{font-size:28px}
.end-platform{left:125px;width:650px;font-size:34px}
.end-name{left:125px;width:650px}.end-mark{left:260px}
.end-cta{left:125px;top:1170px;width:650px}
.hero-message{left:125px;width:700px}.budget-slide{left:125px;width:750px}
.score{left:135px}
.memory span,.task small,.clock-date,.notification small,.source small{font-size:31px}
.clock{margin-top:25px;font-size:100px}
.notification{margin-top:30px;padding:22px;font-size:32px}
.notification small{margin-bottom:14px}
.tab-stack{top:500px}.tab-row{height:67px;margin-bottom:10px;padding:14px 25px}
.count-note{top:990px;font-size:38px}
.tab-stack{left:160px;width:620px}
.slide small{font-size:31px}
.hero-message{font-size:83px}
.source{margin-top:20px;padding:18px}.source small{margin-bottom:10px}
.keys{margin-top:12px}.source+.reply{font-size:29px;margin-top:15px}
.desktop{left:155px;width:760px}
'''

def native(content, section='Разговоры'):
    return '<div class="native"><div class="top"><img src="assets/icon.png" alt="Знак Тройки">тройка<span>＋</span></div>'+content+'<div class="input" data-layout-ignore>Напиши сообщение　↑</div><div class="nav" data-layout-ignore>Главная　 <b>'+section+'</b>　 Дела　 Ещё</div></div>'

def phone(content, sid, home=False):
    inner='<img class="home" src="assets/android-home.png" alt="Настоящий главный экран Тройки для Android">' if home else native(content)
    return f'<div class="phone" id="{sid}-device"><div class="phone-screen">{inner}</div></div>'

def bubble(text): return '<div class="bubble">'+escape(text)+'</div>'
def reply(text): return '<div class="reply">'+text+'</div>'

def art(ep, b, sid):
    k=b['kind'];e=ep['id']
    if k=='end':
        return f'<img id="{sid}-device" class="end-mark" src="assets/icon.png" alt="Логотип Тройки"><div class="end-name">тройка</div><div class="end-platform">Голосовая помощница<br>Android · Windows</div><div class="end-cta">Попробуй свою задачу</div>'
    if k=='hook':
        if e=='tabs':
            labels=['Как записать экран?','Запись без программ','Где включить запись','Со звуком или без?','Сохранить видео','Инструкция','А что я искал?']
            return '<div class="tab-stack" id="'+sid+'-device">'+''.join('<div class="tab-row"><i></i>'+x+'<span>×</span></div>' for x in labels)+'</div>'
        return phone('',sid,True)
    if e=='coffee':
        if k=='request': return phone('<div class="screen-title">Разговор</div>'+bubble('Напомни через 10 минут забрать кофе. И запомни: я без сахара.')+reply('Сохраняю напоминание<br>и предпочтение…'),sid)
        if k=='memory': return phone('<div class="screen-title">Дела</div><div class="task"><span class="tick">✓</span> Забрать кофе<small>Через 10 минут</small></div><div class="memory"><span>ПАМЯТЬ</span><br>Кофе — без сахара</div>',sid)
        if k=='reminder': return phone('<div class="clock">10:10</div><div class="clock-date">Десять минут спустя</div><div class="notification"><small><img src="assets/icon.png" alt="">Тройка · сейчас</small>Пора забрать кофе</div>',sid)
        if k=='question': return phone('<div class="screen-title">Разговор</div>'+bubble('А сахар взять?')+reply('<strong>Ты без сахара.</strong>'),sid)
        if k=='punch': return '<div class="score" id="'+sid+'-device"><em>Тройка　1</em><br>Я　　　 0</div>'
    if e=='shorter':
        if k=='request': return phone('<div class="screen-title">Разговор</div>'+bubble('Собери 3 слайда: проблема, решение, следующий шаг.')+reply('Создаю презентацию…'),sid)
        if k=='slides': return f'<div class="desktop" id="{sid}-device"><img src="assets/windows-home.png" alt="Настоящий экран Тройки для Windows"><div class="slide"><small>ПРЕЗЕНТАЦИЯ · 1 / 3</small><h2>Работа стоит</h2><p>Проблема: не хватает ресурсов.<br>Решение: согласовать бюджет.<br>Следующий шаг: начать проект.</p></div></div><div class="filecard"><b>PPTX</b>　Предложение.pptx<small>3 слайда · сохранено на компьютере</small></div>'
        if k=='message': return f'<div class="hero-message" id="{sid}-device"><small>Шеф · новое сообщение</small>Короче.</div>'
        if k=='question': return phone('<div class="screen-title">Разговор</div>'+bubble('Оставь только суть.')+reply('Создаю новую версию<br>на один слайд…'),sid)
        if k=='budget': return f'<div class="budget-slide" id="{sid}-device"><small>НОВАЯ ВЕРСИЯ · 1 / 1</small>Нужен<br>бюджет</div>'
        if k=='approved': return f'<div class="hero-message" id="{sid}-device"><small>Шеф · новое сообщение</small>Согласовано.</div>'
    if e=='tabs':
        if k=='request': return phone('<div class="screen-title">Разговор</div>'+bubble('Как записать экран в Windows? Нужен официальный источник.')+reply('Ищу справку Microsoft…'),sid)
        if k=='source': return phone('<div class="screen-title">Нашла источник</div><div class="source"><small>support.microsoft.com</small>Запись экрана<br>в Windows 11<div class="keys"><b>Win</b>＋<b>Shift</b>＋<b>R</b></div></div>',sid)
        if k=='question': return phone('<div class="screen-title">Разговор</div>'+bubble('Собери короткую памятку.')+reply('Готовлю документ…'),sid)
        if k=='file': return f'<div class="desktop" id="{sid}-device"><img src="assets/windows-home.png" alt="Настоящий экран Тройки для Windows"><div class="slide"><small>ПАМЯТКА · WINDOWS 11</small><h2>Запись экрана</h2><p>1. Нажми Win + Shift + R.<br>2. Выбери область и начни запись.<br>3. Останови и сохрани видео.</p></div></div><div class="filecard"><b>DOCX</b>　Запись экрана.docx<small>Сохранено на компьютере</small></div>'
        if k=='punch': return f'<div id="{sid}-device"><div class="count">8</div><div class="count-note">вкладок и одна памятка</div></div>'
    raise ValueError((e,k))

def captions(text, duration, sid):
    words=text.split();parts=[];chunk=[]
    for word in words:
        chunk.append(word)
        if len(' '.join(chunk))>32 or word.endswith(('.', '?', '!')):
            parts.append(' '.join(chunk));chunk=[]
    if chunk: parts.append(' '.join(chunk))
    total=sum(len(p) for p in parts);at=.08;out=[]
    for i,p in enumerate(parts):
        d=duration*len(p)/total
        out.append(f'<div id="{sid}-cap-{i}" class="clip" data-start="{at:.3f}" data-duration="{d:.3f}" data-track-index="1" data-track-kind="captions"><div class="caption">{escape(p)}</div></div>')
        at+=d
    return ''.join(out)

def scene(ep,b):
    sid=ep['id']+'-'+b['id'];d=b['duration'];k=b['kind']
    title=escape(b['title']).replace('\n','<br>')
    visual=art(ep,b,sid)
    motion=f'''const tl=gsap.timeline({{paused:true}});
    tl.fromTo('#{sid}-device',{{scale:.92,x:0,y:40,rotationY:-9,rotationX:3,rotationZ:-3,transformPerspective:1500,transformOrigin:'50% 55%'}},{{scale:1,x:0,y:0,rotationY:5,rotationX:0,rotationZ:2,duration:.75,ease:'power3.out'}},0);
    tl.to('#{sid}-device',{{scale:1.13,x:-26,y:-48,rotationY:0,rotationZ:0,duration:1.05,ease:'power2.inOut'}},{max(.9,d*.43):.3f});'''
    if k in ('message','approved','budget','punch'):
        motion=f'''const tl=gsap.timeline({{paused:true}});tl.fromTo('#{sid}-device',{{scale:.82,y:50,rotationZ:-4}},{{scale:1,y:0,rotationZ:0,duration:.55,ease:'back.out(1.2)'}},0);'''
    if k=='end':
        motion=f'''const tl=gsap.timeline({{paused:true}});tl.fromTo('#{sid}-device',{{scale:.85,y:35,rotationZ:-6}},{{scale:1,y:0,rotationZ:0,duration:.7,ease:'power3.out'}},0);'''
    # All informational text holds still after a short scale-based entrance.
    if b['id'] not in ('bet','boss','seven'):
        motion+=f"tl.fromTo('#{sid}-headline',{{opacity:0,scale:.98}},{{opacity:1,scale:1,duration:.22,ease:'power2.out'}},.05);"
    motion+=f"tl.to({{p:0}},{{p:1,duration:{d},ease:'none'}},0);window.__timelines['{sid}']=tl;"
    demo='' if k=='end' else '<div class="demo-label">Демонстрация сценария</div>'
    return f'''<template><style>{CSS}</style><div id="root" data-composition-id="{sid}" data-width="1080" data-height="1920" data-duration="{d}" data-fps="30"><div class="scene"><h1 id="{sid}-headline" class="headline">{title}</h1><div class="stage" data-layout-allow-overflow>{visual}</div>{demo}</div>{captions(b.get('say',''),b.get('speechDuration',0),sid) if b.get('say') else ''}</div><script>{motion}</script></template>'''

def asset_copy(project):
    assets=project/'assets';(assets/'fonts').mkdir(parents=True,exist_ok=True)
    mapping={REPO/'design/troika-ui-2026-11-13/android-dark-390.png':'android-home.png',REPO/'design/troika-ui-2026-11-13/windows-dark-1280.png':'windows-home.png',REPO/'design/app-icon-20261115/icon-512-rounded.png':'icon.png',REPO/'brand/troika/fonts/GolosText-Variable.ttf':'fonts/GolosText-Variable.ttf',REPO/'advertising/overview-20261113/assets/OFL.txt':'fonts/OFL.txt'}
    for src,dst in mapping.items():shutil.copy2(src,assets/dst)
    gsap=ROOT/'assets/gsap.min.js'
    if project != ROOT: shutil.copy2(gsap,assets/'gsap.min.js')
    return assets

def audio(ep,assets):
    start=0
    for beat in ep['beats']:
        if beat.get('say'):
            path=ROOT/'materials/voice-final'/f"{ep['id']}-{beat['id']}.mp3"
            pace=1.1 if beat['voice']=='user' else 1.08
            filters=f'atempo={pace},highpass=f=75,equalizer=f=3000:t=q:w=1:g=2'
            raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-af',filters,'-ac','1','-ar',str(SR),'-f','f32le','-'])
            data=trim(np.frombuffer(raw,dtype='<f4').copy());data*=min(2,.12/max(.001,float(np.sqrt(np.mean(data**2)))))
            # The complete processed speech controls scene lengths.
            beat['speechDuration']=round(len(data)/SR,3)
            floor={'message':1.6,'budget':2.4,'source':3.1,'file':4.2}.get(beat['kind'],2.0)
            beat['duration']=math.ceil(max(floor,beat['speechDuration']+.4)*30)/30
            wav(assets/(ep['id']+'-'+beat['id']+'.wav'),data)
        else:beat['duration']=2.5
        beat['start']=round(start,6);start+=beat['duration']
    ep['duration']=round(start,6)
    bed=decode(REPO/'work/troika-cinematic-20261116/rising-forest.mp3',start=43,duration=start)
    bed=np.pad(bed,(0,max(0,round(start*SR)-len(bed))))[:round(start*SR)]
    bed*=.028/max(.001,float(np.sqrt(np.mean(bed**2))))
    # Duck the existing licensed music under speech; hold a comic pause before the reveal.
    for b in ep['beats']:
        if b.get('say'):
            a=round(b['start']*SR);z=min(len(bed),round((b['start']+b['duration'])*SR));bed[a:z]*=.55
        if b['kind'] in ('message','budget','punch'):
            a=round(b['start']*SR);z=min(len(bed),a+round(.4*SR));bed[a:z]*=.08
    ramp=np.minimum(np.arange(len(bed))/2400,1)*np.minimum((len(bed)-np.arange(len(bed)))/24000,1)
    wav(assets/'music.wav',bed*ramp)

def build():
    timelines=[]
    for ep in SPEC['episodes']:
        project=ROOT if ep['id']=='coffee' else ROOT/'episodes'/ep['id']
        project.mkdir(parents=True,exist_ok=True);assets=asset_copy(project);audio(ep,assets)
        comp=project/'compositions';comp.mkdir(exist_ok=True)
        hosts=[];audios=[]
        for b in ep['beats']:
            sid=ep['id']+'-'+b['id'];(comp/(sid+'.html')).write_text(scene(ep,b),encoding='utf-8')
            hosts.append(f'<div id="{sid}" class="clip" data-composition-id="{sid}" data-composition-src="compositions/{sid}.html" data-start="{b["start"]:.6f}" data-duration="{b["duration"]:.6f}" data-width="1080" data-height="1920" data-track-index="0" data-track-kind="graphics"></div>')
            if b.get('say'):audios.append(f'<audio id="audio-{sid}" class="clip" src="assets/{sid}.wav" data-start="{b["start"]+.08:.6f}" data-duration="{b["speechDuration"]}" data-track-index="2" data-volume="1"></audio>')
        duration=ep['duration']
        variables=json.dumps([{'id':'ground','type':'color','label':'Фон','default':'#0B0C10'},{'id':'ink','type':'color','label':'Текст','default':'#F4F5F7'},{'id':'accent','type':'color','label':'Акцент Тройки','default':'#3DDC97'}],ensure_ascii=False)
        html=f'''<!doctype html><html lang="ru" data-resolution="portrait" data-composition-variables='{variables}'><head><meta charset="utf-8"><meta name="viewport" content="width=1080,height=1920"><title>Тройка — {escape(ep['title'])}</title><script src="assets/gsap.min.js"></script><style>html,body{{margin:0;width:1080px;height:1920px;overflow:hidden;background:#0B0C10}}#root{{position:relative;width:1080px;height:1920px}}.clip{{position:absolute;inset:0}}:root{{--ground:#0B0C10;--ink:#F4F5F7;--accent:#3DDC97}}</style></head><body><div id="root" data-composition-id="main" data-start="0" data-duration="{duration}" data-width="1080" data-height="1920" data-fps="30">{''.join(hosts)}{''.join(audios)}<audio id="music" class="clip" src="assets/music.wav" data-start="0" data-duration="{duration}" data-track-index="3" data-volume="1"></audio></div><script>window.__timelines=window.__timelines||{{}};const tl=gsap.timeline({{paused:true}});tl.to({{p:0}},{{p:1,duration:{duration},ease:'none'}});window.__timelines.main=tl;</script></body></html>'''
        (project/'index.html').write_text(html,encoding='utf-8')
        if project!=ROOT:
            for name in ['hyperframes.json','package.json']:shutil.copy2(ROOT/name,project/name)
            (project/'meta.json').write_text(json.dumps({'name':'Troika '+ep['title'],'id':'troika-'+ep['id']},ensure_ascii=False),encoding='utf-8')
        (project/'timeline.json').write_text(json.dumps(ep,ensure_ascii=False,indent=2),encoding='utf-8')
        timelines.append(ep)
        print(ep['id'],duration,'seconds',round(duration*30),'frames',flush=True)
    (ROOT/'timelines.json').write_text(json.dumps(timelines,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':build()
