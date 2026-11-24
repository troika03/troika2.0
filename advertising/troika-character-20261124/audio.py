"""Assemble and score the ElevenLabs recordings with sample-accurate timing."""
import argparse
import json
from pathlib import Path
import subprocess
import wave

import numpy as np


ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "local"
RATE, FPS = 48000, 30
DIALOGUE = (
    ("dev", "Тройка, включи компьютер."),
    ("troika", "А тебя с кровати тоже голосом поднимать?"),
    ("dev", "Открой браузер и найди мне способы заработать денег."),
    ("troika", "Опять? Ты бы хотя бы один прошлый способ попробовал."),
    ("dev", "Ладно, включи музыку."),
    ("troika", "Наконец-то задача по твоим интеллектуальным возможностям."),
    ("dev", "Ты вообще мой помощник или кто?"),
    ("troika", "Помощник. Просто кто-то же должен говорить тебе правду."),
    ("dev", "Да пошла ты нахуй."),
    ("troika", "Взаимно. Чем ещё помочь?"),
)
GAPS = (.18, .24, .17, .30, .24, .27, .15, .25, .32, .37)


def transcribe():
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="cpu", compute_type="int8", local_files_only=True)
    for role in ("dev", "troika", "hook"):
        parts, _ = model.transcribe(
            str(LOCAL / f"{role}.mp3"), language="ru", word_timestamps=True,
            beam_size=5, condition_on_previous_text=False,
        )
        words = [
            {"start": word.start, "end": word.end, "word": word.word}
            for part in parts for word in part.words
        ]
        (LOCAL / f"asr-{role}.json").write_text(
            json.dumps(words, ensure_ascii=False, indent=2), encoding="utf8"
        )


def decode(role):
    path = LOCAL / f"{role}.mp3"
    return np.frombuffer(subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE),
        "-f", "f32le", "-",
    ]), dtype="<f4")


def sequence():
    boundaries = json.loads((ROOT / "segments.json").read_text(encoding="utf-8-sig"))
    speech = {speaker: decode(speaker) for speaker in ("dev", "troika", "hook")}
    next_segment = {"dev": 0, "troika": 0}
    clips, cues = [], []
    cursor = 0.05
    for index, (speaker, text) in enumerate(DIALOGUE):
        if index == 1:
            chunk = speech["hook"].astype(np.float64)
        else:
            left, right = boundaries[speaker][next_segment[speaker]]
            next_segment[speaker] += 1
            start, stop = round(left * RATE), round(right * RATE)
            if not 0 <= start < stop <= speech[speaker].size:
                raise ValueError(f"Invalid {speaker} boundaries: {left}–{right} s")
            chunk = speech[speaker][start:stop].astype(np.float64)
        active = np.quantile(np.abs(chunk), .83)
        chunk *= np.clip(.13 / max(active, .025), .65, 1.8)
        ramp = round(.012 * RATE)
        chunk[:ramp] *= np.linspace(0, 1, ramp)
        chunk[-ramp:] *= np.linspace(1, 0, ramp)
        offset = round(cursor * RATE)
        end = (offset + chunk.size) / RATE
        clips.append((offset, chunk))
        cues.append(dict(speaker=speaker, start=round(cursor, 4), end=round(end, 4), text=text))
        cursor = end + GAPS[index]
    outro = max(26.6, cursor)
    duration = round((outro + 3.8) * FPS) / FPS
    browser = cues[2]["end"] + .13
    beats = {
        "consent": cues[2]["start"] + .62, "browser": browser,
        "query": browser + .43, "results": browser + 1.33,
        "phone": cues[4]["start"], "play": cues[4]["end"] + .09,
        "argument": cues[6]["start"], "outro": round(outro, 4),
    }
    preview = sorted({
        0, 1.15, cues[1]["start"] + .50, cues[2]["start"] + .33,
        beats["consent"] + .34, browser + .85, beats["results"] + .30,
        cues[3]["end"] - .3, beats["phone"] + .52,
        beats["play"] - .19, beats["play"] + .34, cues[5]["start"] + .75,
        beats["argument"] + .66, cues[7]["start"] + .40, cues[8]["start"] + .45,
        cues[9]["start"] + .43, cues[9]["end"] - .42, outro + 1.25, duration - .1,
    })
    scene = dict(duration=duration, lines=cues, beats=beats, preview=preview)
    return clips, scene


