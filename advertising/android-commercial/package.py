"""Package the rendered film and a portable Shotcut timeline."""
from pathlib import Path
import csv
import importlib.util
import json
import shutil
import subprocess
from xml.etree import ElementTree as E
import zipfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('troika_film',HERE/'render.py')
film=importlib.util.module_from_spec(spec);spec.loader.exec_module(film)
OUT=film.OUT
MASTER='Troika-Android-25s-1080x1920-60fps.mp4'


def prop(node,name,value): E.SubElement(node,'property',{'name':name}).text=str(value)


def shotcut():
    root=E.Element('mlt',{'LC_NUMERIC':'C','producer':'tractor','version':'7.24.0'})
    E.SubElement(root,'profile',{'description':'Troika Android vertical','width':'1080','height':'1920','frame_rate_num':'60','frame_rate_den':'1','progressive':'1','sample_aspect_num':'1','sample_aspect_den':'1','display_aspect_num':'9','display_aspect_den':'16','colorspace':'709'})
    black=E.SubElement(root,'producer',{'id':'black','in':'0','out':'1499'})
    prop(black,'resource','0');prop(black,'mlt_service','color');prop(black,'mlt_image_format','rgba');prop(black,'eof','pause')
    bg=E.SubElement(root,'playlist',{'id':'background'})
    E.SubElement(bg,'entry',{'producer':'black','in':'0','out':'1499'})
    for ident,resource,audio in [('video',MASTER,False),('music','audio/music.wav',True),('sfx','audio/interaction-sfx.wav',True)]:
        ch=E.SubElement(root,'chain',{'id':ident,'in':'0','out':'1499'})
        prop(ch,'resource',resource);prop(ch,'mlt_service','avformat');prop(ch,'eof','pause')
        prop(ch,'set.test_image' if audio else 'set.test_audio','1')
        prop(ch,'shotcut:producer',1)
    for ident,title,producer in [('a1','Музыка','music'),('a2','Касания и свайпы','sfx')]:
        pl=E.SubElement(root,'playlist',{'id':ident})
        prop(pl,'shotcut:name',title);prop(pl,'shotcut:trackHeight',64);prop(pl,'shotcut:trackAudio',1)
        E.SubElement(pl,'entry',{'producer':producer,'in':'0','out':'1499'})
    video=E.SubElement(root,'playlist',{'id':'v1'})
    prop(video,'shotcut:name','Android · сцены');prop(video,'shotcut:trackHeight',100)
    for s in film.PROJECT['scenes']:
        E.SubElement(video,'entry',{'producer':'video','in':str(round(s['start']*60)),'out':str(round(s['end']*60)-1)})
    tractor=E.SubElement(root,'tractor',{'id':'tractor','shotcut':'1','in':'0','out':'1499'})
    prop(tractor,'shotcut',1);prop(tractor,'shotcut:projectAudioChannels',2)
    for ident in ['background','a1','a2','v1']:E.SubElement(tractor,'track',{'producer':ident})
    for b in [1,2]:
        tr=E.SubElement(tractor,'transition',{'in':'0','out':'1499'})
        prop(tr,'mlt_service','mix');prop(tr,'a_track',0);prop(tr,'b_track',b);prop(tr,'always_active',1);prop(tr,'sum',1)
    E.indent(root)
    E.ElementTree(root).write(OUT/'Troika-Android-editable.mlt',encoding='utf-8',xml_declaration=True)


