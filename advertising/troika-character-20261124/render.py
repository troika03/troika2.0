"""Frame-by-frame preview and export of the Troika GSAP sequence."""

import argparse
import base64
from io import BytesIO
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from urllib.request import urlretrieve

import numpy as np
from PIL import Image, ImageDraw
from playwright.sync_api import Error, sync_playwright


ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "local"
OUTPUT = ROOT / "Тройка — Когда твой ИИ уже охренел.mp4"
FPS = 30
SAMPLE_RATE = 48000
GSAP_URL = "https://cdn.jsdelivr.net/npm/gsap@3.13.0/dist/gsap.min.js"


def prepare_gsap():
    library = LOCAL / "gsap.min.js"
    if library.is_file():
        return
    for project in ("sixth-update-20261123", "six-drafts"):
        cached = ROOT.parent / project / "local" / library.name
        if cached.is_file():
            library.write_bytes(cached.read_bytes())
            return
    download = library.with_suffix(".download")
    urlretrieve(GSAP_URL, download)
    download.replace(library)


def voice_envelope(source):
    pcm = subprocess.check_output([
        "ffmpeg", "-v", "error", "-i", str(source), "-f", "f32le", "-ac", "1",
        "-ar", str(SAMPLE_RATE), "-",
    ])
    voice = np.frombuffer(pcm, dtype="<f4")
    if voice.size == 0:
        raise ValueError(f"The soundtrack contains no audio samples: {source}")
    samples_per_frame = SAMPLE_RATE // FPS
    width = round(SAMPLE_RATE / 38)
    values = []
    for center in range(0, voice.size, samples_per_frame):
        chunk = voice[max(0, center - width):center + width]
        values.append(float(np.sqrt(np.mean(chunk ** 2))))
    level = np.convolve(values, [.18, .64, .18], mode="same")
    reference = max(.01, np.quantile(level, .92))
    return np.minimum(1, (level / reference) ** .75).round(4).tolist()


def open_scene(browser, envelope, full_resolution):
    page = browser.new_page(
        viewport={"width": 540, "height": 960},
        device_scale_factor=2 if full_resolution else 1,
    )
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(f"window.voiceEnvelope = {json.dumps(envelope)};")
    page.goto((ROOT / "index.html").as_uri())
    page.evaluate("""async () => {
        await document.fonts.ready;
        await Promise.all(Array.from(document.images, image => image.decode()));
        const missing = [...document.fonts].filter(font => font.status === 'error');
        if (missing.length) throw new Error(`Could not load fonts: ${missing.map(font => font.family)}`);
    }""")
    page.wait_for_function("typeof window.seekFrame === 'function'", timeout=10000)
    scene = page.evaluate("""() => ({
        duration: Number(document.querySelector('#root')?.dataset.duration || window.renderCues?.duration),
        stamps: window.renderCues?.preview || [],
    })""")
    if errors:
        raise RuntimeError(f"Scene errors: {errors}")
    duration = scene["duration"]
    if not duration or not np.isfinite(duration) or duration <= 0:
        raise ValueError("Set the timeline length in #root[data-duration] or window.renderCues.duration")
    return page, errors, duration, scene["stamps"]


def preview(page, duration, stamps):
    last = max(0, (round(duration * FPS) - 1) / FPS)
    cuts = stamps or np.linspace(0, last, 20).tolist()
    stamps = sorted({0, last, *(min(last, max(0, float(time))) for time in cuts)})
    cols, width, height, cell = 5, 200, 356, 379
    rows = (len(stamps) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * width, rows * cell), "#101412")
    draw = ImageDraw.Draw(sheet)
    for index, time in enumerate(stamps):
        page.evaluate("time => window.seekFrame(time)", time)
        capture = page.screenshot(type="jpeg", quality=93)
        x, y = width * (index % cols), cell * (index // cols)
        with Image.open(BytesIO(capture)) as image:
            sheet.paste(image.resize((width, height), Image.Resampling.LANCZOS), (x, y))
        draw.text((x + 8, y + height + 5), f"{time:.2f} s", fill="#bef1d9")
    target = LOCAL / "review.jpg"
    sheet.save(target, quality=94)
    return target


def verify_export(path, frame_count):
    raw = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path),
    ])
    streams = json.loads(raw)["streams"]
    video = next(stream for stream in streams if stream["codec_type"] == "video")
    audio = next(stream for stream in streams if stream["codec_type"] == "audio")
    if (video["codec_name"], video["width"], video["height"], video["r_frame_rate"], int(video["nb_frames"])) != (
        "h264", 1080, 1920, "30/1", frame_count,
    ):
        raise RuntimeError("Export video does not match the requested geometry or frame count")
    if (audio["codec_name"], audio["channels"]) != ("aac", 2):
        raise RuntimeError("Export does not contain stereo AAC audio")
    tolerance = 1 / FPS
    if abs(float(audio["duration"]) - frame_count / FPS) > tolerance:
        raise RuntimeError("Audio and video durations do not match")
    subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"], check=True)


def render(page, source, duration, target):
    frame_count = round(duration * FPS)
    command = [
        "ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(FPS),
        "-threads", "2", "-c:v", "mjpeg", "-i", "-", "-i", str(source), "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "4", "-preset", "veryfast", "-crf", "16",
        "-colorspace", "bt709", "-color_trc", "bt709", "-color_primaries", "bt709",
        "-af", "apad", "-ar", str(SAMPLE_RATE), "-ac", "2", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-t", f"{frame_count / FPS:.6f}", str(target),
    ]
    session = page.context.new_cdp_session(page)
    options = {
        "format": "jpeg", "quality": 94, "optimizeForSpeed": True,
        "clip": {"x": 0, "y": 0, "width": 540, "height": 960, "scale": 2},
    }
    with subprocess.Popen(command, stdin=subprocess.PIPE) as encoder:
        try:
            for frame in range(frame_count):
                page.evaluate("time => { window.seekFrame(time); }", frame / FPS)
                data = session.send("Page.captureScreenshot", options)["data"]
                encoder.stdin.write(base64.b64decode(data))
                if frame % 120 == 0:
                    print(f"Rendered {frame}/{frame_count} frames", flush=True)
        finally:
            encoder.stdin.close()
        if encoder.wait():
            raise RuntimeError("FFmpeg failed while encoding the portrait master")
    verify_export(target, frame_count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", type=Path, required=True, help="The finished master soundtrack")
    parser.add_argument("--preview", action="store_true", help="Write a review sheet instead of the MP4")
    args = parser.parse_args()
    if not args.voice.is_file():
        parser.error(f"Soundtrack not found: {args.voice}")
    LOCAL.mkdir(exist_ok=True)
    prepare_gsap()
    envelope = voice_envelope(args.voice)
    with sync_playwright() as playwright:
        flags = ["--allow-file-access-from-files", "--disable-dev-shm-usage"]
        try:
            browser = playwright.chromium.launch(channel="chrome", args=flags)
        except Error:
            browser = playwright.chromium.launch(args=flags)
        try:
            page, errors, duration, stamps = open_scene(browser, envelope, not args.preview)
            if args.preview:
                output = preview(page, duration, stamps)
                if errors:
                    raise RuntimeError(f"Scene errors: {errors}")
            else:
                with TemporaryDirectory(dir=LOCAL, prefix="render-") as work:
                    temp = Path(work) / "movie.mp4"
                    render(page, args.voice, duration, temp)
                    if errors:
                        raise RuntimeError(f"Scene errors: {errors}")
                    temp.replace(OUTPUT)
                output = OUTPUT
            print(output, flush=True)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
