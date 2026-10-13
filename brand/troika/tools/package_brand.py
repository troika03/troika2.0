"""Create the local asset gallery, verify vectors and PDFs, and package the kit."""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree

from PIL import Image
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT.parents[1] / "work/brand-kit-2026-10-13"
CATALOG = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))


def build_gallery():
    labels = {"logos": "Логотипы", "banners": "Баннеры", "app": "Приложение",
              "icons": "Иконки", "patterns": "Паттерны", "guide": "Брендбук"}
    sections = []
    for category, label in labels.items():
        cards = []
        for item in CATALOG:
            if item["category"] != category:
                continue
            source = item["file"]
            dark = category == "logos" and ("white" in source or "reverse" in source)
            png = "exports/png/" + source.replace(".svg", ".png")
            editable = f'<a href="editable/{source}" download>Править текст</a>' if category=="banners" else ""
            cards.append(
                '<figure class="asset"><div class="art '+("dark" if dark else "")+'">'
                f'<img src="{source}" alt="{html.escape(item["title"])}" loading="lazy"></div>'
                f'<figcaption><strong>{html.escape(Path(source).stem)}</strong>'
                f'<span>{item["width"]} × {item["height"]}</span>'
                f'<div><a href="{source}" download>SVG</a><a href="{png}" download>PNG</a>{editable}</div>'
                "</figcaption></figure>"
            )
        sections.append(f'<section data-category="{category}"><h2>{label}</h2>'
                        f'<div class="grid {category}">{"".join(cards)}</div></section>')
    buttons = '<button type="button" data-filter="all" aria-pressed="true">Всё</button>' + "".join(
        f'<button type="button" data-filter="{key}" aria-pressed="false">{label}</button>' for key, label in labels.items())
    document = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Troika — фирменный стиль</title><link rel="icon" href="app/favicon.svg">