def score_and_mix(clips, scene):
    length = round(scene["duration"] * RATE)
    voice = np.zeros(length, dtype=np.float64)
    for start, content in clips:
        voice[start:start + content.size] = content
    cursor = np.arange(length) / RATE
    bed = np.zeros_like(voice)
    effects = np.zeros_like(voice)
    rng = np.random.default_rng(404)
    beats, lines = scene["beats"], scene["lines"]

    def tone(layer, when, length_sec, hz, quota, envelope, bend=0, noise=0):
        start = round(when * RATE)
        size = min(round(length_sec * RATE), length - start)
        if size < 1:
            return
        t = np.arange(size) / RATE
        phase = 2 * np.pi * (hz * t + .5 * bend / length_sec * t * t)
        fade = (1 - np.exp(-t / .009)) * np.exp(-t / envelope)
        fade *= np.minimum(1, (size - np.arange(size)) / 380)
        sound = np.sin(phase)
        if noise:
            sound = (1 - noise) * sound + noise * rng.normal(0, .55, size)
        layer[start:start + size] += quota * fade * sound

    pulse = .48
    start, stop = beats["play"], beats["argument"]
    for index, clock in enumerate(np.arange(.11, scene["duration"], pulse)):
        playing = start <= clock < stop
        root = (82.41, 98, 73.42, 87.31)[(index // 4) % 4]
        volume = .025 if playing else .012
        if index % 2 == 0:
            tone(bed, clock, .29, 106, volume * .72, .086, -60)
            tone(bed, clock + .04, .39, root, volume * .57, .14)
        else:
            tone(bed, clock, .14, 298, volume * .38, .034, -92, .69)
        if playing or clock > beats["outro"]:
            tone(bed, clock + .10, .46, root * (4 if index % 2 else 2), volume * .45, .19)
    floor = np.interp(cursor, [
        0, stop - .28, stop + .28, lines[8]["start"] - .03,
        lines[8]["start"] + .13, lines[9]["start"] + .44, beats["outro"],
        beats["outro"] + .24, scene["duration"] - .36, scene["duration"],
    ], [.9, 1, .63, .60, 0, 0, .11, 1, .81, 0])
    bed *= floor

    tone(effects, .06, .22, 164, .035, .07, -89)
    tone(effects, beats["consent"], .19, 420, .025, .051, 92)
    tone(effects, beats["browser"], .26, 208, .034, .091, 126, .41)
    tone(effects, beats["results"], .17, 511, .021, .053, -160)
    tone(effects, beats["phone"], .33, 211, .029, .084, -94, .41)
    tone(effects, start, .31, 173, .054, .132, -94)
    tone(effects, stop, .16, 228, .024, .059, -104, .22)
    tone(effects, beats["outro"] + .18, .49, 220, .034, .138)
    tone(effects, beats["outro"] + .26, .45, 329.63, .021, .173)
    stereo = np.column_stack((voice + bed + effects * .93, voice + bed * .88 + effects))
    target = LOCAL / "mix-raw.wav"
    with wave.open(str(target), "wb") as out:
        out.setparams((2, 2, RATE, length, "NONE", "not compressed"))
        out.writeframes(np.int16(np.clip(stereo, -.999, .999) * 32767).tobytes())
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(target), "-af", "loudnorm=I=-14.5:TP=-1.6:LRA=7,apad",
        "-ar", str(RATE), "-t", str(scene["duration"]), "-c:a", "pcm_s24le",
        str(LOCAL / "voice-master.wav"),
    ], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcribe", action="store_true")
    if parser.parse_args().transcribe:
        transcribe()
        return
    clips, scene = sequence()
    score_and_mix(clips, scene)
    (LOCAL / "cues.js").write_text(
        "window.renderCues = " + json.dumps(scene, ensure_ascii=False, indent=2) + ";\n",
        encoding="utf8",
    )
    for cue in scene["lines"]:
        print(f"{cue['start']:.2f}–{cue['end']:.2f}  {cue['speaker']}  {cue['text']}")
    print(f"Duration: {scene['duration']:.2f}s")


if __name__ == "__main__":
    main()
