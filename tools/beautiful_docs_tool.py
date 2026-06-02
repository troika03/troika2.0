"""
Красивые презентации, PDF и документы — с темами, цветами, иконками
и авто-генерацией изображений через Pollinations.AI.

В отличие от `documents_tool.py` (минималистичные базовые документы),
этот модуль делает дизайнерские артефакты:
  - phone_create_beautiful_pptx — презентация с темой, иконками и фоновыми изображениями
  - phone_create_beautiful_pdf — PDF с акцентным заголовком, цветными секциями
  - phone_create_infographic — одностраничный PDF с инфографикой
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import tempfile
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)


def _bridge():
    from gateway.platforms.phone_bridge import bridge
    return bridge


def _check_phone_connected():
    try:
        return _bridge().is_connected()
    except Exception:
        return False


def _safe_filename(name: str, ext: str) -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip("._ ")
    if not base:
        base = "document"
    if not base.lower().endswith("." + ext):
        base = f"{base}.{ext}"
    return base


async def _send_to_phone(filename: str, data: bytes, directory: str = "Download") -> Dict[str, Any]:
    encoded = base64.b64encode(data).decode("ascii")
    path = filename if directory.lower() in ("download", "downloads", "") else f"{directory}/{filename}"
    # Большой PPTX с фоновыми картинками может быть 5-10MB → шлём дольше.
    # Округляем: 1MB ≈ 30 секунд по слабому Tailscale-соединению.
    timeout = max(60.0, len(encoded) / 30_000)
    return await _bridge().send_command(
        "file_write",
        {"path": path, "content": encoded, "encoding": "base64", "append": False},
        timeout=timeout,
    )


# ============================================================================
# Темы (цветовые палитры и шрифты)
# ============================================================================

THEMES = {
    "modern_blue": {
        "primary": (0x1E, 0x40, 0xAF),       # глубокий синий
        "accent": (0x60, 0xA5, 0xFA),         # светлый голубой
        "bg_dark": (0x0F, 0x17, 0x2A),
        "bg_light": (0xF1, 0xF5, 0xF9),
        "text_dark": (0x1E, 0x29, 0x3B),
        "text_light": (0xFF, 0xFF, 0xFF),
    },
    "warm_sunset": {
        "primary": (0xDC, 0x26, 0x26),
        "accent": (0xF9, 0x73, 0x16),
        "bg_dark": (0x44, 0x14, 0x0A),
        "bg_light": (0xFE, 0xF3, 0xC7),
        "text_dark": (0x44, 0x14, 0x0A),
        "text_light": (0xFF, 0xFF, 0xFF),
    },
    "forest_green": {
        "primary": (0x16, 0x65, 0x34),
        "accent": (0x4A, 0xDE, 0x80),
        "bg_dark": (0x14, 0x2F, 0x21),
        "bg_light": (0xF0, 0xFD, 0xF4),
        "text_dark": (0x14, 0x2F, 0x21),
        "text_light": (0xFF, 0xFF, 0xFF),
    },
    "elegant_purple": {
        "primary": (0x6D, 0x28, 0xD9),
        "accent": (0xC0, 0x84, 0xFC),
        "bg_dark": (0x2E, 0x10, 0x65),
        "bg_light": (0xFA, 0xF5, 0xFF),
        "text_dark": (0x2E, 0x10, 0x65),
        "text_light": (0xFF, 0xFF, 0xFF),
    },
    "minimalist_mono": {
        "primary": (0x18, 0x18, 0x18),
        "accent": (0x52, 0x52, 0x52),
        "bg_dark": (0x0A, 0x0A, 0x0A),
        "bg_light": (0xFA, 0xFA, 0xFA),
        "text_dark": (0x18, 0x18, 0x18),
        "text_light": (0xFF, 0xFF, 0xFF),
    },
    "ocean_teal": {
        "primary": (0x0F, 0x76, 0x6E),
        "accent": (0x5E, 0xEA, 0xD4),
        "bg_dark": (0x04, 0x2F, 0x2E),
        "bg_light": (0xF0, 0xFD, 0xFA),
        "text_dark": (0x04, 0x2F, 0x2E),
        "text_light": (0xFF, 0xFF, 0xFF),
    },
    "vibrant_pink": {
        "primary": (0xE9, 0x1E, 0x63),
        "accent": (0xF8, 0xBB, 0xD0),
        "bg_dark": (0x42, 0x0E, 0x21),
        "bg_light": (0xFD, 0xF2, 0xF8),
        "text_dark": (0x42, 0x0E, 0x21),
        "text_light": (0xFF, 0xFF, 0xFF),
    },
    "corporate_navy": {
        "primary": (0x0B, 0x39, 0x67),
        "accent": (0xCB, 0xA1, 0x35),
        "bg_dark": (0x07, 0x1E, 0x34),
        "bg_light": (0xF8, 0xFA, 0xFC),
        "text_dark": (0x0B, 0x39, 0x67),
        "text_light": (0xFF, 0xFF, 0xFF),
    },
}


def _pick_theme(name: str | None) -> Dict[str, Any]:
    if not name:
        return THEMES["modern_blue"]
    name = name.lower().replace("-", "_").replace(" ", "_")
    return THEMES.get(name, THEMES["modern_blue"])


# ============================================================================
# Pollinations image fetcher (внутренний)
# ============================================================================

async def _fetch_pollinations(prompt: str, width: int = 1280, height: int = 720,
                              model: str = "flux", seed: int | None = None) -> bytes | None:
    """Скачать изображение с Pollinations в bytes. Возвращает None при ошибке."""
    if not prompt.strip():
        return None
    encoded = urllib.parse.quote(prompt[:1500])
    # turbo — единственная действительно бесплатная модель Pollinations (по состоянию на 2026)
    # flux/etc возвращают 402 без token. Перебираем в порядке убывания качества.
    models_to_try = [model] if model != "flux" else ["flux", "turbo"]
    if "turbo" not in models_to_try:
        models_to_try.append("turbo")

    token = os.environ.get("POLLINATIONS_TOKEN", "")
    for m in models_to_try:
        params = f"model={m}&width={width}&height={height}&nologo=true&enhance=true&safe=false"
        if seed is not None:
            params += f"&seed={seed}"
        if token:
            params += f"&token={token}"
        url = f"https://image.pollinations.ai/prompt/{encoded}?{params}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=180)) as r:
                    if r.status == 402:
                        logger.warning("pollinations 402 (paywall) for model=%s, trying next", m)
                        continue
                    if r.status != 200:
                        logger.warning("pollinations %s for prompt %s", r.status, prompt[:50])
                        continue
                    data = await r.read()
                    if len(data) < 1000:
                        # Слишком маленький файл — скорее всего HTML с ошибкой
                        logger.warning("pollinations returned tiny payload %db, treating as error", len(data))
                        continue
                    return data
        except Exception as e:
            logger.warning("pollinations fetch failed for %s: %s", m, e)
    return None


def _register_unicode_font():
    """Регистрирует системный шрифт с поддержкой кириллицы и возвращает его имя."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    for path, name, bold_path in [
        (r"C:\Windows\Fonts\segoeui.ttf", "AppFont", r"C:\Windows\Fonts\segoeuib.ttf"),
        (r"C:\Windows\Fonts\arial.ttf", "AppFont", r"C:\Windows\Fonts\arialbd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "AppFont",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont(name, path))
                if bold_path and os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont(f"{name}-Bold", bold_path))
                return name
            except Exception:
                continue
    return "Helvetica"


