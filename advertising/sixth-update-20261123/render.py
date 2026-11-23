"""Render the portrait GSAP scene against the supplied ElevenLabs takes."""
import argparse
import json
import subprocess
from pathlib import Path
from urllib.request import urlretrieve
import wave

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import Error, sync_playwright


ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "local"
FPS = 30
SAMPLE_RATE = 48000
TAKE_DURATION = {1: 21.70, 2: 21.63}
GSAP_URL = "https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist/gsap.min.js"


def prepare_gsap():
    library = LOCAL / "gsap.min.js"
    if library.exists():
        return
    cached_library = ROOT.parent / "six-drafts" / "local" / library.name
    if cached_library.exists():
        library.write_bytes(cached_library.read_bytes())
    else:
        temp_library = library.with_suffix(".download")
        urlretrieve(GSAP_URL, temp_library)
        temp_library.replace(library)


def audio_samples(source):
    pcm = subprocess.check_output(
        ["ffmpeg", "-v", "error", "-i", str(source), "-f", "f32le", "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-"]
    )
    samples = np.frombuffer(pcm, dtype="<f4")
    if samples.size < SAMPLE_RATE * 20:
        raise ValueError(f"Source voice recording is too short: {source}")
    return samples


def voice_envelope(voice, frame_count):
    half_window = SAMPLE_RATE // 38
    envelope = []
    for i in range(frame_count):
        center = i * SAMPLE_RATE // FPS
        chunk = voice[max(0, center - half_window):center + half_window]
        envelope.append(float(np.sqrt(np.mean(chunk ** 2))) if chunk.size else 0)
    values = np.array(envelope)
    values = np.convolve(values, np.array([.18, .64, .18]), mode="same")
    reference = max(.01, np.quantile(values, .92))
    return np.minimum(1, (values / reference) ** .75).round(4).tolist()


