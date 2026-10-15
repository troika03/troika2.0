from pathlib import Path

root = Path(__file__).resolve().parents[1]
thread = Path(r'C:\Users\kiqu\.codex\visualizations\2026\10\15\01a13fc1-5213-7271-97f9-504e1d4fd5b4')
for name in ['troika-phone','troika-desktop']:
    path = thread / (name + '.html')
    text = path.read_text(encoding='utf-8')
    text = text.replace('width:260px; height:260px; max-width:100%; aspect-ratio:1;', 'width:min(260px,100%); height:auto; aspect-ratio:1;')
    text = text.replace('width:236px; height:236px;', 'width:min(236px,100%); height:auto;')
    if name.endswith('phone'):
        old = "const selected=b.dataset.go===screen||b.dataset.go==='tasks'&&['development','project'].includes(screen)||b.dataset.go==='profile'&&!['home','tasks','development','project','files','text','history'].includes(screen);"
        new = "const section=['tasks','new-task','project','development','new-project','development-detail','budget'].includes(screen)?'tasks':['files','file-detail','create-file'].includes(screen)?'files':['home','text','history','approval','offline'].includes(screen)?'home':'profile';const selected=b.dataset.go===section;"
        text = text.replace(old,new)
        capture = "\n  app.addEventListener('click',e=>{const b=e.target.closest('[data-file], [data-action=\"edit-memory\"]');if(b){e.preventDefault();e.stopImmediatePropagation();screen=b.dataset.file?'file-detail':'edit-memory';render();}},true);\n"
        text = text.replace('  app.troikaDesign={screens:Object.keys(pages)',capture+'  app.troikaDesign={screens:Object.keys(pages)',1)
    else:
        capture = "\n  app.addEventListener('click',e=>{const b=e.target.closest('[data-file], [data-action=\"edit-memory\"]');if(b){e.preventDefault();e.stopImmediatePropagation();page=b.dataset.file?'file-detail':'edit-memory';render();}},true);\n"
        text = text.replace('  app.troikaDesign={screens:Object.keys(views)',capture+'  app.troikaDesign={screens:Object.keys(views)',1)
    path.write_text(text,encoding='utf-8')
    (root / 'source' / ('android.html' if name.endswith('phone') else 'desktop.html')).write_text(text,encoding='utf-8')
print('Navigation and narrow voice layout refined')