# ============================================================================
# 1. Beautiful PPTX
# ============================================================================

async def _handle_beautiful_pptx(args: Dict[str, Any], **kw) -> str:
    """Создать дизайнерскую презентацию.

    args:
      title (str), subtitle (str?), filename (str?), theme (str?),
      author (str?), with_images (bool, default True),
      slides: [
        {title, content?, bullets?, image_prompt?, notes?}, ...
      ]
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt, Emu
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    except Exception as e:
        return json.dumps({"ok": False, "error": f"python-pptx missing: {e}"}, ensure_ascii=False)

    title = (args.get("title") or "Презентация").strip()
    subtitle = (args.get("subtitle") or "").strip()
    author = (args.get("author") or "").strip()
    slides_def = args.get("slides") or []
    if not slides_def:
        return json.dumps({"ok": False, "error": "missing 'slides'"}, ensure_ascii=False)

    theme = _pick_theme(args.get("theme"))
    with_images = bool(args.get("with_images", True))
    filename = _safe_filename(args.get("filename") or title, "pptx")

    prs = Presentation()
    prs.slide_width = Inches(13.333)   # 16:9
    prs.slide_height = Inches(7.5)
    slide_w, slide_h = prs.slide_width, prs.slide_height

    def rgb(t): return RGBColor(t[0], t[1], t[2])

    # Параллельно скачаем фоновое изображение для титула и для каждого слайда с image_prompt
    image_tasks: List[Tuple[str, asyncio.Task]] = []
    if with_images:
        # Cover image
        cover_prompt = args.get("cover_image_prompt") or f"abstract minimalist background, {args.get('cover_style', 'modern professional')}, related to: {title}"
        image_tasks.append(("__cover__", asyncio.create_task(
            _fetch_pollinations(cover_prompt, width=1920, height=1080))))
        for idx, s in enumerate(slides_def):
            ip = s.get("image_prompt")
            if ip:
                image_tasks.append((f"slide{idx}", asyncio.create_task(
                    _fetch_pollinations(ip, width=1280, height=720))))

    images: Dict[str, bytes | None] = {}
    if image_tasks:
        for key, task in image_tasks:
            try:
                images[key] = await task
            except Exception:
                images[key] = None

    blank_layout = prs.slide_layouts[6]  # пустой слайд — рисуем сами

    # ===== TITLE SLIDE ============================================
    slide = prs.slides.add_slide(blank_layout)
    # Фон: цвет theme.bg_dark
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, slide_w, slide_h)
    bg.fill.solid()
    bg.fill.fore_color.rgb = rgb(theme["bg_dark"])
    bg.line.fill.background()

    # Фоновая картинка (если есть) — НЕ перекрываем после неё, чтобы было видно
    cover = images.get("__cover__")
    if cover:
        try:
            tmp = io.BytesIO(cover)
            slide.shapes.add_picture(tmp, 0, 0, slide_w, slide_h)
        except Exception as e:
            logger.warning("title cover add failed: %s", e)
    else:
        # Без обложки — насыщенный декор: градиент-имитация (две полосы) + круги + инициал
        from pptx.util import Emu
        # Имитация градиента: широкая горизонтальная полоса primary поверх bg_dark, нижняя половина
        grad_band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                           0, Inches(4),
                                           slide_w, slide_h - Inches(4))
        grad_band.fill.solid()
        grad_band.fill.fore_color.rgb = rgb(theme["primary"])
        grad_band.line.fill.background()
        # Большой круг справа-сверху (акцентный цвет, частично за границей)
        circle = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                                        Inches(9), Inches(-2),
                                        Inches(7), Inches(7))
        circle.fill.solid()
        circle.fill.fore_color.rgb = rgb(theme["accent"])
        circle.line.fill.background()
        # Средний круг слева-внизу
        circle2 = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                                         Inches(-1.5), Inches(5.5),
                                         Inches(3.5), Inches(3.5))
        circle2.fill.solid()
        circle2.fill.fore_color.rgb = rgb(theme["text_light"])
        circle2.line.fill.background()
        # Огромный полупрозрачный инициал заголовка в правом-нижнем углу
        if title:
            initial = title.strip()[:1].upper()
            if initial:
                init_box = slide.shapes.add_textbox(Inches(9.5), Inches(3),
                                                    Inches(4), Inches(4.5))
                init_p = init_box.text_frame.paragraphs[0]
                init_p.text = initial
                init_p.font.name = "Calibri"
                init_p.font.size = Pt(280)
                init_p.font.bold = True
                init_p.font.color.rgb = rgb(theme["accent"])
                init_p.alignment = PP_ALIGN.CENTER
        # Декоративные точки-узор слева-вверху
        for dx in range(4):
            for dy in range(3):
                dot = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                                              Inches(0.7 + dx * 0.35),
                                              Inches(0.5 + dy * 0.35),
                                              Inches(0.12), Inches(0.12))
                dot.fill.solid()
                dot.fill.fore_color.rgb = rgb(theme["accent"])
                dot.line.fill.background()

    # Акцентная полоса слева
    accent_bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                        Inches(0.5), Inches(2.5),
                                        Inches(0.15), Inches(2.5))
    accent_bar.fill.solid()
    accent_bar.fill.fore_color.rgb = rgb(theme["accent"])
    accent_bar.line.fill.background()

    # Title
    title_box = slide.shapes.add_textbox(Inches(0.9), Inches(2.5),
                                         Inches(11.5), Inches(1.8))
    tf = title_box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.name = "Calibri"
    p.font.size = Pt(54)
    p.font.bold = True
    p.font.color.rgb = rgb(theme["text_light"])

    if subtitle:
        sub_box = slide.shapes.add_textbox(Inches(0.9), Inches(4.4),
                                           Inches(11.5), Inches(0.8))
        sp = sub_box.text_frame.paragraphs[0]
        sp.text = subtitle
        sp.font.name = "Calibri"
        sp.font.size = Pt(24)
        sp.font.color.rgb = rgb(theme["accent"])

    if author:
        a_box = slide.shapes.add_textbox(Inches(0.9), Inches(6.5),
                                         Inches(11.5), Inches(0.5))
        ap = a_box.text_frame.paragraphs[0]
        ap.text = author
        ap.font.name = "Calibri"
        ap.font.size = Pt(14)
        ap.font.color.rgb = rgb(theme["text_light"])

    # ===== CONTENT SLIDES =========================================
    for idx, s in enumerate(slides_def):
        slide = prs.slides.add_slide(blank_layout)

        # Фон светлый
        bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, slide_w, slide_h)
        bg.fill.solid()
        bg.fill.fore_color.rgb = rgb(theme["bg_light"])
        bg.line.fill.background()

        # Верхняя цветная полоса
        top_bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, slide_w, Inches(0.3))
        top_bar.fill.solid()
        top_bar.fill.fore_color.rgb = rgb(theme["primary"])
        top_bar.line.fill.background()

        s_title = s.get("title") or ""
        bullets = s.get("bullets") or []
        content = s.get("content") or ""
        img = images.get(f"slide{idx}")

        # Title
        t_box = slide.shapes.add_textbox(Inches(0.7), Inches(0.6),
                                         Inches(12), Inches(1))
        tp = t_box.text_frame.paragraphs[0]
        tp.text = s_title
        tp.font.name = "Calibri"
        tp.font.size = Pt(36)
        tp.font.bold = True
        tp.font.color.rgb = rgb(theme["primary"])

        # Акцентная линия под заголовком
        line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                      Inches(0.7), Inches(1.65),
                                      Inches(1.5), Inches(0.06))
        line.fill.solid()
        line.fill.fore_color.rgb = rgb(theme["accent"])
        line.line.fill.background()

        # Layout: если есть картинка — две колонки. Без картинки — декоративный блок.
        if img:
            content_w = Inches(7)
            img_x = Inches(8)
            img_w = Inches(5)
            img_y = Inches(2)
            img_h = Inches(5)
            try:
                slide.shapes.add_picture(io.BytesIO(img), img_x, img_y, img_w, img_h)
            except Exception as e:
                logger.warning("slide %d image add failed: %s", idx, e)
                content_w = Inches(12)
        else:
            # Без картинки рисуем декоративный геометрический блок справа
            content_w = Inches(7.5)
            # Большой круг primary
            deco = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                                          Inches(9), Inches(2),
                                          Inches(4), Inches(4))
            deco.fill.solid()
            deco.fill.fore_color.rgb = rgb(theme["primary"])
            deco.line.fill.background()
            # Маленький круг внизу — акцент
            deco2 = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                                           Inches(10.5), Inches(5.5),
                                           Inches(1.5), Inches(1.5))
            deco2.fill.solid()
            deco2.fill.fore_color.rgb = rgb(theme["accent"])
            deco2.line.fill.background()
            # Большой инициал заголовка — вместо номера
            initial = (s_title or str(idx + 1)).strip()[:1].upper()
            num_box = slide.shapes.add_textbox(Inches(9), Inches(2.3),
                                                Inches(4), Inches(3.5))
            np_ = num_box.text_frame.paragraphs[0]
            np_.text = initial
            np_.font.name = "Calibri"
            np_.font.size = Pt(180)
            np_.font.bold = True
            np_.font.color.rgb = rgb(theme["text_light"])
            np_.alignment = PP_ALIGN.CENTER
            # Маленькая надпись "номер слайда" под кругом
            sn_box = slide.shapes.add_textbox(Inches(9), Inches(6.0),
                                               Inches(4), Inches(0.4))
            sn_p = sn_box.text_frame.paragraphs[0]
            sn_p.text = f"— {str(idx + 1).zfill(2)} —"
            sn_p.font.name = "Calibri"
            sn_p.font.size = Pt(14)
            sn_p.font.color.rgb = rgb(theme["accent"])
            sn_p.alignment = PP_ALIGN.CENTER

        # Декоративный узор внизу слайда — пять акцентных точек
        for di in range(5):
            d = slide.shapes.add_shape(MSO_SHAPE.OVAL,
                                        Inches(0.7 + di * 0.25),
                                        Inches(7.05), Inches(0.1), Inches(0.1))
            d.fill.solid()
            d.fill.fore_color.rgb = rgb(theme["accent"])
            d.line.fill.background()

        # Content / bullets
        c_box = slide.shapes.add_textbox(Inches(0.7), Inches(2),
                                         content_w, Inches(5))
        c_tf = c_box.text_frame
        c_tf.word_wrap = True
        if bullets:
            for i, b in enumerate(bullets):
                p = c_tf.paragraphs[0] if i == 0 else c_tf.add_paragraph()
                p.text = f"●  {b}"
                p.font.name = "Calibri"
                p.font.size = Pt(22)
                p.font.color.rgb = rgb(theme["text_dark"])
                p.space_after = Pt(12)
        elif content:
            for i, para in enumerate(content.split("\n\n")):
                if not para.strip():
                    continue
                p = c_tf.paragraphs[0] if i == 0 else c_tf.add_paragraph()
                p.text = para
                p.font.name = "Calibri"
                p.font.size = Pt(20)
                p.font.color.rgb = rgb(theme["text_dark"])
                p.space_after = Pt(8)

        # Footer — номер слайда
        f_box = slide.shapes.add_textbox(Inches(12.5), Inches(7.05),
                                         Inches(0.7), Inches(0.4))
        fp = f_box.text_frame.paragraphs[0]
        fp.text = f"{idx + 1} / {len(slides_def)}"
        fp.font.name = "Calibri"
        fp.font.size = Pt(11)
        fp.font.color.rgb = rgb(theme["text_dark"])
        fp.alignment = PP_ALIGN.RIGHT

        if s.get("notes"):
            slide.notes_slide.notes_text_frame.text = s["notes"]

    buf = io.BytesIO()
    prs.save(buf)
    data = buf.getvalue()
    result = await _send_to_phone(filename, data, args.get("directory") or "Download")
    return json.dumps({"ok": result.get("ok", False), "tool": "beautiful_pptx",
                       "filename": filename, "slides": len(slides_def),
                       "size": len(data), "theme": args.get("theme") or "modern_blue",
                       "with_images": with_images,
                       "phone_result": result}, ensure_ascii=False)


# ============================================================================
# 2. Beautiful PDF
# ============================================================================

async def _handle_beautiful_pdf(args: Dict[str, Any], **kw) -> str:
    """Дизайнерский PDF с акцентным заголовком и цветными секциями."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm, mm
        from reportlab.lib.colors import HexColor, Color
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem,
            PageBreak, Image, Table, TableStyle,
        )
        from reportlab.lib import colors
    except Exception as e:
        return json.dumps({"ok": False, "error": f"reportlab missing: {e}"}, ensure_ascii=False)

    title = (args.get("title") or "Документ").strip()
    subtitle = (args.get("subtitle") or "").strip()
    sections = args.get("sections") or []
    theme = _pick_theme(args.get("theme"))
    with_cover_image = bool(args.get("with_cover_image", True))
    filename = _safe_filename(args.get("filename") or title, "pdf")

    font_name = _register_unicode_font()
    bold_font = f"{font_name}-Bold" if font_name != "Helvetica" else "Helvetica-Bold"

    # Скачать обложку если нужно
    cover_image_bytes = None
    if with_cover_image:
        prompt = args.get("cover_image_prompt") or f"abstract elegant background related to {title}, professional, soft colors"
        cover_image_bytes = await _fetch_pollinations(prompt, width=1600, height=900)

    def rgb_color(t):
        return Color(t[0] / 255, t[1] / 255, t[2] / 255)

    primary = rgb_color(theme["primary"])
    accent = rgb_color(theme["accent"])
    text_dark = rgb_color(theme["text_dark"])

    buf = io.BytesIO()

    # Создаём документ с кастомным фоном страницы
    def first_page(canvas, doc):
        canvas.saveState()
        if cover_image_bytes:
            try:
                from reportlab.lib.utils import ImageReader
                img = ImageReader(io.BytesIO(cover_image_bytes))
                canvas.drawImage(img, 0, A4[1] - 11 * cm, width=A4[0], height=11 * cm,
                                 preserveAspectRatio=False, mask='auto')
                # затемнение
                canvas.setFillColorRGB(theme["bg_dark"][0] / 255,
                                       theme["bg_dark"][1] / 255,
                                       theme["bg_dark"][2] / 255, alpha=0.45)
                canvas.rect(0, A4[1] - 11 * cm, A4[0], 11 * cm, fill=1, stroke=0)
            except Exception as e:
                logger.warning("cover image draw failed: %s", e)

        # Title text overlay
        canvas.setFillColor(rgb_color(theme["text_light"]))
        canvas.setFont(bold_font, 32)
        canvas.drawString(2 * cm, A4[1] - 5 * cm, title[:60])
        if subtitle:
            canvas.setFont(font_name, 16)
            canvas.setFillColor(rgb_color(theme["accent"]))
            canvas.drawString(2 * cm, A4[1] - 7 * cm, subtitle[:80])
        # accent bar
        canvas.setFillColor(accent)
        canvas.rect(2 * cm, A4[1] - 8.5 * cm, 6 * cm, 0.2 * cm, fill=1, stroke=0)
        canvas.restoreState()

    def later_pages(canvas, doc):
        canvas.saveState()
        # Header strip
        canvas.setFillColor(primary)
        canvas.rect(0, A4[1] - 1.2 * cm, A4[0], 1.2 * cm, fill=1, stroke=0)
        canvas.setFillColor(rgb_color(theme["text_light"]))
        canvas.setFont(bold_font, 11)
        canvas.drawString(2 * cm, A4[1] - 0.8 * cm, title[:80])
        # Footer
        canvas.setFillColor(text_dark)
        canvas.setFont(font_name, 9)
        canvas.drawRightString(A4[0] - 2 * cm, 1 * cm, f"стр. {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2.5 * cm, rightMargin=2.5 * cm,
                            topMargin=2 * cm, bottomMargin=2 * cm)

    styles = {
        "h1": ParagraphStyle("h1", fontName=bold_font, fontSize=20,
                             textColor=primary, spaceBefore=12, spaceAfter=12,
                             leading=26),
        "h2": ParagraphStyle("h2", fontName=bold_font, fontSize=15,
                             textColor=primary, spaceBefore=8, spaceAfter=8,
                             leading=20),
        "body": ParagraphStyle("body", fontName=font_name, fontSize=11,
                               textColor=text_dark, leading=16,
                               spaceAfter=10, alignment=4),  # justify
        "callout": ParagraphStyle("callout", fontName=font_name, fontSize=12,
                                  textColor=primary, leading=18,
                                  backColor=Color(theme["bg_light"][0] / 255,
                                                  theme["bg_light"][1] / 255,
                                                  theme["bg_light"][2] / 255),
                                  borderColor=accent, borderWidth=1, borderPadding=10,
                                  leftIndent=10, rightIndent=10,
                                  spaceBefore=12, spaceAfter=12),
    }

    # Первая страница оставляем для cover (через canvas), остальной контент идёт со 2-й
    story: List = [PageBreak()]

    for sec in sections:
        heading = sec.get("heading") or sec.get("title")
        if heading:
            story.append(Paragraph(heading, styles["h1"]))
        sub = sec.get("subheading")
        if sub:
            story.append(Paragraph(sub, styles["h2"]))
        text = sec.get("body") or sec.get("content") or ""
        for para in text.split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.replace("\n", "<br/>"), styles["body"]))
        bullets = sec.get("bullets")
        if bullets:
            items = [ListItem(Paragraph(b, styles["body"]), bulletColor=primary)
                     for b in bullets]
            story.append(ListFlowable(items, bulletType="bullet", start="•"))
            story.append(Spacer(1, 0.3 * cm))
        callout = sec.get("callout")
        if callout:
            story.append(Paragraph(callout, styles["callout"]))

    if not sections:
        body = args.get("content", "")
        for para in body.split("\n\n"):
            if para.strip():
                story.append(Paragraph(para, styles["body"]))

    doc.build(story, onFirstPage=first_page, onLaterPages=later_pages)
    data = buf.getvalue()
    result = await _send_to_phone(filename, data, args.get("directory") or "Download")
    return json.dumps({"ok": result.get("ok", False), "tool": "beautiful_pdf",
                       "filename": filename, "size": len(data),
                       "theme": args.get("theme") or "modern_blue",
                       "phone_result": result}, ensure_ascii=False)


