from pathlib import Path
import subprocess
import wave

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parent
RATE = 48_000
DURATION = 18
RNG = np.random.default_rng(45)


def wave_time(duration):
    return np.arange(round(duration * RATE)) / RATE


def fade(time, attack, release, duration):
    return np.clip(time / attack, 0, 1) * np.clip((duration - time) / release, 0, 1)


def put(mix, sound, start, position=0):
    index = round(start * RATE)
    count = min(len(sound), len(mix) - index)
    angle = (position + 1) * np.pi / 4
    mix[index:index + count] += sound[:count, None] * [np.cos(angle), np.sin(angle)]


def note(mix, freq, start, duration, gain, position):
    t = wave_time(duration)
    phase = 2 * np.pi * freq * t
    body = np.sin(phase + np.sin(phase * 2.01) * 0.53 * np.exp(-t * 5))
    overtone = 0.14 * np.sin(phase * 2.003) * np.exp(-t * 2.5)
    signal = (body + overtone) * fade(t, 0.012, 0.26, duration) * np.exp(-t * 2)
    put(mix, signal * gain, start, position)
    put(mix, signal * gain * 0.16, start + 0.13, -position)


def tick(mix, start, position, gain):
    t = wave_time(0.19)
    pulse = 0.7 * np.sin(2 * np.pi * 1280 * t) + 0.3 * RNG.normal(0, 1, len(t))
    put(mix, pulse * np.exp(-t * 51) * fade(t, 0.002, 0.026, 0.19) * gain, start, position)


def impact(mix, time, gain):
    t = wave_time(0.57)
    phase = 2 * np.pi * (44 * t + 2.1 * (1 - np.exp(-t * 17)))
    sound = np.sin(phase) * np.exp(-t * 9) * fade(t, 0.007, 0.095, 0.57)
    put(mix, sound * gain, time)


def sweep(mix, time, duration, gain):
    t = wave_time(duration)
    curves = np.sin(2 * np.pi * (157 * t + 249 * t ** 3))
    airy = RNG.normal(0, 1, len(t))
    airy = np.convolve(airy, np.ones(18) / 18, mode="same")
    put(mix, (airy * 1.5 + curves * 0.44) * fade(t, duration * 0.67, 0.08, duration) ** 2 * gain, time)


def read_voice(name):
    voice = ROOT / "materials" / name
    raw = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(voice), "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-",
    ])
    return np.frombuffer(raw, dtype=np.float32)


def speech(mix):
    request = read_voice("remind.mp3")
    wake = read_voice("wake.mp3")
    for source, first, last, start in [
        (wake, 0.72, 1.50, 3.19),
        (request, 0, 2.82, 4.34),
        (request, 2.97, 3.83, 8.73),
    ]:
        part = source[round(first * RATE):round(last * RATE)]
        duration = len(part) / RATE
        part = part * fade(wave_time(duration), 0.013, 0.072, duration)
        gain = min(1.35, 0.11 / np.sqrt(np.mean(part ** 2)))
        put(mix, part * gain, start)


def build():
    mix = np.zeros((DURATION * RATE, 2), dtype=np.float64)
    t = wave_time(DURATION)
    warmth = np.clip((3.22 - t) / 0.28, 0, 1)
    put(mix, np.sin(2 * np.pi * (47 * t + 0.14 * np.sin(t * 2))) * warmth
        * fade(t, 0.21, 0.8, DURATION) * 0.114, 0)
    for i, at in enumerate((0.11, 0.85, 1.59, 2.33, 2.87)):
        tick(mix, at, (-1) ** i * 0.25, 0.18 if i < 4 else 0.11)
    for i, freq in enumerate((73.42, 110, 146.83, 174.61, 220, 293.66)):
        duration = 15
        u = wave_time(duration)
        amplitude = fade(u, 1.2, 2.6, duration) * (0.75 + 0.25 * np.sin(2 * np.pi * 0.22 * u + i))
        duck = 1 - 0.36 * np.maximum(
            fade(u - 0.97, 0.26, 0.28, 3.3), fade(u - 5.42, 0.24, 0.22, 1.05),
        )
        put(mix, np.sin(2 * np.pi * freq * u + 0.2 * np.sin(2.2 * u + i))
            * amplitude * duck * (0.037 if i == 0 else 0.014), 3.15, (i / 5 - 0.5) * 1.55)
    for at, dur, gain in [(2.63, 0.62, 0.105), (8.31, 0.56, 0.061), (10.73, 0.55, 0.092), (13.58, 0.57, 0.076)]:
        sweep(mix, at, dur, gain)
    for at, gain in [(0, 0.14), (3.2, 0.23), (8.8, 0.13), (11.2, 0.1), (14.1, 0.16)]:
        impact(mix, at, gain)
    for at, freq, gain, position in [
        (3.89, 440, 0.075, -0.21),
        (4.02, 659.25, 0.052, 0.28),
        (7.21, 293.66, 0.062, -0.36),
        (7.55, 349.23, 0.048, 0.28),
        (8.87, 440, 0.065, -0.3),
        (9.04, 587.33, 0.068, 0.3),
        (11.22, 587.33, 0.125, -0.18),
        (11.37, 783.99, 0.11, 0.22),
        (12.11, 293.66, 0.059, -0.4),
        (12.81, 349.23, 0.054, 0.34),
        (14.13, 293.66, 0.114, -0.32),
        (14.27, 440, 0.086, 0.16),
        (14.49, 587.33, 0.088, 0.3),
        (15.35, 440, 0.039, -0.39),
    ]:
        note(mix, freq, at, 1.42, gain, position)
    speech(mix)
    mix *= fade(t, 0.013, 0.63, DURATION)[:, None]
    mix = np.tanh(1.48 * mix)
    mix *= 10 ** (-1.5 / 20) / np.max(np.abs(mix))
    with wave.open(str(ROOT / "public" / "soundtrack.wav"), "wb") as output:
        output.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
        output.writeframes((mix * 32767).astype("<i2").tobytes())
    texture = RNG.integers(32, 230, (180, 180), dtype=np.uint8)
    Image.fromarray(texture).save(ROOT / "public" / "grain.png")


if __name__ == "__main__":
    build()
