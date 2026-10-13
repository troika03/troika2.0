"""Build the Troika vector identity without a browser or proprietary editor."""

from __future__ import annotations

import hashlib
import html
import json
import math
from pathlib import Path
from xml.etree import ElementTree

from fontTools.pens.basePen import BasePen
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.svgLib.path import parse_path
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from reportlab.lib.colors import HexColor
from reportlab.pdfgen.canvas import Canvas


ROOT = Path(__file__).resolve().parents[1]
COLORS = {
    "amber": "#F5A623",
    "ink": "#0C0B0A",
    "paper": "#F3F0EA",
    "deep": "#E08A12",
    "muted": "#8C887F",
    "white": "#FFFFFF",
}
AMBER, INK, PAPER, DEEP, MUTED, WHITE = COLORS.values()
FONT_FILE = ROOT / "fonts/GolosText-Variable.ttf"
VARIABLE_FONT = TTFont(FONT_FILE)
FONTS = {
    weight: instantiateVariableFont(VARIABLE_FONT, {"wght": weight}, inplace=False)
    for weight in (400, 500, 600, 700)
}
GLYPHS = {weight: font.getGlyphSet() for weight, font in FONTS.items()}
CMAP = {chr(codepoint): name for codepoint, name in VARIABLE_FONT.getBestCmap().items()}
UPM = VARIABLE_FONT["head"].unitsPerEm
CATALOG = []
SCENES = {}
TEXT_BOUNDS = []

# Three nested, round-ended paths. The silhouette uses filled contours.
MARK_PATHS = (
    "M12 92V60C12 33.490 33.490 12 60 12H92"
    "A8 8 0 0 1 92 28H60C42.327 28 28 42.327 28 60V92"
    "A8 8 0 0 1 12 92Z",
    "M40 92V68C40 52.536 52.536 40 68 40H92"
    "A8 8 0 0 1 92 56H68C61.373 56 56 61.373 56 68V92"
    "A8 8 0 0 1 40 92Z",
    "M68 92V80C68 73.373 73.373 68 80 68H92"
    "A8 8 0 0 1 92 84H84V92A8 8 0 0 1 68 92Z",
)


def n(value):
    return f"{value:.4f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def rect(x, y, w, h, fill, radius=0, stroke=None, sw=1):
    return {"kind": "rect", "x": x, "y": y, "w": w, "h": h,
            "fill": fill, "radius": radius, "stroke": stroke, "sw": sw}


def path(d, fill=None, stroke=None, sw=2):
    return {"kind": "path", "d": d, "fill": fill, "stroke": stroke, "sw": sw}


def circle(x, y, radius, fill=None, stroke=None, sw=2):
    return {"kind": "circle", "x": x, "y": y, "radius": radius,
            "fill": fill, "stroke": stroke, "sw": sw}


def group(children, x=0, y=0, scale=1, opacity=1):
    return {"kind": "group", "children": children, "x": x, "y": y,
            "scale": scale, "opacity": opacity}


def mark(x, y, size, color=AMBER, opacity=1):
    return group([path(d, color) for d in MARK_PATHS], x, y, size / 112, opacity)


def advance(text, size, weight=400, tracking=0):
    font = FONTS[weight]
    return sum(font["hmtx"][CMAP[ch]][0] / UPM * size for ch in text) + tracking * max(0, len(text) - 1)


def text(value, x, y, size=24, fill=INK, weight=400, tracking=0, max_width=None):
    if max_width and advance(value, size, weight, tracking) > max_width:
        size *= max_width / advance(value, size, weight, tracking)
    return {"kind": "text", "value": value, "x": x, "y": y, "size": size,
            "fill": fill, "weight": weight, "tracking": tracking}


def lines(values, x, baseline, size, fill=INK, weight=700, leading=1.12, max_width=None):
    return [text(value, x, baseline + index * size * leading, size, fill, weight,
                 tracking=-size * .025 if weight >= 600 else 0, max_width=max_width)
            for index, value in enumerate(values)]


def logo(x, y, h=100, on_dark=False, mono=False, language="en"):
    color = PAPER if on_dark else INK
    mark_color = color if mono else AMBER
    word = "troika" if language == "en" else "тройка"
    size = h * .94
    baseline = y + h * .78
    return [
        mark(x, y, h, mark_color),
        text(word, x + h * 1.29, baseline, size, color, 700, -size * .032),
    ]


