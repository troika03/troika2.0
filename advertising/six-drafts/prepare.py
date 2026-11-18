"""Prepare high-resolution UI planes from native Flutter renders."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import shutil
import urllib.request

root = Path(__file__).resolve().parent
out = root / 'local'
screens = out / 'screens'
repo = root.parents[1]
font_file = repo / 'hermes-android/assets/fonts/GolosText-Variable.ttf'
home = Image.open(screens / 'home.png').convert('RGB')
home.save(out / 'home.webp', lossless=True)
chat = Image.open(screens / 'chat-3.png').convert('RGB')
# The test engine uses the Ahem font for a route title. Use the route's
# literal title with the matching Golos Text face on the original background.
arr = np.asarray(chat).copy()
for x in range(275, 735):
    fraction = (x - 274) / (735 - 274)
    arr[:215, x] = arr[:215,274] * (1-fraction) + arr[:215,735] * fraction
chat = Image.fromarray(arr)
font = ImageFont.truetype(str(font_file), 80)
font.set_variation_by_axes([520])
ImageDraw.Draw(chat).text((288,112),'Текст',font=font,fill='#f4f5f7',anchor='lm')
# The later native states have identical geometry. Separate the changed rows
# so the camera can introduce each genuine bubble independently.
early = Image.open(screens / 'chat-0.png').convert('RGB')
base = chat.copy()
base.paste(early.crop((0,640,1560,1410)),(0,640))
base.save(out / 'thread.webp', lossless=True)
for i, (top,bottom) in enumerate([(161,233),(233,284),(284,337)], 1):
    chat.crop((0,top*4,1560,bottom*4)).save(out / f'row-{i}.webp',lossless=True)
shutil.copyfile(font_file,out / 'golos.ttf')
gsap = root.parent / 'troika-hyperframes-20261117/assets/gsap.min.js'
if gsap.exists():
    shutil.copyfile(gsap,out/'gsap.min.js')
elif not (out/'gsap.min.js').exists():
    urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js',out/'gsap.min.js')
