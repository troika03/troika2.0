"""Produce a continuous Russian narration, align the film and export the voiced cut."""
import argparse
import json
import re
import subprocess
from difflib import SequenceMatcher
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel
from scipy.io import wavfile

from render import portrait
from score import glass_score

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'local/continuous'
FPS = 30
SR = 48000
FRAMES = 1304
DURATION = FRAMES / FPS
CHAPTERS = json.loads((ROOT/'monologue.json').read_text('utf-8'))


def take():
    spec = spec_from_file_location('series_voice', ROOT.parent/'troika-hyperframes-20261117/voice.py')
    service = module_from_spec(spec)
    spec.loader.exec_module(service)
    text = ' '.join(part for chapter in CHAPTERS for part in chapter if part)
    service.SPEC['episodes'] = [{'id':'mono', 'beats':[{'id':'full','voice':'user','say':text}]}]
    service.OUT = OUT
    service.generate()


def ffmpeg(*args):
    subprocess.run(['ffmpeg','-y','-v','error',*map(str,args)],check=True)


def prepare_speech():
    source = OUT/'mono-full.mp3'
    seconds = float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(source)]))
    # Change pace once for the whole performance. All breaths stay in their original order.
    tempo = seconds/(DURATION-.60)
    filters = f'aresample={SR},rubberband=tempo={tempo:.3f}:pitch=0.87:formant=preserved,highpass=f=55,apad,atrim=end_sample={round(SR*DURATION)}'
    ffmpeg('-i',source,'-af',filters,'-ar',SR,'-ac',1,'-c:a','pcm_s24le',OUT/'voice.wav')


def norm(word):
    return re.sub(r'[^а-яa-z0-9]','',word.lower().replace('ё','е')).replace('0','ноль')


def timing(model_name):
    model = WhisperModel(model_name,device='cpu',compute_type='int8',cpu_threads=4)
    segments,_ = model.transcribe(str(OUT/'voice.wav'),language='ru',word_timestamps=True,beam_size=3)
    heard = [w for segment in segments for w in segment.words]
    tokens, lines, chapter_lines = [], [], []
    for chapter in CHAPTERS:
        chapter_lines.append(len(lines))
        for text in chapter[1:]:
            lines.append((len(tokens),text))
            tokens.extend(norm(word) for word in text.split() if norm(word))
    match = SequenceMatcher(None,tokens,[norm(w.word) for w in heard],autojunk=False)
    if match.ratio()<.84:
        raise ValueError('Transcription differs from the script. Review the take before rendering.')
    anchors = {a+i:heard[b+i].start for a,b,count in match.get_matching_blocks() for i in range(count)}
    known = sorted(anchors)
    word_starts = np.interp(np.arange(len(tokens)),known,[anchors[i] for i in known])
    caps = [[round(float(word_starts[pos]),3),text] for pos,text in lines]
    caps[0][0] = 0
    starts = [round(caps[index][0]*FPS)/FPS for index in chapter_lines]

    def word_start(chapter,line,word):
        index = lines[chapter_lines[chapter]+line][0]
        phrase = CHAPTERS[chapter][line+1].split()
        return float(word_starts[index+[norm(w) for w in phrase].index(norm(word))])

    events = {(3,1.96):word_start(3,0,'Когда'),(3,3.05):word_start(3,1,'Сегодня'),
              (4,1.45):caps[chapter_lines[4]+1][0],(7,1.65):caps[-1][0]-.18}
    data = dict(duration=DURATION,starts=starts,caps=caps,zeroAt=caps[chapter_lines[5]+2][0],
                events={f'{i},{n}':v for (i,n),v in events.items()})
    (OUT/'cuts.js').write_text('window.cut='+json.dumps(data,ensure_ascii=False)+';',encoding='utf-8')
    return data,events


def mix(data,events):
    music = glass_score(DURATION,data['starts'],data['caps'][1][0],events)
    secs = np.arange(len(music))/SR
    music *= np.interp(secs,[0,.08,DURATION-.65,DURATION],[.24,1,1,0])[:,None]
    wavfile.write(OUT/'score.wav',SR,music.astype(np.float32))
    graph = ('[0:a]pan=stereo|c0=c0|c1=c0[v];[v][1:a]amix=inputs=2:weights=\'1 0.36\':normalize=0,'
             f'loudnorm=I=-16:TP=-1.5:LRA=8,aresample={SR},apad,atrim=end_sample={round(DURATION*SR)},asetpts=N/SR/TB[a]')
    ffmpeg('-i',OUT/'voice.wav','-i',OUT/'score.wav','-filter_complex',graph,'-map','[a]','-c:a','pcm_s24le',OUT/'mix.wav')


def export():
    # The previous cut keeps its own captions and artwork entry point.
    html = (ROOT/'index.html').read_text('utf-8').replace('<meta charset="utf-8">','<meta charset="utf-8"><base href="../../">',1)
    html = html.replace('src="local/cuts.js"','src="local/continuous/cuts.js"')
    (OUT/'index.html').write_text(html,encoding='utf-8')
    portrait.root = portrait.local = OUT
    portrait.section(('monologue',range(FRAMES),True))
    ffmpeg('-i',OUT/'part-monologue.mp4','-i',OUT/'mix.wav','-map','0:v','-map','1:a','-c:v','copy',
           '-c:a','aac','-b:a','256k','-ar',SR,'-metadata:s:a:0','language=rus','-movflags','+faststart',
           ROOT/'Тройка — Живая озвучка.mp4')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--asr-model',default='base')
    args = parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if not (OUT/'mono-full.mp3').is_file():
        take()
    prepare_speech()
    cue_data, visual_events = timing(args.asr_model)
    mix(cue_data,visual_events)
    print('Chapter starts:',cue_data['starts'],flush=True)
    export()