def glyph_paths(node):
    font = FONTS[node["weight"]]
    glyph_set = GLYPHS[node["weight"]]
    x = node["x"]
    for ch in node["value"]:
        glyph = CMAP.get(ch)
        if glyph is None:
            raise ValueError(f"Missing glyph: {ch!r}")
        pen = SVGPathPen(glyph_set)
        glyph_set[glyph].draw(pen)
        yield pen.getCommands(), x
        x += font["hmtx"][glyph][0] / UPM * node["size"] + node["tracking"]


def svg_node(node, editable=False):
    kind = node["kind"]
    if kind == "group":
        body = "".join(svg_node(child, editable) for child in node["children"])
        return (f'<g transform="translate({n(node["x"])} {n(node["y"])}) scale({n(node["scale"])})" '
                f'opacity="{n(node["opacity"])}">{body}</g>')
    attrs = f'fill="{node.get("fill") or "none"}"'
    if node.get("stroke"):
        attrs += f' stroke="{node["stroke"]}" stroke-width="{n(node["sw"])}" stroke-linecap="round" stroke-linejoin="round"'
    if kind == "rect":
        return f'<rect x="{n(node["x"])}" y="{n(node["y"])}" width="{n(node["w"])}" height="{n(node["h"])}" rx="{n(node["radius"])}" {attrs}/>'
    if kind == "circle":
        return f'<circle cx="{n(node["x"])}" cy="{n(node["y"])}" r="{n(node["radius"])}" {attrs}/>'
    if kind == "path":
        return f'<path d="{node["d"]}" {attrs}/>'
    if kind == "text":
        value = html.escape(node["value"])
        if editable:
            return (f'<text x="{n(node["x"])}" y="{n(node["y"])}" font-family="Golos Text" '
                    f'font-size="{n(node["size"])}" font-weight="{node["weight"]}" '
                    f'letter-spacing="{n(node["tracking"])}" fill="{node["fill"]}">{value}</text>')
        output = []
        for d, x in glyph_paths(node):
            if d:
                output.append(f'<path d="{d}" transform="translate({n(x)} {n(node["y"])}) scale({n(node["size"]/UPM)} {n(-node["size"]/UPM)})"/>')
        return f'<g fill="{node["fill"]}" aria-label="{value}">{"".join(output)}</g>'
    raise ValueError(kind)


def save(name, w, h, nodes, title, category, editable=False):
    target = ROOT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    doc = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
           f'viewBox="0 0 {w} {h}" role="img" aria-labelledby="title desc">'
           f'<title id="title">{html.escape(title)}</title>'
           f'<desc id="desc">Troika. Векторный оригинал. {"Редактируемый текст: Golos Text." if editable else "Текст переведён в кривые. Внешних ресурсов нет."}</desc>'
           + "".join(svg_node(node, editable) for node in nodes) + "</svg>")
    target.write_text(doc, encoding="utf-8")
    ElementTree.fromstring(doc)
    scene = {"w": w, "h": h, "nodes": nodes, "title": title}
    SCENES[name] = scene
    CATALOG.append({"file": name, "width": w, "height": h, "title": title,
                    "category": category, "editable_text": editable})
    if not editable:
        check_text_bounds(scene, name)


def check_text_bounds(scene, name):
    def visit(node, tx=0, ty=0, scale=1):
        if node["kind"] == "group":
            for child in node["children"]:
                visit(child, tx + node["x"] * scale, ty + node["y"] * scale, scale * node["scale"])
        elif node["kind"] == "text":
            for ch, (_, x) in zip(node["value"], glyph_paths(node)):
                pen = BoundsPen(GLYPHS[node["weight"]])
                GLYPHS[node["weight"]][CMAP[ch]].draw(pen)
                if pen.bounds:
                    a, b, c, d = pen.bounds
                    s = node["size"] / UPM
                    box = (tx + (x + a*s)*scale, ty + (node["y"] - d*s)*scale,
                           tx + (x + c*s)*scale, ty + (node["y"] - b*s)*scale)
                    if min(box[:2]) < -0.1 or box[2] > scene["w"]+.1 or box[3] > scene["h"]+.1:
                        raise ValueError(f"Clipped text in {name}: {node['value']!r}, {box}")
            TEXT_BOUNDS.append({"file": name, "text": node["value"], "within_artboard": True})
    for node in scene["nodes"]:
        visit(node)


class PDFPen(BasePen):
    def __init__(self, pdf_path):
        super().__init__(None)
        self.pdf_path = pdf_path

    def _moveTo(self, p):
        self.pdf_path.moveTo(*p)

    def _lineTo(self, p):
        self.pdf_path.lineTo(*p)

    def _curveToOne(self, p1, p2, p3):
        self.pdf_path.curveTo(*p1, *p2, *p3)

    def _closePath(self):
        self.pdf_path.close()