<style>
@font-face{font-family:Golos;src:url("fonts/GolosText-Variable.ttf") format("truetype");font-weight:400 900;font-display:swap}
*{box-sizing:border-box}body{margin:0;background:#fff;color:#0c0b0a;font:16px/1.5 Golos,Arial,sans-serif}
main{max-width:1440px;margin:auto;padding:36px 32px 64px}a{color:inherit;text-underline-offset:4px}
h1{font-size:30px;letter-spacing:-.03em;line-height:1.2;margin:0 0 12px}h2{font-size:24px;font-weight:600;margin:50px 0 18px}
p{max-width:760px}.downloads{display:flex;flex-wrap:wrap;gap:14px 26px;margin:24px 0 30px}.board{display:block;width:100%;height:auto}
nav{display:flex;flex-wrap:wrap;gap:8px;padding:24px 0;border-bottom:1px solid #dedbd5}
button{font:inherit;border:1px solid #d6d2ca;background:#fff;border-radius:4px;padding:7px 13px;cursor:pointer}
button[aria-pressed=true]{background:#0c0b0a;color:#fff;border-color:#0c0b0a}:focus-visible{outline:3px solid #c37b0f;outline-offset:4px}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:28px}.banners{grid-template-columns:repeat(2,minmax(0,1fr))}
.icons{grid-template-columns:repeat(6,minmax(0,1fr))}.guide{grid-template-columns:repeat(3,minmax(0,1fr))}
figure{margin:0;min-width:0}.art{background:#f7f7f7;display:flex;align-items:center;justify-content:center;padding:18px;min-height:180px}
.art.dark{background:#0c0b0a}.art img{display:block;max-width:100%;max-height:300px;width:auto;height:auto}
.banners .art,.guide .art,.patterns .art{padding:0}.banners .art img,.patterns .art img{width:100%;max-height:none}
.guide .art img{width:100%;max-height:none}.icons .art{min-height:100px}.icons .art img{width:36px;height:36px}
figcaption{padding-top:12px;font-size:13px}figcaption strong{display:block;font-weight:500;overflow-wrap:anywhere}
figcaption span{display:block;color:#59554f;font-size:12px}figcaption div{display:flex;gap:16px;flex-wrap:wrap;padding-top:8px}
[hidden]{display:none!important}footer{border-top:1px solid #dedbd5;margin-top:50px;padding-top:22px;color:#555;font-size:14px}
@media(max-width:800px){main{padding:24px 18px}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.icons{grid-template-columns:repeat(4,minmax(0,1fr))}}
@media(max-width:520px){.grid,.banners,.guide{grid-template-columns:1fr}.icons{grid-template-columns:repeat(3,minmax(0,1fr))}h1{font-size:26px}.art{min-height:130px}}
</style></head><body><main>
<h1>Troika. Фирменный стиль</h1>
<p>Три линии: голос, задача, результат. Логотип, баннеры и иконки в векторе.
В оригиналах текст переведён в кривые. Для редактирования надписей есть отдельные SVG и шрифт.</p>
<div class="downloads"><a href="download/Troika-Brand-Kit.zip" download>Скачать весь комплект</a>
<a href="guide/Troika-Brand-Guide.pdf">Открыть брендбук</a>
<a href="exports/pdf/Troika-Logos.pdf">Логотипы PDF</a>
<a href="exports/pdf/Troika-Banners.pdf">Баннеры PDF</a></div>
<img class="board" src="preview/brand-board.svg" alt="Troika: логотип, янтарная палитра и иконки приложения">
<nav aria-label="Тип материалов">__BUTTONS__</nav>__SECTIONS__
<footer>Комплект от 13 октября 2026. Это материалы оформления; внедрение в сайт и клиенты выполняется отдельно.
Golos Text: <a href="https://github.com/googlefonts/golos-text">официальный источник</a>,
<a href="fonts/OFL.txt">лицензия OFL</a>. <a href="README.md">Инструкция</a>.</footer>
</main><script>
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{
document.querySelectorAll('[data-filter]').forEach(other=>other.setAttribute('aria-pressed',String(other===button)));
document.querySelectorAll('[data-category]').forEach(section=>section.hidden=button.dataset.filter!=='all'&&button.dataset.filter!==section.dataset.category);
}));
</script></body></html>"""
    (ROOT/"index.html").write_text(document.replace("__BUTTONS__",buttons).replace("__SECTIONS__","".join(sections)),encoding="utf-8")


def contact_sheet():
    assets = [item for item in CATALOG if item["category"]=="banners"]
    board = Image.new("RGB", (1500, math_ceil(len(assets)/3)*390), "white")
    for index, item in enumerate(assets):
        source = ROOT/"exports/png"/item["file"].replace(".svg", ".png")
        image = Image.open(source).convert("RGB")
        image.thumbnail((470, 360))
        x = (index%3)*500+(500-image.width)//2
        y = (index//3)*390+(390-image.height)//2
        board.paste(image,(x,y))
    SCRATCH.mkdir(parents=True,exist_ok=True)
    board.save(SCRATCH/"banner-contact.png")
    pages = Image.new("RGB", (1500, 1100), "#E8E8E8")
    for index in range(2,8):
        image = Image.open(SCRATCH/f"guide-{index}.png").convert("RGB")
        image.thumbnail((480,530))
        x = ((index-2)%3)*500+(500-image.width)//2
        y = ((index-2)//3)*550+(550-image.height)//2
        pages.paste(image,(x,y))
    pages.save(SCRATCH/"guide-contact.png")


def math_ceil(value):
    return int(value) if value==int(value) else int(value)+1


def validate():
    namespace = "{http://www.w3.org/2000/svg}"
    vectors = list(ROOT.rglob("*.svg"))
    for file in vectors:
        root = ElementTree.fromstring(file.read_text(encoding="utf-8"))
        assert not root.findall(".//"+namespace+"image"), f"Raster in {file}"
        assert not root.findall(".//"+namespace+"script"), f"Script in {file}"
        assert not root.findall(".//"+namespace+"foreignObject"), f"foreignObject in {file}"
        if "editable" not in file.relative_to(ROOT).parts:
            assert not root.findall(".//"+namespace+"text"), f"Live text in outlined SVG: {file}"
        for node in root.iter():
            for key, value in node.attrib.items():
                if key.endswith("href"):
                    assert value.startswith("#"), f"External SVG reference in {file}"
    pdfs = {"guide/Troika-Brand-Guide.pdf": 7, "exports/pdf/Troika-Logos.pdf": 2,
            "exports/pdf/Troika-Banners.pdf": 11}
    for filename, expected in pdfs.items():
        pdf = PdfReader(ROOT/filename)
        assert len(pdf.pages)==expected
        for page in pdf.pages:
            xobjects = page["/Resources"].get("/XObject", {})
            for obj in xobjects.values():
                assert obj.get_object().get("/Subtype")!="/Image", f"Raster in {filename}"
    for xml in (ROOT/"app/android").glob("*.xml"):
        ElementTree.parse(xml)
    result = {"svg_count":len(vectors), "outlined_masters_without_live_text":True,
              "svg_no_raster_or_scripts":True, "pdf_vector_verified":True,
              "pdf_page_counts":pdfs, "android_xml_valid":True}
    (ROOT/"guide/package-validation.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def package():
    Image.open(ROOT/"exports/png/app/app-icon-dark.png").save(
        ROOT/"app/Troika.ico",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    Image.open(ROOT/"exports/png/app/favicon-48.png").save(
        ROOT/"app/favicon.ico",sizes=[(16,16),(32,32),(48,48)])
    files = sorted(file for file in ROOT.rglob("*") if file.is_file()
                   and "download" not in file.relative_to(ROOT).parts
                   and "__pycache__" not in file.relative_to(ROOT).parts
                   and file.name!="manifest.json")
    # Match the Git checkout byte-for-byte while preserving the upstream license.
    for file in files:
        if file.suffix in (".svg", ".xml", ".json", ".css", ".html", ".md", ".py", ".cjs") or file.name in (".gitignore", ".gitattributes"):
            file.write_bytes(file.read_bytes().replace(b"\r\n", b"\n"))
    manifest = [{"file":file.relative_to(ROOT).as_posix(),"bytes":file.stat().st_size,
                 "sha256":hashlib.sha256(file.read_bytes()).hexdigest()} for file in files]
    (ROOT/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    files.append(ROOT/"manifest.json")
    folder = ROOT/"download"
    folder.mkdir(exist_ok=True)
    target = folder/"Troika-Brand-Kit.zip"
    with ZipFile(target,"w",ZIP_DEFLATED,compresslevel=9) as archive:
        for file in files:
            archive.write(file,Path("Troika-Brand-Kit")/file.relative_to(ROOT))
    with ZipFile(target) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist())==len(files)
        for item in manifest:
            data = archive.read("Troika-Brand-Kit/"+item["file"])
            assert hashlib.sha256(data).hexdigest()==item["sha256"]
    print(json.dumps({"packaged_files":len(files),"zip_bytes":target.stat().st_size,
                      "archive_hashes_verified":True},ensure_ascii=False))


if __name__=="__main__":
    build_gallery()
    contact_sheet()
    print(json.dumps(validate(),ensure_ascii=False))
    package()
