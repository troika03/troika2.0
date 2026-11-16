import argparse
import json
import subprocess
import wave
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
RATE = 48_000
FPS = 30
FRAMES = 882
SAMPLES_PER_FRAME = RATE // FPS
SOURCE = ROOT / "materials" / "deadline-voice"
PUBLIC = ROOT / "public"

# Reserve the gaps before Troika's jokes and silence for the title slide.
CUES = (
    ("01-hero-deadline", 0.10, 2.83, -0.08),
    ("02-troika-question", 3.05, 4.51, 0.08),
    ("03-hero-topic", 4.78, 7.17, -0.08),
    ("04-troika-joke", 7.75, 9.12, 0.08),
    ("05-hero-request", 9.39, 12.18, -0.08),
    ("06-troika-source", 12.45, 15.40, 0.08),
    ("07-troika-file", 15.74, 18.55, 0.08),
    ("08-hero-example", 18.94, 21.10, -0.08),
    ("09-troika-punch", 21.78, 23.34, 0.08),
)


def decode(path):
    raw = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(path), "-af", "highpass=f=75,lowpass=f=11500",
        "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-",
    ])
    return np.frombuffer(raw, dtype="<f4")


def trim(samples):
    block = RATE // 100
    rms = np.sqrt(np.mean(samples[:len(samples) // block * block].reshape(-1, block) ** 2, axis=1))
    spoken = np.flatnonzero(rms > max(0.0021, np.max(rms) * 0.023))
    if not len(spoken):
        raise ValueError("Speech take is silent")
    start = max(0, (spoken[0] - 3) * block)
    end = min(len(samples), (spoken[-1] + 6) * block)
    return samples[start:end]


def fit(samples, limit, identifier):
    speed = len(samples) / (RATE * limit)
    if speed > 1.42:
        raise ValueError(f"{identifier} needs a shorter take ({speed:.2f}×)")
    if speed > 1:
        raw = subprocess.check_output([
            "ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", "-",
            "-af", f"atempo={speed:.4f}", "-f", "f32le", "-",
        ], input=samples.tobytes())
        samples = np.frombuffer(raw, dtype="<f4")
    samples = samples[:round(RATE * limit)].copy()
    samples *= 0.135 / np.sqrt(np.mean(samples ** 2))
    magnitude = np.abs(samples)
    samples = np.sign(samples) * (np.minimum(magnitude, 0.45) + 0.35 * np.maximum(0, magnitude - 0.45))
    ramp_in = min(len(samples), round(0.012 * RATE))
    ramp_out = min(len(samples), round(0.038 * RATE))
    samples[:ramp_in] *= np.linspace(0, 1, ramp_in)
    samples[-ramp_out:] *= np.linspace(1, 0, ramp_out)
    return samples


def mouth_frames(samples, start, poses):
    peak = np.sqrt(np.mean(samples ** 2))
    last = start + len(samples)
    for frame in range(start // SAMPLES_PER_FRAME, (last + SAMPLES_PER_FRAME - 1) // SAMPLES_PER_FRAME):
        first = max(0, frame * SAMPLES_PER_FRAME - start)
        end = min(len(samples), (frame + 1) * SAMPLES_PER_FRAME - start)
        if end - first < SAMPLES_PER_FRAME // 3:
            continue
        volume = np.sqrt(np.mean(samples[first:end] ** 2))
        poses[frame] = 2 if volume > peak * 0.83 else int(volume > peak * 0.20)


def main():
    parser = argparse.ArgumentParser(description="Mix recorded dialogue and calculate the mouth poses.")
    parser.add_argument("--takes", type=Path, default=SOURCE, help="Directory containing the nine MP3 takes.")
    args = parser.parse_args()
    source = args.takes.resolve()
    mix = np.zeros((FRAMES * SAMPLES_PER_FRAME, 2))
    poses = [0] * FRAMES
    timing = []
    for name, start, end, pan in CUES:
        samples = fit(trim(decode(source / f"{name}.mp3")), end - start, name)
        first = round(start * RATE)
        angle = (pan + 1) * np.pi / 4
        mix[first:first + len(samples)] += samples[:, None] * [np.cos(angle), np.sin(angle)]
        mouth_frames(samples, first, poses)
        timing.append({"line": name, "start": start, "end": round(start + len(samples) / RATE, 4)})
        print(f"{name}: {timing[-1]['start']:.2f}–{timing[-1]['end']:.2f}s")
    mix *= 10 ** (-1.8 / 20) / np.max(np.abs(mix))
    with wave.open(str(PUBLIC / "deadline-voice.wav"), "wb") as track:
        track.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
        track.writeframes((mix * 32767).astype("<i2").tobytes())
    (PUBLIC / "deadline-mouth.json").write_text(json.dumps(poses, separators=(",", ":")), encoding="utf-8")
    (source / "timing.json").write_text(json.dumps(timing, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
