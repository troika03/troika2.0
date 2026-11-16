from pathlib import Path
import subprocess
import wave

import numpy as np


ROOT = Path(__file__).resolve().parent
RATE = 48_000
DURATION = 28.8
RNG = np.random.default_rng(42)
SPEECH = [
    ("hook", 0.12, 4.04),
    ("light", 4.37, 1.96),
    ("light-reply", 6.79, 1.82),
    ("search", 9.13, 3.77),
    ("search-reply", 13.13, 2.22),
    ("slides", 15.76, 2.87),
    ("slides-reply", 20.04, 2.24),
    ("end", 22.55, 6.01),
]


def times(duration):
    return np.arange(round(duration * RATE)) / RATE


def fade(t, length, attack=0.012, release=0.18):
    return np.clip(t / attack, 0, 1) * np.clip((length - t) / release, 0, 1)


def place(mix, samples, start, pan=0):
    begin = round(start * RATE)
    count = min(len(samples), len(mix) - begin)
    angle = (pan + 1) * np.pi / 4
    mix[begin:begin + count] += samples[:count, None] * [np.cos(angle), np.sin(angle)]


def decode(name):
    extension = "wav" if name.endswith("-reply") else "mp3"
    file = ROOT / "materials" / "voice" / f"{name}.{extension}"
    raw = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(file), "-af", "highpass=f=80,lowpass=f=9800",
        "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-",
    ])
    return np.frombuffer(raw, dtype="<f4")


def speech():
    takes = []
    for name, start, limit in SPEECH:
        audio = decode(name)
        block = RATE // 100
        rms = np.sqrt(np.mean(audio[:len(audio) // block * block].reshape(-1, block) ** 2, axis=1))
        voiced = np.flatnonzero(rms > max(0.0032, np.max(rms) * 0.024))
        if not len(voiced):
            raise ValueError(f"No voice detected in {name}")
        sample = audio[max(0, (voiced[0] - 4) * block):min(len(audio), (voiced[-1] + 5) * block)]
        tempo = len(sample) / (RATE * limit)
        if tempo > 1:
            compressed = subprocess.check_output([
                "ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(RATE), "-ac", "1", "-i", "-",
                "-af", f"atempo={tempo:.4f}", "-f", "f32le", "-",
            ], input=sample.tobytes())
            sample = np.frombuffer(compressed, dtype="<f4")[:round(limit * RATE)]
        length = len(sample) / RATE
        sample = sample * fade(times(length), length, 0.015, 0.04)
        takes.append((name, start, sample * 0.107 / np.sqrt(np.mean(sample ** 2))))
    return takes


def pluck(mix, midi, start, gain, pan, length=0.67):
    t = times(length)
    hz = 440 * 2 ** ((midi - 69) / 12)
    phase = 2 * np.pi * hz * t
    body = np.sin(phase + np.sin(phase * 2.003) * np.exp(-t * 8))
    halo = 0.17 * np.sin(phase * 0.997) + 0.13 * np.sin(phase * 3.01) * np.exp(-t * 12)
    clip = (body + halo) * np.exp(-t * 4.7) * fade(t, length) * gain
    place(mix, clip, start, pan)
    place(mix, clip * 0.12, start + 0.154, -pan)


def drum(mix, start, gain, pan, high=False):
    length = 0.08 if high else 0.31
    t = times(length)
    if high:
        noise = RNG.normal(0, 1, len(t) + 1)
        body = np.diff(noise) * 0.27
    else:
        body = np.sin(2 * np.pi * (44 * t + 2.12 * (1 - np.exp(-t * 23))))
    place(mix, body * np.exp(-t * (39 if high else 13)) * fade(t, length, 0.007, 0.026)
          * gain, start, pan)


def rise(mix, start, length, gain, pan):
    t = times(length)
    airy = np.convolve(RNG.normal(0, 1, len(t)), np.ones(15) / 15, mode="same")
    sine = np.sin(2 * np.pi * (175 * t + 592 * t ** 3))
    clip = (airy * 0.85 + sine * 0.26) * fade(t, length, length * 0.61, 0.08) ** 2
    place(mix, clip * gain, start, pan)


def music(mix):
    bars = [45, 45, 48, 43, 45, 48, 41, 43, 45, 48, 41, 43]
    steps = [(0, 0, 0.058), (0.47, 12, 0.033), (0.79, 19, 0.036),
             (1.14, 15, 0.033), (1.59, 19, 0.029), (1.89, 12, 0.03)]
    for index, base in enumerate(bars):
        start = 0.12 + index * 2.32
        for offset, value, gain in steps:
            pluck(mix, base + value, start + offset, gain, 0.24 if offset > 1 else -0.22)
        for offset, gain in [(0, 0.08), (1.15, 0.064), (1.74, 0.036)]:
            drum(mix, start + offset, gain, 0)
        for offset in (0.31, 0.86, 1.42, 2.03):
            drum(mix, start + offset, 0.021, 0.39, high=True)


def foley(mix):
    for start, duration, gain, pan in [
        (3.99, 0.34, 0.10, 0.22), (6.16, 0.31, 0.11, -0.16),
        (8.69, 0.35, 0.09, 0.18), (12.77, 0.32, 0.074, -0.15),
        (15.29, 0.36, 0.084, 0.3), (18.28, 0.43, 0.12, -0.2),
        (22.09, 0.41, 0.11, 0.24),
    ]:
        rise(mix, start, duration, gain, pan)
    for at, midi, gain, pan in [
        (4.69, 76, 0.052, -0.2), (6.45, 84, 0.088, 0.07), (6.57, 88, 0.062, -0.29),
        (13.04, 79, 0.095, 0.24), (13.17, 84, 0.059, -0.16),
        (18.67, 60, 0.087, -0.31), (18.88, 64, 0.084, 0.14), (19.10, 67, 0.089, 0.34),
        (20.13, 79, 0.090, 0.02), (22.51, 60, 0.071, -0.33),
        (22.68, 67, 0.072, 0.2), (22.81, 72, 0.074, 0.31),
    ]:
        pluck(mix, midi, at, gain, pan)


def main():
    t = times(DURATION)
    bed = np.zeros((len(t), 2))
    mix = np.zeros_like(bed)
    music(bed)
    foley(mix)
    duck = np.ones(len(t))
    for name, at, take in speech():
        length = len(take) / RATE
        duck -= 0.53 * fade(t - at + 0.10, length + 0.32, 0.095, 0.2)
        place(mix, take, at, 0.10 if name.endswith("-reply") else -0.07)
        print(f"{name}: {at:.2f} to {at + length:.2f}s")
    mix = np.tanh(2.2 * (mix + bed * duck[:, None]))
    mix *= fade(t, DURATION, 0.019, 0.41)[:, None]
    mix *= 10 ** (-1.5 / 20) / np.max(np.abs(mix))
    with wave.open(str(ROOT / "public" / "soundtrack.wav"), "wb") as output:
        output.setparams((2, 2, RATE, 0, "NONE", "not compressed"))
        output.writeframes((mix * 32767).astype("<i2").tobytes())


if __name__ == "__main__":
    main()