def draw_pdf_node(canvas, node, opacity=1):
    canvas.saveState()
    kind = node["kind"]
    if kind == "group":
        canvas.translate(node["x"], node["y"])
        canvas.scale(node["scale"], node["scale"])
        for child in node["children"]:
            draw_pdf_node(canvas, child, opacity * node["opacity"])
        canvas.restoreState()
        return
    if kind == "text":
        for d, x in glyph_paths(node):
            if not d:
                continue
            canvas.saveState()
            canvas.translate(x, node["y"])
            canvas.scale(node["size"]/UPM, -node["size"]/UPM)
            canvas.setFillColor(HexColor(node["fill"]))
            canvas.setFillAlpha(opacity)
            p = canvas.beginPath()
            parse_path(d, PDFPen(p))
            canvas.drawPath(p, fill=1, stroke=0, fillMode=1)
            canvas.restoreState()
        canvas.restoreState()
        return
    fill, stroke = node.get("fill"), node.get("stroke")
    if fill:
        canvas.setFillColor(HexColor(fill))
        canvas.setFillAlpha(opacity)
    if stroke:
        canvas.setStrokeColor(HexColor(stroke))
        canvas.setStrokeAlpha(opacity)
        canvas.setLineWidth(node["sw"])
        canvas.setLineCap(1)
        canvas.setLineJoin(1)
    if kind == "rect":
        canvas.roundRect(node["x"], node["y"], node["w"], node["h"], node["radius"],
                         fill=bool(fill), stroke=bool(stroke))
    elif kind == "circle":
        canvas.circle(node["x"], node["y"], node["radius"], fill=bool(fill), stroke=bool(stroke))
    else:
        p = canvas.beginPath()
        parse_path(node["d"], PDFPen(p))
        canvas.drawPath(p, fill=bool(fill), stroke=bool(stroke), fillMode=1)
    canvas.restoreState()


def pdf_file(name, scenes, physical=False):
    target = ROOT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(target), pageCompression=1)
    canvas.setTitle("Troika: " + target.stem)
    canvas.setAuthor("Troika")
    for scene in scenes:
        scale = 1 if physical else .75
        canvas.setPageSize((scene["w"]*scale, scene["h"]*scale))
        canvas.saveState()
        canvas.translate(0, scene["h"]*scale)
        canvas.scale(scale, -scale)
        for node in scene["nodes"]:
            draw_pdf_node(canvas, node)
        canvas.restoreState()
        canvas.showPage()
    canvas.save()


def icon_paths(name):
    shapes = {
        "voice": ["M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3",
                  "M5 11v1a7 7 0 0 0 14 0v-1", "M12 19v3M8 22h8"],
        "text": ["M5 4h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-7l-6 4v-4H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z",
                 "M7 9h10M7 13h6"],
        "tasks": ["M10 6h10M10 12h10M10 18h10", "M3 5l2 2 3-3M3 11l2 2 3-3M3 17l2 2 3-3"],
        "files": ["M6 3h8l4 4v14H6Z", "M14 3v5h4M9 12h6M9 16h6"],
        "memory": ["M9 3H7a3 3 0 0 0-3 3v12a3 3 0 0 0 3 3h2M15 3h2a3 3 0 0 1 3 3v12a3 3 0 0 1-3 3h-2",
                   "M9 8h6v8H9ZM2 8h2M2 16h2M20 8h2M20 16h2M9 1v2M15 1v2M9 21v2M15 21v2"],
        "search": ["M16.5 16.5 22 22", "M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z"],
        "phone": ["M7 2h10a1 1 0 0 1 1 1v18a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Z",
                  "M10 5h4M11 19h2"],
        "desktop": ["M3 3h18v13H3ZM12 16v5M7 21h10"],
        "settings": ["M4 6h16M4 12h16M4 18h16", "M8 3v6M16 9v6M10 15v6"],
        "profile": ["M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z", "M4 22v-2a8 8 0 0 1 16 0v2"],
        "stop": ["M6 6h12v12H6Z"],
        "shield": ["M12 2 21 6v6c0 5-9 10-9 10S3 17 3 12V6Z", "m8 12 3 3 5-6"],
        "share": ["M12 16V2m-5 5 5-5 5 5M5 12v9h14v-9"],
        "download": ["M12 2v14m-5-5 5 5 5-5M3 18v4h18v-4"],
        "code": ["m7 6-6 6 6 6m10-12 6 6-6 6M14 3l-4 18"],
        "reminder": ["M5 17h14l-2-3V8a5 5 0 0 0-10 0v6ZM10 21h4M12 1v2"],
        "add": ["M12 4v16M4 12h16"],
        "check": ["m4 12 5 5L20 5"],
    }
    return [path(d, stroke=INK, sw=1.75) for d in shapes[name]]


