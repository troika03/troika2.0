"""
Документы для голосового ассистента: создаёт PDF/PPTX/DOCX/XLSX/CSV/JSON
и кладёт их на подключённый Android-телефон через PhoneBridge.

Использует встроенные библиотеки:
- reportlab — PDF
- python-pptx — PowerPoint
- python-docx — Word
- openpyxl — Excel
- markdown — Markdown→HTML, далее в PDF через reportlab

Все documents tools работают через одну общую схему:
1. Генерируем файл во временном буфере (io.BytesIO).
2. base64-кодируем.
3. Отправляем команду ``file_write`` с encoding=base64 в PhoneBridge.
4. Возвращаем путь файла на телефоне для LLM.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import re
import zipfile
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _bridge():
    from gateway.platforms.phone_bridge import bridge
    return bridge


def _check_phone_connected():
    try:
        return _bridge().is_connected()
    except Exception:
        return False


async def _send_to_phone(filename: str, data: bytes, directory: str = "Download") -> Dict[str, Any]:
    """Отправить бинарные данные на телефон через bridge.

    Если directory='Download' — отправляем просто имя файла, потому что resolveSafe()
    в Kotlin сам кладёт неабсолютные пути в Downloads. Иначе передаём с префиксом.
    """
    encoded = base64.b64encode(data).decode("ascii")
    if directory.lower() in ("download", "downloads", ""):
        path = filename
    else:
        path = f"{directory}/{filename}"
    timeout = max(60.0, len(encoded) / 30_000)
    result = await _bridge().send_command(
        "file_write",
        {"path": path, "content": encoded, "encoding": "base64", "append": False},
        timeout=timeout,
    )
    return result


def _safe_filename(name: str, ext: str) -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip("._ ")
    if not base:
        base = "document"
    if not base.lower().endswith("." + ext):
        base = f"{base}.{ext}"
    return base


# ============================================================================
# PDF
# ============================================================================

async def _handle_create_pdf(args: Dict[str, Any], **kw) -> str:
    """Сгенерировать PDF из заголовка и параграфов и положить на телефон."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem,
            PageBreak,
        )
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os
    except Exception as e:
        return json.dumps({"ok": False, "error": f"reportlab missing: {e}"}, ensure_ascii=False)

    title = (args.get("title") or "Документ").strip()
    content = args.get("content", "")
    sections = args.get("sections", [])  # альтернатива content: [{heading, body}]
    filename = _safe_filename(args.get("filename") or title, "pdf")
    directory = args.get("directory") or "Download"

    # Регистрируем шрифт с поддержкой кириллицы
    font_name = "Helvetica"
    for font_path in [
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont("AppFont", font_path))
                font_name = "AppFont"
                break
            except Exception:
                continue

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName=font_name, fontSize=20)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=font_name, fontSize=14)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName=font_name, fontSize=11, leading=15)

    story: List = [Paragraph(title, h1), Spacer(1, 0.5*cm)]

    if sections:
        for sec in sections:
            heading = sec.get("heading") or sec.get("title")
            if heading:
                story.append(Paragraph(heading, h2))
                story.append(Spacer(1, 0.2*cm))
            text = sec.get("body") or sec.get("content") or ""
            for para in text.split("\n\n"):
                if para.strip():
                    story.append(Paragraph(para.replace("\n", "<br/>"), body))
                    story.append(Spacer(1, 0.2*cm))
    elif content:
        for para in content.split("\n\n"):
            if para.strip():
                story.append(Paragraph(para.replace("\n", "<br/>"), body))
                story.append(Spacer(1, 0.2*cm))

    doc.build(story)
    data = buf.getvalue()

    result = await _send_to_phone(filename, data, directory)
    return json.dumps({"ok": result.get("ok", False), "tool": "create_pdf",
                       "filename": filename, "size": len(data),
                       "phone_result": result}, ensure_ascii=False)


# ============================================================================
# PowerPoint
# ============================================================================

