from pathlib import Path

root=Path(__file__).resolve().parents[1]
thread=Path(r'C:\Users\kiqu\.codex\visualizations\2026\10\15\01a13fc1-5213-7271-97f9-504e1d4fd5b4')
css='\n#troika-phone .tk-orb-label svg,#troika-desktop .td-orb>svg { transform:scale(2.25); transform-origin:center; }\n'
for platform,name in [('android','troika-phone'),('desktop','troika-desktop')]:
    file=thread/(name+'.html')
    text=file.read_text(encoding='utf-8')
    if css.strip() not in text:text=text.replace('</style>',css+'</style>',1)
    file.write_text(text,encoding='utf-8')
    (root/'source'/(platform+'.html')).write_text(text,encoding='utf-8')
