"""Prepare demo-data screens for the overview without using personal files."""
from pathlib import Path
from base64 import b64encode
from PIL import Image
from playwright.sync_api import sync_playwright
import shutil
import re

root=Path(__file__).resolve().parent
repo=root.parents[1]
out=root/'local/screens'
out.mkdir(parents=True,exist_ok=True)
old=repo/'design/troika-ui-2026-10-20/svg/android/dark'
font=repo/'hermes-android/assets/fonts/GolosText-Variable.ttf'
shutil.copyfile(font,out.parent/'golos.ttf')
shutil.copyfile(root.parent/'six-drafts/local/gsap.min.js',out.parent/'gsap.min.js')
changes={
'memory':{'Личный сайт и проект с заметками':'Репетиции по пятницам','Светлая тема днём, тёмная вечером':'Люблю короткие объяснения'},
'tasks':{'Посмотреть план запуска':'Собрать вещи на репетицию','Личный сайт':'Музыка','Выбрать домен':'Подготовить ноты','Проверить первую версию сайта':'Забрать гитару','10:00':'16:00','Сегодня, 20 октября':'План на неделю'},
'reminders':{'Сегодня':'Пятница','Посмотреть план запуска':'Забрать гитару','Личный сайт · уведомление и голос':'К репетиции · уведомление и голос','18:00':'16:00','Проверить первую версию сайта':'Подготовить ноты'},
'files':{'План запуска.docx':'План репетиции.docx','Личный сайт.zip':'Список вещей.docx','ZIP':'DOC','Презентация идеи.pptx':'Как устроен звук.pptx'},
}
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='chrome')
    page=browser.new_page(viewport={'width':390,'height':844},device_scale_factor=3)
    for name,subs in changes.items():
        svg=(old/(name+'.svg')).read_text('utf-8')
        for a,b in subs.items(): svg=svg.replace('>'+a+'<','>'+b+'<')
        svg=re.sub(r'url\("[^"]+\.ttf"\)',lambda m:'url("data:font/ttf;base64,'+b64encode(font.read_bytes()).decode()+'")',svg)
        page.set_content('<style>*{margin:0}body{background:#0b0c10}</style>'+svg)
        page.evaluate('document.fonts.ready')
        page.screenshot(path=str(out/(name+'.png')))
    browser.close()
# Frame the voice mark above the shortcut chips in both production client views.
home=Image.open(root.parent/'six-drafts/local/screens/home.png')
home.crop((0,0,home.width,int(home.height*.70))).save(out/'home.png')
compact=Image.open(repo/'design/troika-ui-2026-11-13/windows-dark-compact.png')
compact.crop((0,0,480,417)).save(out/'windows.png')


# Detail view of the Windows screen-sharing command, cropped to its permission text.
commands=Image.open(repo/'design/troika-ui-2026-10-20/previews/desktop/dark/commands.png').convert('RGB')
detail=Image.new('RGB',(800,320),commands.getpixel((850,91)))
detail.paste(commands.crop((372,79,1158,167)),(8,25))
detail.paste(commands.crop((372,426,1158,550)),(8,132))
detail.save(out/'winhelp.png')
