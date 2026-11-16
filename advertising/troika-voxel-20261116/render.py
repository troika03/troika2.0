import argparse
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import subprocess
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent
FPS = 30
EPISODES = {
    "five-minutes": (984, "Troika-Five-Minutes-3D.mp4", (24, 96, 175, 271, 335, 445, 546, 633, 738, 796, 850, 930)),
    "deadline": (882, "Troika-Deadline-3D.mp4", (22, 101, 171, 244, 309, 419, 503, 587, 671, 742, 779, 845)),
}
IMAGES = ("android-home.png", "windows-home.png", "app-icon.png", "wordmark-white.svg")
VOICE = ROOT / "public" / "deadline-voice.wav"
VOICE_FILES = (VOICE.name, "deadline-mouth.json")
HTML = b'''<!doctype html><html lang="ru"><meta charset="utf-8">
<title>Troika Motion</title><link rel="stylesheet" href="/work/preview.css">
<style>html,body,#root{margin:0;width:100%;height:100%;overflow:hidden;background:#0b0c10}</style>
''' + "".join(f'<img hidden src="/public/{asset}">' for asset in IMAGES).encode() + b'''
<div id="root"></div><script src="/work/preview.js"></script>'''


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(HTML)))
            self.end_headers()
            self.wfile.write(HTML)
            return
        allowed = ("/work/preview.js", "/work/preview.css")
        if path in allowed or path.startswith("/public/"):
            super().do_GET()
            return
        if path[1:] in (*IMAGES, *VOICE_FILES):
            self.path = "/public" + path
            super().do_GET()
            return
        self.send_error(404)


@contextmanager
def server():
    handler = partial(Handler, directory=ROOT)
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as http:
        thread = Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{http.server_port}"
        finally:
            http.shutdown()
            thread.join()


def browser_path():
    if os.environ.get("TROIKA_BROWSER"):
        return os.environ["TROIKA_BROWSER"]
    for location in (
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
    ):
        if Path(location).is_file():
            return location
    return None


def bundle():
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    subprocess.run([npm, "run", "bundle"], cwd=ROOT, check=True)


def ready(page, url, query):
    page.goto(f"{url}?capture&{query}", wait_until="networkidle")
    page.wait_for_function("typeof window.seek === 'function'")
    page.evaluate("""async () => {
        await document.fonts.load('700 50px Golos', 'Тройка');
        if (!document.fonts.check('700 50px Golos', 'Тройка')) {
            throw Error('Golos Text failed to load');
        }
        await Promise.all([...document.images].map(image => image.decode()));
    }""")
    page.wait_for_function(
        "document.querySelector('canvas[data-ready],canvas[data-error]')",
        timeout=30_000,
    )
    error = page.locator("canvas").get_attribute("data-error")
    if error:
        raise RuntimeError(error)


def grab(page, frame, quality=96):
    page.evaluate(
        """frame => new Promise(resolve => {
            window.seek(frame);
            requestAnimationFrame(() => requestAnimationFrame(resolve));
        })""",
        frame,
    )
    return page.screenshot(type="jpeg", quality=quality, timeout=20_000)


def encode(page, output, start, end, voiced):
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-n",
        "-f", "image2pipe", "-vcodec", "mjpeg", "-framerate", str(FPS), "-i", "-",
    ]
    if voiced:
        command.extend(["-ss", f"{start / FPS:.6f}", "-i", str(VOICE)])
    command.extend([
        "-map", "0:v", "-c:v", "libx264", "-preset", "fast", "-crf", "17",
        "-filter:v", "scale=out_range=tv", "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
    ])
    command.extend(["-map", "1:a", "-c:a", "aac", "-b:a", "192k"] if voiced else ["-an"])
    command.extend(["-t", f"{(end - start + 1) / FPS:.6f}", "-movflags", "+faststart", str(output)])
    with subprocess.Popen(command, stdin=subprocess.PIPE) as encoder:
        for frame in range(start, end + 1):
            encoder.stdin.write(grab(page, frame))
            if (frame - start) % 60 == 0:
                print(f"{frame - start + 1}/{end - start + 1}", flush=True)
        encoder.stdin.close()
        if encoder.wait():
            raise RuntimeError("FFmpeg could not finish encoding")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", choices=EPISODES, default="five-minutes")
    parser.add_argument("--voiced", action="store_true", help="Render the deadline episode with dialogue.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--frames")
    parser.add_argument("--scale", type=float, choices=(0.5, 1), default=1)
    parser.add_argument("--stills", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    total, filename, stills = EPISODES[args.episode]
    if args.voiced:
        if args.episode != "deadline":
            parser.error("--voiced requires --episode deadline")
        if not all((ROOT / "public" / name).is_file() for name in VOICE_FILES):
            parser.error("Run python voice_deadline.py to prepare the dialogue first")
        filename = filename.removesuffix(".mp4") + "-Voiced.mp4"
    start, end = map(int, (args.frames or f"0-{total - 1}").split("-"))
    if not 0 <= start <= end < total:
        parser.error(f"frames must be in 0–{total - 1}")
    output = (args.output or ROOT / "final" / filename).resolve()
    if output.exists() and not (args.stills or args.preview):
        parser.error("output already exists")
    query = f"episode={args.episode}" + ("&voiced" if args.voiced else "")
    bundle()
    if args.preview:
        with server() as url:
            print(f"{url}?{query}", flush=True)
            input("Press Enter to stop.\n")
        return
    with server() as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=browser_path(),
            args=["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--disable-dev-shm-usage",
                  "--disk-cache-size=1048576"],
        )
        page = browser.new_page(viewport={
            "width": round(args.scale * 1080),
            "height": round(args.scale * 1920),
        })
        page.on("pageerror", lambda error: print(error, flush=True))
        ready(page, url, query)
        if args.stills:
            prefix = "voiced" if args.voiced else "frame" if args.episode == "five-minutes" else args.episode
            for frame in stills:
                (ROOT / "work" / f"{prefix}-{frame:03}.jpg").write_bytes(grab(page, frame))
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            encode(page, output, start, end, args.voiced)
        browser.close()


if __name__ == "__main__":
    main()