async def _handle_create_pptx(args: Dict[str, Any], **kw) -> str:
    """Создать .pptx презентацию.

    Принимает массив slides: [{title, content, bullets?, notes?}].
    """
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
    except Exception as e:
        return json.dumps({"ok": False, "error": f"python-pptx missing: {e}"}, ensure_ascii=False)

    title = (args.get("title") or "Презентация").strip()
    slides = args.get("slides") or []
    filename = _safe_filename(args.get("filename") or title, "pptx")
    directory = args.get("directory") or "Download"

    if not slides:
        return json.dumps({"ok": False, "error": "missing 'slides' (list of {title,content,bullets?,notes?})"}, ensure_ascii=False)

    prs = Presentation()
    # Title slide
    title_layout = prs.slide_layouts[0]
    title_slide = prs.slides.add_slide(title_layout)
    title_slide.shapes.title.text = title
    if slides and slides[0].get("subtitle"):
        title_slide.placeholders[1].text = slides[0]["subtitle"]

    # Content slides
    content_layout = prs.slide_layouts[1]  # Title + Content
    for s in slides:
        slide = prs.slides.add_slide(content_layout)
        slide.shapes.title.text = s.get("title", "")
        body_ph = None
        for shape in slide.placeholders:
            if shape.placeholder_format.idx == 1:
                body_ph = shape
                break
        if body_ph is None:
            continue
        tf = body_ph.text_frame
        tf.clear()

        bullets = s.get("bullets") or []
        if bullets:
            for i, b in enumerate(bullets):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = str(b)
                p.font.size = Pt(18)
        else:
            content_text = s.get("content") or ""
            for i, line in enumerate(content_text.split("\n")):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = line
                p.font.size = Pt(18)

        if s.get("notes"):
            slide.notes_slide.notes_text_frame.text = s["notes"]

    buf = io.BytesIO()
    prs.save(buf)
    data = buf.getvalue()
    result = await _send_to_phone(filename, data, directory)
    return json.dumps({"ok": result.get("ok", False), "tool": "create_pptx",
                       "filename": filename, "slides": len(slides),
                       "size": len(data), "phone_result": result}, ensure_ascii=False)


# ============================================================================
# Word
# ============================================================================

async def _handle_create_docx(args: Dict[str, Any], **kw) -> str:
    try:
        from docx import Document
        from docx.shared import Pt
    except Exception as e:
        return json.dumps({"ok": False, "error": f"python-docx missing: {e}"}, ensure_ascii=False)

    title = (args.get("title") or "Документ").strip()
    content = args.get("content", "")
    sections = args.get("sections") or []
    filename = _safe_filename(args.get("filename") or title, "docx")
    directory = args.get("directory") or "Download"

    doc = Document()
    if title:
        doc.add_heading(title, level=0)

    if sections:
        for sec in sections:
            heading = sec.get("heading") or sec.get("title")
            if heading:
                doc.add_heading(heading, level=1)
            text = sec.get("body") or sec.get("content") or ""
            for para in text.split("\n\n"):
                if para.strip():
                    doc.add_paragraph(para)
    elif content:
        for para in content.split("\n\n"):
            if para.strip():
                doc.add_paragraph(para)

    buf = io.BytesIO()
    doc.save(buf)
    data = buf.getvalue()
    result = await _send_to_phone(filename, data, directory)
    return json.dumps({"ok": result.get("ok", False), "tool": "create_docx",
                       "filename": filename, "size": len(data),
                       "phone_result": result}, ensure_ascii=False)


# ============================================================================
# Excel
# ============================================================================

async def _handle_create_xlsx(args: Dict[str, Any], **kw) -> str:
    try:
        from openpyxl import Workbook
    except Exception as e:
        return json.dumps({"ok": False, "error": f"openpyxl missing: {e}"}, ensure_ascii=False)

    title = (args.get("title") or "Таблица").strip()
    sheets = args.get("sheets") or []  # [{name, headers, rows}]
    rows = args.get("rows")  # альтернатива sheets: одна таблица
    headers = args.get("headers")
    filename = _safe_filename(args.get("filename") or title, "xlsx")
    directory = args.get("directory") or "Download"

    if not sheets and rows is not None:
        sheets = [{"name": "Sheet1", "headers": headers or [], "rows": rows}]

    if not sheets:
        return json.dumps({"ok": False, "error": "missing 'sheets' or 'rows'"}, ensure_ascii=False)

    wb = Workbook()
    # удаляем дефолтный лист если у нас есть свои
    wb.remove(wb.active)
    for sheet_def in sheets:
        name = (sheet_def.get("name") or "Sheet")[:31]
        ws = wb.create_sheet(title=name)
        hdrs = sheet_def.get("headers") or []
        if hdrs:
            ws.append([str(h) for h in hdrs])
            for cell in ws[1]:
                cell.font = cell.font.copy(bold=True)
        for row in sheet_def.get("rows") or []:
            if isinstance(row, dict) and hdrs:
                ws.append([row.get(h, "") for h in hdrs])
            elif isinstance(row, list):
                ws.append(row)
            else:
                ws.append([row])

    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()
    result = await _send_to_phone(filename, data, directory)
    return json.dumps({"ok": result.get("ok", False), "tool": "create_xlsx",
                       "filename": filename, "size": len(data),
                       "phone_result": result}, ensure_ascii=False)


