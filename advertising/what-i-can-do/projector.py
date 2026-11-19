"""Build the projector cold open at the timing of the verified Gemini master."""
from functools import lru_cache
from pathlib import Path
import math
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
LOCAL = ROOT / "local"
W, H, FPS = 1080, 1920, 30
FRAMES = 155
MASTER = ROOT / "Что умеет Тройка — До доклада 5 минут — Gemini.mp4"
FINAL = ROOT / "Тройка — Кот на проекторе.mp4"
RESAMPLE = Image.Resampling.BICUBIC


@lru_cache
def font(size, weight):
    face = ImageFont.truetype(str(LOCAL / "golos.ttf"), size)
    face.set_variation_by_axes([weight])
    return face


def slide_on_projector(photo):
    # Projector screen corners measured on the classroom photograph, clockwise.
    corners = np.array([(17, 82), (322, 90), (333, 372), (15, 373)]) * (photo.width / 340)
    slide = Image.new("RGB", (1040, 900), "#e6dec5")
    d = ImageDraw.Draw(slide)
    d.text((68, 70), "ФИЗИКА", font=font(41, 650), fill="#344d40")
    d.multiline_text((60, 208), "Как устроен\nзвук", font=font(125, 765),
                     fill="#182d26", spacing=-12, stroke_width=0)
    for shift, color, width in [(0, "#367356", 11), (18, "#759880", 5)]:
        wave = [(x, 682 + shift + math.sin(x / 38) * 105 * math.exp(-((x-510)/290)**2))
                for x in range(65, 975, 3)]
        d.line(wave, fill=color, width=width)
    coeffs, targets = [], []
    for (x, y), (u, v) in zip(corners, [(0, 0), (1040, 0), (1040, 900), (0, 900)]):
        coeffs.extend([[x, y, 1, 0, 0, 0, -u*x, -u*y], [0, 0, 0, x, y, 1, -v*x, -v*y]])
        targets.extend([u, v])
    coeffs = np.linalg.solve(coeffs, targets)
    projection = slide.transform(photo.size, Image.Transform.PERSPECTIVE, coeffs, RESAMPLE)
    mask = Image.new("L", photo.size)
    ImageDraw.Draw(mask).polygon(list(map(tuple, corners)), fill=255)
    return Image.composite(projection, photo, mask)


def photo_plate(photo):
    # Full photograph on a portrait field, with a soft dark falloff into caption space.
    im = Image.new("RGB", (W, H), "#100f0d")
    h = round(photo.height * W / photo.width)
    photo = photo.resize((W, h), RESAMPLE)
    y = 202
    im.paste(photo, (0, y))
    strength = np.interp(np.arange(H), [0,y,y+115,425,690,1270,1430,y+h-75,y+h,H],
                         [1,1,.68,.22,0,0,.10,.78,1,1])
    shade = Image.fromarray(np.uint8(np.repeat((strength*255)[:, None], W, axis=1)))
    return Image.composite(Image.new("RGB", (W, H), "#100f0d"), im, shade)


def ease(value):
    u = max(0., min(1., value))
    return u*u*(3-2*u)


def main():
    photo = Image.open(ROOT / "design/classroom-projector.jpg").convert("RGB")
    cat, deck = photo_plate(photo), photo_plate(slide_on_projector(photo))
    screenshot = Image.open(LOCAL / "screens/files.png").convert("RGB")
    # The real Files view, fourth row, including the PPT icon, filename and file size.
    row = screenshot.crop((47, 1422, 1100, 1665)).resize((908, 210), RESAMPLE)
    temp = LOCAL / "projector-opening.mp4"
    with subprocess.Popen([
        "ffmpeg","-y","-v","error","-f","rawvideo","-pix_fmt","rgb24","-s","1080x1920",
        "-r","30","-i","-","-c:v","libx264","-preset","veryfast","-crf","15",
        "-threads","3","-pix_fmt","yuv420p",str(temp)
    ], stdin=subprocess.PIPE) as enc:
        for n in range(FRAMES):
            t = n / FPS
            reveal = ease((t-2.37)/.18)
            bg = cat if reveal == 0 else deck if reveal == 1 else Image.blend(cat, deck, reveal)
            zoom = 1 + .055*ease(t/1.45) - .055*ease((t-2.35)/.65)
            inset = max(0., (W-W/zoom)/2)
            frame = bg.copy() if inset < .001 else bg.resize(
                (W,H), RESAMPLE, box=(inset,inset*H/W,W-inset,H-inset*H/W))
            d = ImageDraw.Draw(frame)
            if t < 2.48:
                d.text((60, 106), "Я: «Сейчас", font=font(88, 790), fill="#fffaf2")
                d.text((59, 203), "покажу доклад»", font=font(103, 805), fill="#fffaf2",
                       stroke_width=1,stroke_fill="#fffaf2")
            if 1.22 <= t < 2.45:
                u = ease((t-1.22)/.18)
                y = round(1180+340*(1-u))
                card = Image.new("RGBA", (960,324))
                cd = ImageDraw.Draw(card)
                cd.rounded_rectangle((0,0,959,323),36,fill="#1f2321",outline="#62d99e",width=4)
                cd.text((29,18),"Тройка · Файлы",font=font(39,650),fill="#80e2ad")
                card.paste(row, (25,88))
                frame.paste(card,(60,y),card)
            caption = "Тройка, где мои слайды?!" if t < 2.37 else "Вот они. «Как устроен звук»."
            d = ImageDraw.Draw(frame)
            d.text((60,1550),caption,font=font(57,650),fill="white",stroke_width=2,stroke_fill="#24201b")
            enc.stdin.write(frame.tobytes())
        enc.stdin.close()
        if enc.wait():
            raise RuntimeError("Opening encode failed")
    # At frame 155 the previous master has already cut to the next full-screen scene.
    subprocess.run([
        "ffmpeg","-y","-v","error","-threads","2","-i",str(temp),"-threads","2","-i",str(MASTER),
        "-filter_complex_threads","2","-filter_complex",
        "[0:v]setsar=1[a];[1:v]trim=start_frame=155,setpts=PTS-STARTPTS,setsar=1[b];[a][b]concat=n=2:v=1:a=0[v]",
        "-map","[v]","-map","1:a","-c:a","copy","-c:v","libx264","-threads","4","-preset","veryfast",
        "-crf","16","-pix_fmt","yuv420p","-color_primaries","bt709","-color_trc","bt709",
        "-colorspace","bt709","-movflags","+faststart",str(FINAL)
    ],check=True)


if __name__ == "__main__":
    main()