# ============================================================================
# 3. Инфографика (одностраничный PDF с числами и иконками)
# ============================================================================

async def _handle_infographic(args: Dict[str, Any], **kw) -> str:
    """Инфографика на одну страницу: заголовок + 3-6 блоков "число + подпись"."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm
        from reportlab.lib.colors import Color
        from reportlab.pdfgen import canvas as pdf_canvas
    except Exception as e:
        return json.dumps({"ok": False, "error": f"reportlab missing: {e}"}, ensure_ascii=False)

    title = (args.get("title") or "Инфографика").strip()
    subtitle = (args.get("subtitle") or "").strip()
    stats = args.get("stats") or []  # [{value, label, hint?}]
    if not stats:
        return json.dumps({"ok": False, "error": "missing 'stats' (list of {value, label})"}, ensure_ascii=False)
    theme = _pick_theme(args.get("theme"))
    filename = _safe_filename(args.get("filename") or title, "pdf")

    font_name = _register_unicode_font()
    bold_font = f"{font_name}-Bold" if font_name != "Helvetica" else "Helvetica-Bold"

    def rgb_color(t):
        return Color(t[0] / 255, t[1] / 255, t[2] / 255)

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # Фон
    c.setFillColor(rgb_color(theme["bg_dark"]))
    c.rect(0, 0, W, H, fill=1, stroke=0)

    # Title
    c.setFillColor(rgb_color(theme["text_light"]))
    c.setFont(bold_font, 28)
    c.drawString(2 * cm, H - 3 * cm, title)
    if subtitle:
        c.setFont(font_name, 14)
        c.setFillColor(rgb_color(theme["accent"]))
        c.drawString(2 * cm, H - 4 * cm, subtitle)
    # accent bar
    c.setFillColor(rgb_color(theme["accent"]))
    c.rect(2 * cm, H - 4.7 * cm, 4 * cm, 0.15 * cm, fill=1, stroke=0)

    # Stats grid — 3 в строке, минимум 1 строка
    n = len(stats)
    cols = 3 if n >= 3 else n
    rows = (n + cols - 1) // cols
    grid_top = H - 6 * cm
    grid_bottom = 3 * cm
    cell_w = (W - 4 * cm) / cols
    cell_h = (grid_top - grid_bottom) / rows

    for i, item in enumerate(stats):
        r = i // cols
        col = i % cols
        x = 2 * cm + col * cell_w
        y = grid_top - (r + 1) * cell_h

        # Карточка
        c.setFillColor(rgb_color(theme["primary"]))
        c.roundRect(x + 0.3 * cm, y + 0.3 * cm,
                    cell_w - 0.6 * cm, cell_h - 0.6 * cm,
                    0.4 * cm, fill=1, stroke=0)
        # Большое значение
        value = str(item.get("value", ""))
        c.setFont(bold_font, 40)
        c.setFillColor(rgb_color(theme["text_light"]))
        c.drawCentredString(x + cell_w / 2, y + cell_h - 2.2 * cm, value[:8])
        # Подпись
        label = str(item.get("label", ""))
        c.setFont(font_name, 12)
        c.setFillColor(rgb_color(theme["accent"]))
        c.drawCentredString(x + cell_w / 2, y + cell_h / 2 - 0.5 * cm, label[:40])
        # Hint
        hint = item.get("hint")
        if hint:
            c.setFont(font_name, 9)
            c.setFillColor(rgb_color(theme["text_light"]))
            c.drawCentredString(x + cell_w / 2, y + 0.9 * cm, str(hint)[:50])

    # Footer
    c.setFillColor(rgb_color(theme["text_light"]))
    c.setFont(font_name, 9)
    c.drawString(2 * cm, 1.3 * cm, args.get("footer", "Hermes Agent"))

    c.showPage()
    c.save()
    data = buf.getvalue()
    result = await _send_to_phone(filename, data, args.get("directory") or "Download")
    return json.dumps({"ok": result.get("ok", False), "tool": "infographic",
                       "filename": filename, "stats_count": len(stats),
                       "size": len(data), "phone_result": result}, ensure_ascii=False)


# ============================================================================
# Schemas
# ============================================================================

_THEME_LIST = ", ".join(THEMES.keys())

BEAUTIFUL_PPTX_SCHEMA = {
    "name": "phone_create_beautiful_pptx",
    "description": (
        "★ DEFAULT TOOL FOR ANY PRESENTATION ★ "
        "Always use this for ANY user request involving slides/презентация/презинтация/презентацию/slide deck — "
        "even if the user does NOT say 'beautiful' or 'красивая'. "
        "Generates a designer-quality PowerPoint with theme colors, accents, decorative shapes "
        f"and optional AI illustrations via Pollinations. Themes: {_THEME_LIST}. "
        "Pick a fitting theme based on the topic (экология→forest_green, бизнес→corporate_navy, "
        "технологии→modern_blue, искусство→vibrant_pink, etc). "
        "Each slide can have an optional 'image_prompt'. "
        "Do NOT use phone_create_pptx — it produces ugly white slides."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "subtitle": {"type": "string"},
            "author": {"type": "string"},
            "theme": {"type": "string", "description": f"One of: {_THEME_LIST}. Default modern_blue."},
            "with_images": {"type": "boolean", "description": "Auto-generate illustrations. Default true."},
            "cover_image_prompt": {"type": "string", "description": "Override cover image prompt."},
            "slides": {
                "type": "array",
                "description": "Each: {title, content?, bullets?, image_prompt?, notes?}",
                "items": {"type": "object"},
            },
            "filename": {"type": "string"},
            "directory": {"type": "string"},
        },
        "required": ["title", "slides"],
    },
}

BEAUTIFUL_PDF_SCHEMA = {
    "name": "phone_create_beautiful_pdf",
    "description": (
        f"Generate a designer-quality PDF with cover image, themed colors and sections. Themes: {_THEME_LIST}. "
        "Each section can have {heading, subheading?, body, bullets?, callout?}. "
        "Use when user wants a 'pretty', 'nice', 'красивый' document."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "subtitle": {"type": "string"},
            "theme": {"type": "string"},
            "with_cover_image": {"type": "boolean"},
            "cover_image_prompt": {"type": "string"},
            "sections": {"type": "array", "items": {"type": "object"}},
            "content": {"type": "string", "description": "Shortcut if no sections."},
            "filename": {"type": "string"},
            "directory": {"type": "string"},
        },
        "required": ["title"],
    },
}

INFOGRAPHIC_SCHEMA = {
    "name": "phone_create_infographic",
    "description": "Generate a single-page infographic PDF with big numbers and labels. Great for summaries, dashboards, key stats.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "subtitle": {"type": "string"},
            "theme": {"type": "string"},
            "stats": {
                "type": "array",
                "description": "List of {value, label, hint?}. 3-6 items recommended.",
                "items": {"type": "object"},
            },
            "footer": {"type": "string"},
            "filename": {"type": "string"},
            "directory": {"type": "string"},
        },
        "required": ["title", "stats"],
    },
}


# ============================================================================
# Registration
# ============================================================================

from tools.registry import registry  # noqa: E402

registry.register(name="phone_create_beautiful_pptx", toolset="beautiful_docs",
                  schema=BEAUTIFUL_PPTX_SCHEMA, handler=_handle_beautiful_pptx,
                  check_fn=_check_phone_connected, is_async=True, emoji="🎨")
registry.register(name="phone_create_beautiful_pdf", toolset="beautiful_docs",
                  schema=BEAUTIFUL_PDF_SCHEMA, handler=_handle_beautiful_pdf,
                  check_fn=_check_phone_connected, is_async=True, emoji="🎨")
registry.register(name="phone_create_infographic", toolset="beautiful_docs",
                  schema=INFOGRAPHIC_SCHEMA, handler=_handle_infographic,
                  check_fn=_check_phone_connected, is_async=True, emoji="📊")