# ============================================================================
# Markdown → PDF
# ============================================================================

async def _handle_markdown_to_pdf(args: Dict[str, Any], **kw) -> str:
    """Конвертирует Markdown в PDF и кладёт на телефон.

    Простая реализация: парсит секции и абзацы. Не поддерживает таблицы/код-блоки
    с syntax-highlighting, но обрабатывает заголовки, списки, жирный/курсив.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem,
        )
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os
    except Exception as e:
        return json.dumps({"ok": False, "error": f"reportlab missing: {e}"}, ensure_ascii=False)

    md_text = args.get("markdown") or args.get("content") or ""
    if not md_text.strip():
        return json.dumps({"ok": False, "error": "missing 'markdown'"}, ensure_ascii=False)
    filename = _safe_filename(args.get("filename") or "document", "pdf")
    directory = args.get("directory") or "Download"

    font_name = "Helvetica"
    for fp in [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf"]:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont("AppFont", fp))
                font_name = "AppFont"
                break
            except Exception:
                continue

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontName=font_name, fontSize=20)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=font_name, fontSize=16)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontName=font_name, fontSize=13)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName=font_name, fontSize=11, leading=15)

    story: List = []
    lines = md_text.split("\n")
    bullets: List[str] = []

    def flush_bullets():
        nonlocal bullets
        if bullets:
            items = [ListItem(Paragraph(_md_inline(b), body)) for b in bullets]
            story.append(ListFlowable(items, bulletType="bullet", start="•"))
            story.append(Spacer(1, 0.3*cm))
            bullets = []

    para_buf: List[str] = []
    def flush_para():
        nonlocal para_buf
        if para_buf:
            story.append(Paragraph(_md_inline(" ".join(para_buf)), body))
            story.append(Spacer(1, 0.2*cm))
            para_buf = []

    for line in lines:
        ln = line.rstrip()
        if ln.startswith("# "):
            flush_bullets(); flush_para()
            story.append(Paragraph(_md_inline(ln[2:]), h1))
            story.append(Spacer(1, 0.3*cm))
        elif ln.startswith("## "):
            flush_bullets(); flush_para()
            story.append(Paragraph(_md_inline(ln[3:]), h2))
            story.append(Spacer(1, 0.3*cm))
        elif ln.startswith("### "):
            flush_bullets(); flush_para()
            story.append(Paragraph(_md_inline(ln[4:]), h3))
            story.append(Spacer(1, 0.2*cm))
        elif ln.lstrip().startswith(("- ", "* ", "• ")):
            flush_para()
            bullets.append(ln.lstrip()[2:])
        elif ln.strip() == "":
            flush_bullets(); flush_para()
        else:
            para_buf.append(ln)
    flush_bullets(); flush_para()

    doc.build(story)
    data = buf.getvalue()
    result = await _send_to_phone(filename, data, directory)
    return json.dumps({"ok": result.get("ok", False), "tool": "markdown_to_pdf",
                       "filename": filename, "size": len(data),
                       "phone_result": result}, ensure_ascii=False)


def _md_inline(s: str) -> str:
    """Простая обработка inline markdown в reportlab paragraph markup."""
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\*(.+?)\*", r"<i>\1</i>", s)
    s = re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", s)
    return s


# ============================================================================
# CSV / JSON
# ============================================================================

async def _handle_create_csv(args: Dict[str, Any], **kw) -> str:
    headers = args.get("headers") or []
    rows = args.get("rows") or []
    filename = _safe_filename(args.get("filename") or "data", "csv")
    directory = args.get("directory") or "Download"

    buf = io.StringIO()
    w = csv.writer(buf)
    if headers:
        w.writerow(headers)
    for row in rows:
        if isinstance(row, dict) and headers:
            w.writerow([row.get(h, "") for h in headers])
        elif isinstance(row, list):
            w.writerow(row)
        else:
            w.writerow([row])
    data = buf.getvalue().encode("utf-8")
    # CSV: добавляем BOM чтобы Excel правильно открыл кириллицу
    data = b"\xef\xbb\xbf" + data
    result = await _send_to_phone(filename, data, directory)
    return json.dumps({"ok": result.get("ok", False), "tool": "create_csv",
                       "filename": filename, "size": len(data),
                       "phone_result": result}, ensure_ascii=False)


async def _handle_create_json(args: Dict[str, Any], **kw) -> str:
    data_obj = args.get("data")
    if data_obj is None:
        return json.dumps({"ok": False, "error": "missing 'data'"}, ensure_ascii=False)
    filename = _safe_filename(args.get("filename") or "data", "json")
    directory = args.get("directory") or "Download"
    indent = int(args.get("indent", 2))
    data = json.dumps(data_obj, ensure_ascii=False, indent=indent).encode("utf-8")
    result = await _send_to_phone(filename, data, directory)
    return json.dumps({"ok": result.get("ok", False), "tool": "create_json",
                       "filename": filename, "size": len(data),
                       "phone_result": result}, ensure_ascii=False)


# ============================================================================
# ZIP
# ============================================================================

async def _handle_create_zip(args: Dict[str, Any], **kw) -> str:
    """Создать ZIP из набора виртуальных файлов.

    files: [{name, content, encoding?}] — content может быть text или base64.
    """
    files = args.get("files") or []
    if not files:
        return json.dumps({"ok": False, "error": "missing 'files' (list of {name,content})"}, ensure_ascii=False)
    filename = _safe_filename(args.get("filename") or "archive", "zip")
    directory = args.get("directory") or "Download"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            name = f.get("name") or "file.txt"
            enc = f.get("encoding", "text")
            content = f.get("content", "")
            if enc == "base64":
                data = base64.b64decode(content)
            else:
                data = content.encode("utf-8")
            zf.writestr(name, data)

    data = buf.getvalue()
    result = await _send_to_phone(filename, data, directory)
    return json.dumps({"ok": result.get("ok", False), "tool": "create_zip",
                       "filename": filename, "size": len(data),
                       "files_count": len(files), "phone_result": result}, ensure_ascii=False)


# ============================================================================
# Schemas
# ============================================================================

CREATE_PDF_SCHEMA = {
    "name": "phone_create_pdf",
    "description": "Generate a PDF document and save it to the user's phone (Downloads folder by default). Supports Russian and Latin text via system fonts.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string", "description": "Plain text body. Use blank lines to separate paragraphs."},
            "sections": {"type": "array", "description": "Alternative to 'content': list of {heading, body} for structured docs.",
                         "items": {"type": "object"}},
            "filename": {"type": "string", "description": "Optional filename (without path). Defaults from title."},
            "directory": {"type": "string", "description": "Folder on phone, default 'Download'."},
        },
        "required": ["title"],
    },
}

CREATE_PPTX_SCHEMA = {
    "name": "phone_create_pptx",
    "description": (
        "[LEGACY/PLAIN] Generate a bare-bones PowerPoint with WHITE BACKGROUND and no styling. "
        "DO NOT USE for normal user requests. For ANY presentation request "
        "(\"сделай презентацию\", \"slides\", \"презинтация\", etc.) use phone_create_beautiful_pptx instead "
        "— it produces designer-quality slides with themes, colors and decoration. "
        "Use this plain tool ONLY when the user explicitly says \"plain\", \"minimal text-only\", "
        "or \"без оформления\"."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "slides": {
                "type": "array",
                "description": "List of slides. Each slide: {title, content?, bullets?, notes?}",
                "items": {"type": "object"},
            },
            "filename": {"type": "string"},
            "directory": {"type": "string"},
        },
        "required": ["title", "slides"],
    },
}

CREATE_DOCX_SCHEMA = {
    "name": "phone_create_docx",
    "description": "Generate a Word document (.docx) and save it to the user's phone.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "sections": {"type": "array", "items": {"type": "object"}},
            "filename": {"type": "string"},
            "directory": {"type": "string"},
        },
        "required": ["title"],
    },
}

CREATE_XLSX_SCHEMA = {
    "name": "phone_create_xlsx",
    "description": "Generate an Excel spreadsheet (.xlsx) and save it to the user's phone. Supports multiple sheets.",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "sheets": {
                "type": "array",
                "description": "List of {name, headers, rows}. Rows can be lists or dicts.",
                "items": {"type": "object"},
            },
            "headers": {"type": "array", "items": {"type": "string"}, "description": "Shortcut for single-sheet."},
            "rows": {"type": "array", "description": "Shortcut for single-sheet."},
            "filename": {"type": "string"},
            "directory": {"type": "string"},
        },
    },
}

MD2PDF_SCHEMA = {
    "name": "phone_markdown_to_pdf",
    "description": "Convert Markdown text to PDF and save to the phone. Supports headings (# ## ###), bullets (- *), bold (**), italic (*), inline code.",
    "parameters": {
        "type": "object",
        "properties": {
            "markdown": {"type": "string"},
            "filename": {"type": "string"},
            "directory": {"type": "string"},
        },
        "required": ["markdown"],
    },
}

CREATE_CSV_SCHEMA = {
    "name": "phone_create_csv",
    "description": "Create a CSV file (with UTF-8 BOM so Excel opens Russian text correctly) and save to phone.",
    "parameters": {
        "type": "object",
        "properties": {
            "headers": {"type": "array", "items": {"type": "string"}},
            "rows": {"type": "array"},
            "filename": {"type": "string"},
            "directory": {"type": "string"},
        },
        "required": ["rows"],
    },
}

CREATE_JSON_SCHEMA = {
    "name": "phone_create_json",
    "description": "Save a JSON file to the phone with pretty-printed UTF-8.",
    "parameters": {
        "type": "object",
        "properties": {
            "data": {"description": "Any JSON-serializable object."},
            "filename": {"type": "string"},
            "directory": {"type": "string"},
            "indent": {"type": "integer"},
        },
        "required": ["data"],
    },
}

CREATE_ZIP_SCHEMA = {
    "name": "phone_create_zip",
    "description": "Bundle multiple in-memory files into a ZIP and save to phone.",
    "parameters": {
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "description": "List of {name, content, encoding?}. encoding: 'text' (default) or 'base64'.",
                "items": {"type": "object"},
            },
            "filename": {"type": "string"},
            "directory": {"type": "string"},
        },
        "required": ["files"],
    },
}


# ============================================================================
# Registration
# ============================================================================

from tools.registry import registry  # noqa: E402

registry.register(name="phone_create_pdf", toolset="phone_documents",
                  schema=CREATE_PDF_SCHEMA, handler=_handle_create_pdf,
                  check_fn=_check_phone_connected, is_async=True, emoji="📄")
registry.register(name="phone_create_pptx", toolset="phone_documents",
                  schema=CREATE_PPTX_SCHEMA, handler=_handle_create_pptx,
                  check_fn=_check_phone_connected, is_async=True, emoji="📊")
registry.register(name="phone_create_docx", toolset="phone_documents",
                  schema=CREATE_DOCX_SCHEMA, handler=_handle_create_docx,
                  check_fn=_check_phone_connected, is_async=True, emoji="📝")
registry.register(name="phone_create_xlsx", toolset="phone_documents",
                  schema=CREATE_XLSX_SCHEMA, handler=_handle_create_xlsx,
                  check_fn=_check_phone_connected, is_async=True, emoji="📈")
registry.register(name="phone_markdown_to_pdf", toolset="phone_documents",
                  schema=MD2PDF_SCHEMA, handler=_handle_markdown_to_pdf,
                  check_fn=_check_phone_connected, is_async=True, emoji="📄")
registry.register(name="phone_create_csv", toolset="phone_documents",
                  schema=CREATE_CSV_SCHEMA, handler=_handle_create_csv,
                  check_fn=_check_phone_connected, is_async=True, emoji="📋")
registry.register(name="phone_create_json", toolset="phone_documents",
                  schema=CREATE_JSON_SCHEMA, handler=_handle_create_json,
                  check_fn=_check_phone_connected, is_async=True, emoji="📋")
registry.register(name="phone_create_zip", toolset="phone_documents",
                  schema=CREATE_ZIP_SCHEMA, handler=_handle_create_zip,
                  check_fn=_check_phone_connected, is_async=True, emoji="🗜")