def package():
    shotcut()
    for n in ['render.py','project.json','README.md','package.py']:
        if (HERE/n).resolve() != (OUT/n).resolve():
            shutil.copy2(HERE/n,OUT/n)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(OUT/MASTER),'-vf','scale=540:960','-c:v','libx264','-crf','23','-preset','fast','-threads','4','-c:a','aac','-b:a','160k','-movflags','+faststart',str(OUT/'Troika-Android-preview.mp4')],check=True)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(OUT/MASTER)]))
    (OUT/'media-info.json').write_text(json.dumps(probe,ensure_ascii=False,indent=2),encoding='utf-8')
    video=next(s for s in probe['streams'] if s['codec_type']=='video')
    sound=next(s for s in probe['streams'] if s['codec_type']=='audio')
    measured=subprocess.run(['ffmpeg','-hide_banner','-nostats','-i',str(OUT/MASTER),'-af','loudnorm=I=-16:TP=-1.5:LRA=8:print_format=json','-f','null','-'],capture_output=True,text=True,encoding='utf-8',errors='replace',check=True).stderr
    loudness=json.loads(measured[measured.rfind('{'):measured.rfind('}')+1])
    checks={'1080x1920':(video['width'],video['height'])==(1080,1920),'60fps':video['avg_frame_rate']=='60/1','1500_frames':int(video['nb_frames'])==1500,'25_seconds':abs(float(probe['format']['duration'])-25)<.05,'H264':video['codec_name']=='h264','AAC':sound['codec_name']=='aac','stereo_48k':sound['channels']==2 and sound['sample_rate']=='48000','true_peak_below_minus_1_5_dBTP':float(loudness['input_tp'])<=-1.5}
    report={'source':film.PROJECT['source_kind'],'checks':checks,'loudness':loudness,'visual_review':'Просмотрены 12 кадров, включая голос, свайп, ввод, создание проекта, напоминание и финал.','listening_review':'Прослушивание человеком не подтверждено; громкость измерена, события привязаны к временной шкале.','realism_score':{'узнаваемость_товара':2,'физическая_правдоподобность':1,'ясность_сообщения':2,'монтаж_и_звук':1,'факты_и_текст':2,'total':8,'out_of':10},'limits':['Анимация макетов, не запись релизного APK.','Нет неподтверждённых плеера, погоды, редактора кода или предпросмотра сайта.','Скорость монтажа не является замером скорости API.','Проект Shotcut сформирован в MLT; открытие в установленном Shotcut не проверено.']}
    if not all(checks.values()): raise RuntimeError('The rendered film failed media checks: '+str(checks))
    (OUT/'quality-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for filename,fields in [('SHOT_LIST.csv',['ID','start','end','scene','source']),('TIMELINE.csv',['ID','start','end','scene','source'])]:
        with (OUT/filename).open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.writer(f);writer.writerow(fields)
            for i,s in enumerate(film.PROJECT['scenes'],1):writer.writerow([f'S{i:02}',s['start'],s['end'],s['name'],'assets/'+s['screen']+'.svg'])
    (OUT/'ASSET_CHECKLIST.md').write_text('Все используемые исходные экраны, логотип, шрифт, клавиатура и звуковые дорожки включены.\n\nДля восстановления исходных сцен с плеером, погодной карточкой и редактором кода нужны подлинные Android-экспорты этих экранов и подтверждение поддерживаемых взаимодействий. Эти сцены в данной версии не заявлены.\n',encoding='utf-8')
    (OUT/'EXPORT.json').write_text(json.dumps({'width':1080,'height':1920,'fps':60,'seconds':25,'frames':1500,'video':'H.264 High, yuv420p','audio':'AAC, stereo, 48000 Hz, 256 kbps','loudness_LUFS':loudness['input_i'],'true_peak_dBTP':loudness['input_tp']},ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'captions.srt').write_text('1\n00:00:22,650 --> 00:00:25,000\nТройка. От просьбы к действию.\n',encoding='utf-8')
    (OUT/'preview.html').write_text('''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Тройка — ролик</title><style>body{margin:0;background:#0c0b0a;color:#f3f0ea;font:16px Arial;text-align:center}video{display:block;max-height:88vh;max-width:100%;margin:20px auto}a{color:inherit}p{margin:20px}</style><video controls playsinline poster="poster.jpg" src="Troika-Android-25s-1080x1920-60fps.mp4"></video><p>25 с · 1080 × 1920 · 60 fps</p><p>Анимация исходных Android-макетов. Демонстрационные данные.</p><p><a href="Troika-Android-editable.mlt">Проект Shotcut</a> · <a href="README.md">Исходники и монтаж</a></p></html>''',encoding='utf-8')
    archive=OUT.parent/'Troika-Android-Commercial-Editable.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(OUT.rglob('*')):
            if p.is_file() and p.suffix not in ['.tmp'] and 'revision' not in p.relative_to(OUT).parts:
                z.write(p,Path('Troika-Android-Commercial')/p.relative_to(OUT))
    print(archive,flush=True)


if __name__=='__main__':package()