def wave(x, y, width, height, color, opacity=1):
    """A repeated rhythm from the same three-line mark, not a stock waveform."""
    nodes = []
    for index in range(7):
        amplitude = height * (.35 + .65 * math.sin((index+1)*math.pi/8))
        bx = x + index * width/7
        nodes.append(rect(bx, y + (height-amplitude)/2, width/14, amplitude, color, width/28))
    return group(nodes, opacity=opacity)


def build_logos():
    for color_name in ("amber", "ink", "white"):
        save(f"logos/mark-{color_name}.svg", 112, 112, [mark(0, 0, 112, COLORS[color_name])],
             f"Знак Troika, {color_name}", "logos")
    for language in ("en", "ru"):
        for version in ("primary", "reverse", "mono-black", "mono-white"):
            dark = version in ("reverse", "mono-white")
            nodes = logo(24, 24, 112, dark, version.startswith("mono"), language)
            save(f"logos/logo-{language}-{version}.svg", 510 if language=="en" else 620, 160, nodes,
                 f"Логотип Troika, {language}, {version}", "logos")
        word = "troika" if language=="en" else "тройка"
        for version, color in (("black", INK), ("white", WHITE)):
            save(f"logos/wordmark-{language}-{version}.svg", 390 if language=="en" else 500, 130,
                 [text(word, 16, 98, 120, color, 700, -3.84)],
                 f"Словесный знак {word}", "logos")
    save("logos/logo-stacked.svg", 440, 370,
         [mark(135, 16, 170), text("troika", 43, 305, 130, INK, 700, -4.16)],
         "Вертикальный логотип Troika", "logos")