def soundtrack(voice, take, frame_count):
    seconds = frame_count / FPS
    length = round(seconds * SAMPLE_RATE)
    clock = np.arange(length) / SAMPLE_RATE
    rng = np.random.default_rng(62)
    bed = np.zeros(length, dtype=np.float64)
    effects = np.zeros_like(bed)

    def tone(destination, start, duration, hz, volume, decay, end_hz=None, texture=0):
        begin = round(start * SAMPLE_RATE)
        count = min(round(duration * SAMPLE_RATE), length - begin)
        if count <= 0:
            return
        t = np.arange(count) / SAMPLE_RATE
        phase = 2 * np.pi * (hz * t + (end_hz - hz) * t ** 2 / (2 * duration)) if end_hz else 2 * np.pi * hz * t
        fade = (1 - np.exp(-t / .012)) * np.exp(-t / decay) * np.minimum(1, (count - np.arange(count)) / 320)
        signal = (1 - texture) * np.sin(phase) + texture * rng.standard_normal(count)
        destination[begin:begin + count] += volume * fade * signal

    beat = .52
    for index in range(32):
        start = .04 + beat * index
        if index % 2 == 0:
            tone(bed, start, .38, 82, .016, .12, 48)
        if index % 2 == 1:
            tone(bed, start + .025, .17, 190, .006, .048, 154, .33)
        if index % 4 in (0, 3):
            note = (110, 130.81, 98, 123.47)[(index // 4) % 4]
            tone(bed, start + .065, .43, note, .014, .17)
            tone(bed, start + .065, .35, note * 2, .004, .1)
    bed *= np.interp(clock, [0, .20, 15.75, 16.67, seconds], [.7, 1, .94, .0, .0])

    offset = 0 if take == 1 else -.08
    tone(effects, .12, .24, 280, .028, .065, 560)
    tone(effects, 3.62 + offset, .23, 350, .022, .066, 156, .21)
    tone(effects, 7.38, .17, 170, .018, .061, 370, .18)
    tone(effects, 9.69, .17, 280, .018, .059, 135, .17)
    tone(effects, 18.18 + offset, .16, 115, .031, .058, 42)
    tone(effects, 20.06 + offset, .26, 356, .021, .09, 560)

    mono = np.zeros(length)
    speech_count = min(length, voice.size)
    mono[:speech_count] = voice[:speech_count]
    stereo = np.column_stack((mono + bed + effects * .87, mono + bed * .87 + effects))
    pcm = np.int16(np.clip(stereo, -.999, .999) * 32767)
    path = LOCAL / f"mix-{take}.wav"
    with wave.open(str(path), "wb") as out:
        out.setparams((2, 2, SAMPLE_RATE, length, "NONE", "not compressed"))
        out.writeframes(pcm.tobytes())
    return path


def open_scene(browser, take, envelope, full_resolution):
    page = browser.new_page(
        viewport={"width": 540, "height": 960},
        device_scale_factor=2 if full_resolution else 1,
    )
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(f"window.voiceEnvelope = {json.dumps(envelope)};")
    page.goto(f"{(ROOT / 'index.html').as_uri()}?take={take}")
    page.evaluate("async () => { await document.fonts.ready; await Promise.all(Array.from(document.images, image => image.decode())); }")
    page.wait_for_function("Boolean(window.seekFrame) && document.fonts.check('650 25px Golos')")
    return page, errors


def check_caption(page, time):
    return page.evaluate(
        """(time) => [...document.querySelectorAll('.line')].flatMap((element) => {
            if (+getComputedStyle(element).opacity < 0.80) return [];
            const bounds = document.createRange();
            bounds.selectNodeContents(element);
            return [...bounds.getClientRects()].flatMap(rect =>
                rect.left < 14 || rect.right > 526 || rect.top < 30 || rect.bottom > 920
                ? [{ time, text: element.textContent, rect: rect.toJSON() }] : []);
        })""",
        time,
    )


def preview(browser, take, envelope):
    page, errors = open_scene(browser, take, envelope, False)
    stamps = [0, .7, 1.7, 2.4, 3.62, 4.1, 5.7, 6.8, 7.85, 8.8, 9.82, 10.55,
              12.1, 14.2, 15.55, 16.9, 17.55, 18.36, 18.8, 19.7, 20.6, 21.55]
    sheet = Image.new("RGB", (1080, 342 * ((len(stamps) + 5) // 6)), "#101412")
    draw = ImageDraw.Draw(sheet)
    cuts = []
    for index, time in enumerate(stamps):
        page.evaluate("(time) => window.seekFrame(time)", time)
        cuts.extend(check_caption(page, time))
        frame = LOCAL / f"preview-{take}-{round(time * 1000):05}.jpg"
        page.screenshot(path=str(frame), type="jpeg", quality=93)
        x, y = 180 * (index % 6), 342 * (index // 6)
        with Image.open(frame) as image:
            sheet.paste(image.resize((180, 320), Image.Resampling.LANCZOS), (x, y))
        draw.text((x + 8, y + 323), f"{time:.2f} s", fill="#bef1d9")
    sheet.save(LOCAL / f"review-{take}.jpg", quality=94)
    page.close()
    if errors or cuts:
        raise RuntimeError(f"Preview errors: {errors}, caption cuts: {cuts}")


def render(browser, take, voice, envelope, frame_count):
    page, errors = open_scene(browser, take, envelope, True)
    output = ROOT / f"Тройка — Шестое обновление — дубль {take}.mp4"
    temp = LOCAL / f"take-{take}.mp4"
    audio = soundtrack(voice, take, frame_count)
    command = [
        "ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(FPS),
        "-threads", "2", "-c:v", "mjpeg", "-i", "-", "-i", str(audio), "-map", "0:v:0",
        "-map", "1:a:0", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "4",
        "-preset", "veryfast", "-crf", "16", "-colorspace", "bt709", "-color_trc", "bt709",
        "-color_primaries", "bt709", "-af", "loudnorm=I=-14.5:TP=-1.5:LRA=7",
        "-ar", str(SAMPLE_RATE), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-t", f"{frame_count / FPS:.6f}", str(temp),
    ]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE)
    cuts = []
    try:
        for index in range(frame_count):
            time = index / FPS
            page.evaluate("(time) => window.seekFrame(time)", time)
            if index % 6 == 0:
                cuts.extend(check_caption(page, time))
            encoder.stdin.write(page.screenshot(type="jpeg", quality=94))
            if index % 120 == 0:
                print(f"Take {take}: {index}/{frame_count}", flush=True)
    finally:
        encoder.stdin.close()
        status = encoder.wait()
        page.close()
    if status or errors or cuts:
        raise RuntimeError(f"Encode exit {status}, browser errors {errors}, caption cuts {cuts}")
    temp.replace(output)
    print(output, flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", type=Path, action="append", required=True)
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    if not 1 <= len(args.voice) <= 2:
        parser.error("Pass one or two --voice recordings in take order.")
    LOCAL.mkdir(exist_ok=True)
    prepare_gsap()
    with sync_playwright() as playwright:
        flags = ["--allow-file-access-from-files", "--disable-dev-shm-usage"]
        try:
            browser = playwright.chromium.launch(channel="chrome", args=flags)
        except Error:
            browser = playwright.chromium.launch(args=flags)
        for take, track in enumerate(args.voice, 1):
            voice = audio_samples(track)
            frames = round(TAKE_DURATION[take] * FPS)
            if abs(frames / FPS - voice.size / SAMPLE_RATE) > .10:
                raise ValueError(f"Take {take} does not match the timing: {track}")
            envelope = voice_envelope(voice, frames)
            if args.preview:
                preview(browser, take, envelope)
            else:
                render(browser, take, voice, envelope, frames)
        browser.close()


if __name__ == "__main__":
    main()
