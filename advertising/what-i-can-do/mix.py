"""Finish the approved overview cut with its November 19 Gemini recording."""
from pathlib import Path
import json
import subprocess

root = Path(__file__).resolve().parent
assets = root / 'local'
cut = root / 'Что умеет Тройка — До доклада 5 минут.mp4'
final = root / 'Что умеет Тройка — До доклада 5 минут — Gemini.mp4'
cues = json.loads((root / 'cues.js').read_text(encoding='utf-8').split('=', 1)[1].strip().rstrip(';'))

# Start times checked against the actual Brio and Nika performance.
speech_starts = [
    0, 2.42, 5.18, 7.62, 10.80, 14.60, 19.08, 21.84, 26.34, 28.48,
    32.14, 35.42, 38.70, 40.80, 44.18, 46.62, 49.34, 54.36, 59.96,
    63.50, 66.62, 69.62, 72.94, 76.74, 80.14, 82.78,
]
duration = 86.5
anchors = [(cue[0], max(0, start - 0.12))
           for cue, start in zip(cues, speech_starts, strict=True)]
# Keep the opening file reveal quick and the closing caption legible before it is spoken.
anchors.insert(1, (1.20, 1.20))
anchors.extend([(81.20, 84.04), (81.70, 84.32), (82.08, 84.62), (84, duration)])

# Integrate each change of playback speed into one continuous timestamp map.
terms = []
previous_speed = 0
for (source, target), (next_source, next_target) in zip(anchors, anchors[1:]):
    speed = (next_target - target) / (next_source - source)
    terms.append(f'({speed - previous_speed:.8f})*max(0,PTS*TB-{source})')
    previous_speed = speed
video = "settb=AVTB,setpts='(" + '+'.join(terms) + ")/TB',fps=30,tpad=stop_mode=clone:stop_duration=0.2"
audio = (
    '[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0,apad[voices];'
    f'[2:a]aresample=48000,atempo={84/duration:.8f},volume=-9dB,apad[bed];'
    f'[voices][bed]amix=inputs=2:normalize=0,atrim=duration={duration},'
    'loudnorm=I=-16:TP=-1.5:LRA=8,aresample=48000[mix]'
)
subprocess.run([
    'ffmpeg', '-y', '-v', 'error', '-threads', '2', '-i', str(cut),
    '-i', str(assets / 'gemini-dialogue.wav'), '-i', str(assets / 'music.wav'),
    '-filter_complex_threads', '2', '-filter_complex', f'[0:v]{video}[picture];{audio}',
    '-map', '[picture]', '-map', '[mix]', '-t', str(duration),
    '-c:v', 'libx264', '-threads', '4', '-preset', 'veryfast', '-crf', '16',
    '-pix_fmt', 'yuv420p', '-colorspace', 'bt709', '-color_trc', 'bt709',
    '-color_primaries', 'bt709', '-c:a', 'aac', '-b:a', '192k',
    '-movflags', '+faststart', str(final),
], check=True)