def build_icons():
    icon_names = ("voice", "text", "tasks", "files", "memory", "search", "phone", "desktop",
                  "settings", "profile", "stop", "shield", "share", "download", "code", "reminder", "add", "check")
    for name in icon_names:
        save(f"icons/{name}.svg", 24, 24, icon_paths(name), f"Troika: {name}", "icons")
    symbols = "".join(f'<symbol id="troika-{name}" viewBox="0 0 24 24">'
                      + "".join(svg_node(node).replace(INK, "currentColor") for node in icon_paths(name))
                      + "</symbol>" for name in icon_names)
    (ROOT/"icons/sprite.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg">'+symbols+"</svg>", encoding="utf-8")
    for variant, bg, fg in (("dark", INK, AMBER), ("light", PAPER, INK), ("amber", AMBER, INK)):
        save(f"app/app-icon-{variant}.svg", 1024, 1024,
             [rect(0, 0, 1024, 1024, bg), mark(210, 210, 604, fg)],
             f"Иконка Troika, {variant}", "app")
        save(f"app/avatar-{variant}.svg", 512, 512,
             [circle(256, 256, 256, bg), mark(104, 104, 304, fg)],
             f"Аватар Troika, {variant}", "app")
    save("app/adaptive-foreground.svg", 108, 108, [mark(24, 24, 60, AMBER)],
         "Android adaptive foreground, safe zone", "app")
    save("app/adaptive-monochrome.svg", 108, 108, [mark(24, 24, 60, INK)],
         "Android adaptive monochrome", "app")
    save("app/favicon.svg", 32, 32, [rect(0, 0, 32, 32, INK, 7), mark(4, 4, 24, AMBER)],
         "Favicon Troika", "app")
    android = ROOT/"app/android"
    android.mkdir(parents=True, exist_ok=True)
    geometry = "".join(f'<path android:fillColor="{AMBER}" android:pathData="{d}"/>' for d in MARK_PATHS)
    (android/"ic_launcher_foreground.xml").write_text(
        '<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="108dp" android:height="108dp" '
        'android:viewportWidth="108" android:viewportHeight="108"><group android:translateX="24" android:translateY="24" '
        'android:scaleX="0.535714" android:scaleY="0.535714">'+geometry+"</group></vector>", encoding="utf-8")
    (android/"ic_launcher_monochrome.xml").write_text(
        (android/"ic_launcher_foreground.xml").read_text(encoding="utf-8").replace(AMBER, "#000000"), encoding="utf-8")
    (android/"ic_launcher_background.xml").write_text(
        f'<shape xmlns:android="http://schemas.android.com/apk/res/android" android:shape="rectangle"><solid android:color="{INK}"/></shape>',
        encoding="utf-8")
    (android/"ic_launcher.xml").write_text(
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android"><background android:drawable="@drawable/ic_launcher_background"/>'
        '<foreground android:drawable="@drawable/ic_launcher_foreground"/><monochrome android:drawable="@drawable/ic_launcher_monochrome"/></adaptive-icon>',
        encoding="utf-8")


def banner(name, w, h, nodes, title):
    save(f"banners/{name}.svg", w, h, nodes, title, "banners")
    save(f"editable/banners/{name}.svg", w, h, nodes, title, "editable", editable=True)


def build_banners():
    banner("hero-1920x960", 1920, 960, [
        rect(0, 0, 1920, 960, INK),
        *logo(96, 72, 94, True),
        *lines(["Скажи,", "что нужно."], 96, 410, 156, PAPER),
        text("Голосовой помощник для ваших задач.", 101, 707, 36, PAPER),
        text("Android и Windows", 101, 860, 28, "#BCB7AE"),
        mark(1250, 178, 590),
    ], "Главный баннер: Скажи, что нужно.")
    banner("social-1200x630", 1200, 630, [
        rect(0, 0, 1200, 630, AMBER),
        *logo(60, 46, 70, mono=True),
        *lines(["От слов", "к делу."], 60, 310, 104),
        text("Голосовой помощник", 65, 535, 27),
        mark(810, 152, 330, INK),
    ], "Социальная карточка Troika")
    banner("post-1080x1080", 1080, 1080, [
        rect(0, 0, 1080, 1080, PAPER),
        *logo(64, 48, 80),
        *lines(["Меньше набора.", "Больше разговора."], 64, 270, 76, max_width=960),
        mark(338, 461, 420),
        text("Голосовой помощник для ваших задач.", 64, 991, 30, max_width=950),
    ], "Квадратная публикация Troika")
    banner("post-1080x1350", 1080, 1350, [
        rect(0, 0, 1080, 1350, INK),
        *logo(64, 52, 80, True),
        *lines(["Ваши задачи.", "Вашим голосом."], 64, 320, 99, PAPER, max_width=950),
        mark(320, 567, 460),
        text("Troika для Android и Windows", 64, 1246, 30, PAPER),
    ], "Вертикальная публикация Troika")
    banner("story-1080x1920", 1080, 1920, [
        rect(0, 0, 1080, 1920, AMBER),
        *logo(72, 260, 90, mono=True),
        *lines(["«Тройка,", "помоги", "с задачей»"], 72, 590, 112, max_width=930),
        mark(262, 985, 540, INK),
        text("Голосовой помощник", 72, 1656, 34),
        text("Android и Windows", 72, 1710, 28),
    ], "История Troika, safe zone 250 px")
    banner("cover-1590x530", 1590, 530, [
        rect(0, 0, 1590, 530, INK),
        *logo(96, 64, 78, True),
        text("От слов к делу.", 96, 307, 98, PAPER, 700, -2.5),
        text("Голосовой помощник для ваших задач", 101, 408, 28, PAPER),
        mark(1175, 100, 322),
    ], "Обложка сообщества Troika")
    banner("youtube-2560x1440", 2560, 1440, [
        rect(0, 0, 2560, 1440, INK),
        mark(-100, -120, 750, AMBER, .1),
        mark(1930, 860, 720, AMBER, .1),
        *logo(570, 580, 108, True),
        text("От слов к делу.", 570, 815, 100, PAPER, 700, -2.5),
        mark(1754, 586, 240),
    ], "Обложка видео: контент в центральной safe zone 1546 x 423")
    banner("feature-1024x500", 1024, 500, [
        rect(0, 0, 1024, 500, AMBER),
        *logo(48, 42, 68, mono=True),
        *lines(["Скажи,", "что нужно."], 48, 259, 81),
        text("Голосовой помощник", 52, 436, 23),
        mark(700, 105, 268, INK),
    ], "Графика приложения Troika")
    banner("web-1440x400", 1440, 400, [
        rect(0, 0, 1440, 400, PAPER),
        *logo(60, 44, 66),
        text("Скажите задачу голосом.", 60, 240, 66, INK, 700, -1.5, max_width=1010),
        text("Troika для Android и Windows", 64, 325, 26),
        mark(1130, 68, 255),
    ], "Горизонтальный светлый баннер Troika")
    banner("email-1200x300", 1200, 300, [
        rect(0, 0, 1200, 300, INK),
        *logo(52, 46, 76, True),
        text("Голосовой помощник для ваших задач.", 55, 232, 33, PAPER),
        mark(955, 58, 180),
    ], "Заголовок письма Troika")
    banner("desktop-1920x1080", 1920, 1080, [
        rect(0, 0, 1920, 1080, INK),
        mark(710, 193, 500),
        text("troika", 725, 910, 153, PAPER, 700, -4.89),
    ], "Обои рабочего стола Troika")


def build_patterns():
    nodes = [rect(0, 0, 448, 448, INK)]
    for row in range(2):
        for col in range(2):
            nodes.append(mark(col*224+40, row*224+40, 144, AMBER, .8 if (row+col)%2==0 else .25))
    save("patterns/voice-tile.svg", 448, 448, nodes, "Бесшовный паттерн Troika", "patterns")
    save("patterns/voice-lines.svg", 1440, 560,
         [rect(0, 0, 1440, 560, PAPER), mark(930, -120, 760, AMBER),
          mark(700, -240, 760, INK, .08)], "Фоновый мотив из логотипа", "patterns")


def build_board():
    nodes = [rect(0, 0, 1600, 1240, WHITE), rect(0, 0, 1600, 585, INK),
             *logo(70, 54, 90, True),
             *lines(["Скажи,", "что нужно."], 70, 300, 109, PAPER),
             text("Голосовой помощник для ваших задач.", 76, 519, 28, PAPER),
             mark(1090, 57, 450)]
    nodes += [text("Знак и логотип", 70, 662, 23, INK, 600), *logo(64, 696, 100),
              *logo(65, 855, 78, mono=True, language="ru"),
              text("Иконка приложения", 1020, 662, 23, INK, 600),
              rect(1020, 700, 150, 150, INK, 34), mark(1049, 729, 92),
              rect(1210, 700, 150, 150, AMBER, 34), mark(1239, 729, 92, INK),
              text("Янтарь. Голос. Действие.", 70, 1040, 31, INK, 600)]
    for index, (label, color) in enumerate((("Янтарь", AMBER), ("Графит", INK), ("Светлый", PAPER), ("Глубокий янтарь", DEEP))):
        x = 70 + index*365
        nodes += [rect(x, 1080, 333, 42, color),
                  text(label, x, 1162, 22), text(color, x, 1195, 17, "#625E57")]
    save("preview/brand-board.svg", 1600, 1240, nodes, "Troika: фирменный стиль", "preview")


def guide_page(title, number, body):
    return {"w": 595.28, "h": 841.89, "title": title, "nodes": [
        rect(0, 0, 595.28, 841.89, WHITE),
        text("Troika / Фирменный стиль", 42, 38, 10, "#555555"),
        text(title, 42, 93, 27, INK, 600),
        *body,
        text("13 октября 2026", 42, 805, 9, "#555555"),
        text(str(number), 544, 805, 9, "#555555"),
    ]}


def para(values, x=42, y=137, size=12, leading=1.5):
    return lines(values, x, y, size, INK, 400, leading=leading)


def build_guide():
    pages = []
    pages.append(guide_page("Голос становится действием", 1, [
        *para(["Troika - персональный голосовой помощник для Android и Windows.",
               "В основе оформления - три линии: голос, задача, результат.",
               "Тёплый янтарь связывает знак с существующей палитрой продукта."]),
        *logo(53, 235, 108),
        text("От слов к делу.", 42, 440, 29, INK, 600),
        *para(["Основная фраза: «Скажи, что нужно».",
               "Короткое описание: «Голосовой помощник для ваших задач».",
               "Название в тексте: Troika или Тройка. В логотипе - troika / тройка.",
               "Не добавляйте «AI», «1.0» или тариф в словесный знак."], y=481),
        *para(["Комплект содержит визуальные материалы, а не подтверждение",
               "готовности функций. Перед публикацией рекламы сверяйте обещания",
               "с текущим продуктом. Изображения не являются скриншотами клиента."], y=653, size=11),
    ]))
    pages.append(guide_page("Логотип и варианты", 2, [
        *para(["Основной вариант: янтарный знак и тёмная словесная часть.",
               "На тёмном фоне используется светлая словесная часть."]),
        *logo(42, 199, 91),
        rect(42, 329, 511, 149, INK), *logo(60, 350, 91, True),
        *logo(42, 534, 74, mono=True, language="ru"),
        text("Монохромный знак", 42, 683, 13, INK, 600),
        mark(43, 696, 54, INK), mark(158, 696, 54, DEEP),
        *para(["SVG с прозрачным фоном. Весь текст - в кривых.",
               "Русская и латинская версии равноправны; не смешивайте их."], x=253, y=706, size=10),
    ]))
    pages.append(guide_page("Размер и свободное поле", 3, [
        *para(["За единицу u принят штрих знака: 16 единиц из 112.",
               "Минимальное свободное поле вокруг видимого контура - 2u.",
               "Поле сохраняется до текста, края носителя и соседних объектов."]),
        rect(120, 237, 312, 312, None, stroke="#BEBEBE", sw=.7),
        mark(120+51, 237+51, 210, INK),
        text("2u", 128, 272, 12), text("2u", 377, 526, 12),
        *para(["Минимум в цифровой среде: знак 24 px; полный логотип 120 px.",
               "Favicon 16 px - отдельный упрощённый формат без слова.",
               "Минимум в печати: знак 8 мм; полный логотип 28 мм."], y=610),
        *para(["Не растягивайте, не поворачивайте и не меняйте расстояния.",
               "Не добавляйте тень, обводку, градиент или новые части.",
               "На фотографии используйте спокойную однотонную подложку."], y=707, size=11),
    ]))
    body = [*para(["Основная палитра совпадает с янтарным акцентом клиента.",
                   "В документах: белый фон, тёмный текст. Цвет служит навигации."])]
    for index, (label, color) in enumerate((("Янтарь", AMBER), ("Графит", INK), ("Светлый", PAPER), ("Глубокий янтарь", DEEP), ("Приглушённый", MUTED))):
        y = 203 + index*84
        body += [rect(42, y, 112, 55, color), text(label, 176, y+23, 14, INK, 600),
                 text(color, 176, y+48, 12)]
    body += para(["Мелкий текст: графит на белом или светлый на графите.",
                  "Янтарный текст на белом не используйте: контраст недостаточен.",
                  "Приглушённый цвет на белом - только для крупной графики.",
                  "PDF и SVG используют RGB. Печатную цветопробу делайте",
                  "с профилем конкретной типографии; CMYK не фиксируется."], y=685, size=11, leading=1.42)
    pages.append(guide_page("Цвет и читаемость", 4, body))
    pages.append(guide_page("Шрифт и голос бренда", 5, [
        *para(["Шрифт - Golos Text: обычный 400, средний 500,",
               "полужирный 600, жирный 700. Поддерживает кириллицу и латиницу.",
               "Оригинальный variable TTF и лицензия OFL находятся в fonts/."]),
        text("Скажите задачу.", 42, 277, 41, INK, 700, -.9),
        text("Тройка, помоги с документом.", 42, 340, 25, INK, 600),
        text("Голосовой помощник для ваших задач.", 42, 394, 15),
        *para(["Пишите коротко и конкретно. Обращайтесь к человеку на «вы».",
               "Действие важнее списка технологий. Одна фраза - одна мысль.",
               "В заголовках обычный регистр, без разрядки и заглавных букв."], y=476),
        text("Фразы для оформления", 42, 582, 16, INK, 600),
        *para(["Скажи, что нужно.", "От слов к делу.", "Ваши задачи. Вашим голосом.",
               "Меньше набора. Больше разговора."], y=622),
        *para(["Не обещайте «всё умеет», постоянное наблюдение, готовую оплату",
               "или автоматическое восстановление локальных файлов."], y=739, size=11),
    ]))
    body = [*para(["Готовые макеты в banners/: открывайте SVG и меняйте масштаб.",
                   "В editable/banners/ - те же макеты с редактируемым текстом.",
                   "Для текста установите вложенный Golos Text."])]
    entries = [
        ("Главный баннер", "1920 x 960"),
        ("Социальная карточка", "1200 x 630"),
        ("Квадратная публикация", "1080 x 1080"),
        ("Вертикальная публикация", "1080 x 1350"),
        ("История", "1080 x 1920"),
        ("Обложка сообщества", "1590 x 530"),
        ("Обложка видео", "2560 x 1440"),
        ("Графика приложения", "1024 x 500"),
        ("Горизонтальный баннер", "1440 x 400"),
        ("Заголовок письма", "1200 x 300"),
        ("Обои рабочего стола", "1920 x 1080"),
    ]
    for index, (label, dimensions) in enumerate(entries):
        y = 233 + index*32
        body += [text(label, 42, y, 12), text(dimensions, 407, y, 12)]
    body += para(["Истории: основной контент между y=250 и y=1720.",
                  "Обложка видео: основной контент внутри центральных",
                  "1546 x 423 px. Дополнительный фон может обрезаться.",
                  "После размещения проверьте предпросмотр площадки:",
                  "элементы интерфейса и кадрирование могут отличаться."], y=649, size=11)
    pages.append(guide_page("Баннеры и форматы", 6, body))
    body = [*para(["18 outline-иконок. Сетка 24 x 24, штрих 1,75 px,",
                   "закруглённые окончания. Не меняйте толщину отдельно у иконки.",
                   "SVG sprite использует currentColor для цвета интерфейса."])]
    names = ("voice", "text", "tasks", "files", "memory", "search", "phone", "desktop", "settings",
             "profile", "stop", "shield", "share", "download", "code", "reminder", "add", "check")
    for index, name in enumerate(names):
        x, y = 47+(index%6)*86, 214+(index//6)*74
        body += [group(icon_paths(name), x+13, y, 1.5), text(name, x, y+57, 9)]
    body += [text("Иконка приложения", 42, 492, 16, INK, 600),
             rect(42, 522, 100, 100, INK, 23), mark(62, 542, 60),
             rect(173, 522, 100, 100, AMBER, 23), mark(193, 542, 60, INK)]
    body += para(["Android: foreground, background, monochrome и adaptive XML.",
                  "Windows: ICO с размерами от 16 до 256 px.",
                  "Исходник приложения квадратный: системную маску не запекайте.",
                  "Круглые аватары - отдельные файлы."], y=660, size=11)
    pages.append(guide_page("Иконки и приложение", 7, body))
    for index, page in enumerate(pages):
        save(f"guide/pages/page-{index+1:02}.svg", page["w"], page["h"], page["nodes"],
             page["title"], "guide")
    pdf_file("guide/Troika-Brand-Guide.pdf", pages, physical=True)
    pdf_file("exports/pdf/Troika-Logos.pdf",
             [SCENES["preview/brand-board.svg"],
              {"w": 1000, "h": 700, "nodes": [rect(0, 0, 1000, 700, WHITE),
               *logo(48, 50, 130), *logo(48, 255, 130, mono=True, language="ru"),
               mark(50, 475, 150), mark(300, 475, 150, INK)]}])
    pdf_file("exports/pdf/Troika-Banners.pdf",
             [SCENES[item["file"]] for item in CATALOG if item["category"]=="banners"])


def luminance(hex_color):
    rgb = [int(hex_color[i:i+2], 16)/255 for i in (1, 3, 5)]
    values = [v/12.92 if v <= .04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    return sum(a*b for a, b in zip(values, (.2126, .7152, .0722)))


def contrast(a, b):
    values = sorted((luminance(a), luminance(b)))
    return round((values[1]+.05)/(values[0]+.05), 2)


def write_metadata():
    tokens = {
        "brand": "Troika", "version": "2026-10-13", "colors": COLORS,
        "typography": {"family": "Golos Text", "weights": [400, 500, 600, 700],
                       "source": "https://github.com/googlefonts/golos-text", "license": "OFL-1.1"},
        "logo": {"grid": 112, "stroke_unit": 16, "clear_space": 32,
                 "min_mark_px": 24, "min_lockup_px": 120, "min_mark_mm": 8, "min_lockup_mm": 28},
        "icons": {"grid": 24, "stroke": 1.75},
        "contrast": {f"{a}_on_{b}": contrast(COLORS[a], COLORS[b])
                     for a, b in (("paper", "ink"), ("ink", "amber"), ("amber", "ink"),
                                  ("amber", "white"), ("muted", "white"), ("muted", "ink"))},
    }
    (ROOT/"tokens.json").write_text(json.dumps(tokens, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (ROOT/"catalog.json").write_text(json.dumps(CATALOG, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (ROOT/"tokens.css").write_text(":root {\n"+ "".join(f"  --troika-{key}: {value};\n" for key, value in COLORS.items())
                                  + '  --troika-font: "Golos Text", sans-serif;\n}\n', encoding="utf-8")
    (ROOT/"guide/validation.json").write_text(json.dumps({
        "vector_scenes": len(CATALOG), "text_runs_checked": len(TEXT_BOUNDS),
        "all_text_within_artboards": True, "font_sha256": hashlib.sha256(FONT_FILE.read_bytes()).hexdigest(),
        "no_raster_in_vector_masters": True,
        "pdf_outputs": {"brand_guide_pages": 7, "logo_pages": 2, "banner_pages": 11},
    }, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def build():
    build_logos()
    build_icons()
    build_banners()
    build_patterns()
    build_board()
    build_guide()
    write_metadata()
    print(json.dumps({"svg_scenes": len(CATALOG), "text_runs_checked": len(TEXT_BOUNDS),
                      "pdf_files": 3, "output": str(ROOT)}, ensure_ascii=False))


if __name__ == "__main__":
    build()
