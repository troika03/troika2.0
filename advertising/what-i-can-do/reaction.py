"""Add a classroom reaction beat to the synced projector master."""
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageOps
from projector import FPS, H, W, RESAMPLE, ease, font, photo_plate

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "Тройка — Кот на проекторе.mp4"
FINAL = ROOT / "Тройка — Реакция у доски.mp4"
PREVIEW = ROOT / "Первые шесть секунд — Реакция у доски.mp4"
REJOIN = 38
LEAD = 30


def encode():
    cat = photo_plate(Image.open(ROOT / "design/classroom-projector.jpg").convert("RGB"))
    face = ImageOps.fit(Image.open(ROOT / "design/classroom-reaction.jpg").convert("RGB"), (W, H))
    intro = ROOT / "local/reaction-opening.mp4"
    with subprocess.Popen([
        "ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
        f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-threads", "3",
        "-preset", "veryfast", "-crf", "15", "-pix_fmt", "yuv420p", str(intro),
    ], stdin=subprocess.PIPE) as encoder:
        for n in range(REJOIN + LEAD):
            if n < 22:
                frame = cat.copy()
                ImageDraw.Draw(frame).text((60, 138), "Мой доклад:", font=font(100, 780), fill="#fffaf2")
            else:
                # A quick punch-in lands on the eyes, then holds through the awkward beat.
                scale = 1 + .105 * ease((n - 22) / 10)
                width, height = W / scale, H / scale
                x, y = (W - width) * .53, (H - height) * .31
                frame = face.resize((W, H), RESAMPLE, box=(x, y, x + width, y + height))
                if n >= LEAD + 2:
                    draw = ImageDraw.Draw(frame)
                    draw.text((60, 1540), "Тройка, где мои слайды?!", font=font(57, 650),
                              fill="white", stroke_width=3, stroke_fill="#221c1b")
            encoder.stdin.write(frame.tobytes())
        encoder.stdin.close()
        if encoder.wait():
            raise RuntimeError("Reaction-shot encode failed")
    # One extra second before the original voices. A projector click cuts to quiet on the face.
    graph = (
        f"[0:v]setsar=1[open];[1:v]trim=start_frame={REJOIN},setpts=PTS-STARTPTS,setsar=1[tail];"
        "[open][tail]concat=n=2:v=1:a=0[v];"
        "[1:a]adelay=1000:all=1[original];"
        "anoisesrc=color=brown:amplitude=0.022:duration=0.72:sample_rate=48000:seed=23,"
        "highpass=f=120,lowpass=f=1500,afade=t=out:st=0.55:d=0.17[room];"
        "anoisesrc=color=pink:amplitude=0.16:duration=0.055:sample_rate=48000:seed=8,"
        "highpass=f=1200,afade=t=in:d=0.002,afade=t=out:st=0.004:d=0.051[click];"
        "[original][room][click]amix=inputs=3:duration=first:normalize=0[a]"
    )
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-threads", "2", "-i", str(intro),
                    "-threads", "2", "-i", str(SOURCE), "-filter_complex_threads", "2",
                    "-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                    "-threads", "4", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
                    "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                    "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "192k", "-t", "87.5",
                    "-movflags", "+faststart", str(FINAL)], check=True)
    subprocess.run(["ffmpeg","-y","-v","error","-threads","2","-i",str(FINAL),"-t","6",
                    "-c:v","libx264","-threads","3","-preset","veryfast","-crf","16",
                    "-c:a","aac","-b:a","192k","-movflags","+faststart",str(PREVIEW)],check=True)


if __name__ == "__main__":
    encode()
