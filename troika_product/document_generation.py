"""In-memory document generators used by the hosted Troika tools."""

from __future__ import annotations

from html import escape
import io
import os
from pathlib import Path
from typing import Any


def _clean_text(value: Any, *, fallback: str = "", max_chars: int = 500_000) -> str:
    text = str(value if value is not None else fallback).replace("\x00", "").strip()
    if len(text) > max_chars:
        raise ValueError("document text exceeds the technical safety size")
    return text


def _normalized_sections(args: dict[str, Any]) -> tuple[str, list[tuple[str, str]]]:
    title = _clean_text(args.get("title"), fallback="Документ", max_chars=500)
    raw_sections = args.get("sections") or []
    sections: list[tuple[str, str]] = []
    if raw_sections:
        if not isinstance(raw_sections, list) or len(raw_sections) > 200:
            raise ValueError("sections must be a reasonably sized list")
        for raw in raw_sections:
            if not isinstance(raw, dict):
                raise ValueError("each section must be an object")
            heading = _clean_text(raw.get("heading") or raw.get("title"), max_chars=500)
            body = _clean_text(raw.get("body") or raw.get("content"), max_chars=500_000)
            if heading or body:
                sections.append((heading, body))
    else:
        body = _clean_text(args.get("content"), max_chars=1_000_000)
        if body:
            sections.append(("", body))
    return title or "Документ", sections


def generate_docx(args: dict[str, Any]) -> bytes:
    """Create a clean Word document entirely in memory."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    title, sections = _normalized_sections(args)
    document = Document()
    section = document.sections[0]
    section.top_margin = Cm(2)
    section.bottom_margin = Cm(2)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

    styles = document.styles
    styles["Normal"].font.name = "Arial"
    styles["Normal"].font.size = Pt(11)
    styles["Title"].font.name = "Arial"
    styles["Title"].font.color.rgb = RGBColor(38, 38, 38)
    styles["Title"].font.size = Pt(22)
    styles["Heading 1"].font.name = "Arial"
    styles["Heading 1"].font.color.rgb = RGBColor(38, 38, 38)
    styles["Heading 1"].font.size = Pt(14)
    styles["Heading 1"].paragraph_format.keep_with_next = True

    heading = document.add_heading(title, level=0)
    heading.alignment = WD_ALIGN_PARAGRAPH.LEFT
    for section_title, body in sections:
        if section_title:
            document.add_heading(section_title, level=1)
        for paragraph_text in body.split("\n\n"):
            paragraph_text = paragraph_text.strip()
            if not paragraph_text:
                continue
            paragraph = document.add_paragraph(paragraph_text)
            paragraph.paragraph_format.space_after = Pt(7)
            paragraph.paragraph_format.line_spacing = 1.15

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _register_pdf_font() -> str:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf",
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont("TroikaDocumentFont", str(candidate)))
            return "TroikaDocumentFont"
        except Exception:
            continue
    # Built-in Helvetica is safe for Latin text.  If no Unicode font exists,
    # reportlab will still produce a valid file instead of reaching outside.
    return "Helvetica"


def generate_pdf(args: dict[str, Any]) -> bytes:
    """Create a paginated PDF entirely in memory and without remote assets."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    title, sections = _normalized_sections(args)
    font_name = _register_pdf_font()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=title,
        author="Тройка",
    )
    base = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TroikaTitle",
        parent=base["Title"],
        fontName=font_name,
        fontSize=22,
        leading=27,
        textColor=colors.HexColor("#262626"),
        alignment=0,
        spaceAfter=18,
    )
    section_style = ParagraphStyle(
        "TroikaHeading",
        parent=base["Heading1"],
        fontName=font_name,
        fontSize=15,
        leading=19,
        textColor=colors.HexColor("#262626"),
        keepWithNext=True,
        spaceBefore=10,
        spaceAfter=7,
    )
    body_style = ParagraphStyle(
        "TroikaBody",
        parent=base["BodyText"],
        fontName=font_name,
        fontSize=11,
        leading=16,
        textColor=colors.HexColor("#26231F"),
        spaceAfter=7,
    )
    story = [Paragraph(escape(title), title_style)]
    for section_title, body in sections:
        if section_title:
            story.append(Paragraph(escape(section_title), section_style))
        for paragraph_text in body.split("\n\n"):
            paragraph_text = paragraph_text.strip()
            if paragraph_text:
                safe_paragraph = "<br/>".join(
                    escape(line) for line in paragraph_text.splitlines()
                )
                story.extend((Paragraph(safe_paragraph, body_style), Spacer(1, 2)))
    document.build(story)
    return buffer.getvalue()


def generate_pptx(args: dict[str, Any]) -> bytes:
    """Create a restrained 16:9 presentation entirely in memory."""
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    title = _clean_text(args.get("title"), fallback="Презентация", max_chars=500)
    raw_slides = args.get("slides") or []
    if not isinstance(raw_slides, list) or not raw_slides:
        raise ValueError("slides must be a non-empty list")
    if len(raw_slides) > 100:
        raise ValueError("presentation exceeds the technical safety size")

    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    background_color = RGBColor(255, 255, 255)
    text_color = RGBColor(38, 38, 38)
    muted = RGBColor(64, 64, 64)
    if len(title) > 160:
        raise ValueError("presentation title is too long; use a concise title")

    if args.get("include_cover", True):
        cover = presentation.slides.add_slide(presentation.slide_layouts[6])
        cover.background.fill.solid()
        cover.background.fill.fore_color.rgb = background_color
        cover_title = cover.shapes.add_textbox(
            Inches(1), Inches(2.3), Inches(11.3), Inches(1.5)
        )
        cover_paragraph = cover_title.text_frame.paragraphs[0]
        cover_paragraph.text = title or "Презентация"
        cover_paragraph.alignment = PP_ALIGN.CENTER
        cover_paragraph.font.name = "Arial"
        cover_paragraph.font.size = Pt(34)
        cover_paragraph.font.bold = True
        cover_paragraph.font.color.rgb = text_color

    for index, raw in enumerate(raw_slides, start=1):
        if not isinstance(raw, dict):
            raise ValueError("each slide must be an object")
        slide_title = _clean_text(raw.get("title"), max_chars=500)
        bullets_value = raw.get("bullets") or []
        if bullets_value and not isinstance(bullets_value, list):
            raise ValueError("slide bullets must be a list")
        if bullets_value:
            body_lines = [_clean_text(item, max_chars=5_000) for item in bullets_value]
        else:
            content = _clean_text(raw.get("content", raw.get("body")), max_chars=30_000)
            body_lines = [line.strip() for line in content.splitlines() if line.strip()]

        estimated_lines = sum(
            max(1, (len(part) + 64) // 65)
            for line in body_lines
            for part in line.splitlines()
        )
        if len(slide_title) > 120 or len(body_lines) > 6 or estimated_lines > 8:
            raise ValueError("slide has too much text; split it into multiple slides")
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = background_color

        title_box = slide.shapes.add_textbox(
            Inches(1), Inches(0.62), Inches(11.4), Inches(1.2)
        )
        title_paragraph = title_box.text_frame.paragraphs[0]
        title_paragraph.text = slide_title or f"Слайд {index}"
        title_paragraph.font.name = "Arial"
        title_paragraph.font.size = Pt(28)
        title_paragraph.font.bold = True
        title_paragraph.font.color.rgb = text_color

        layout = raw.get("layout", "content")
        if layout not in {"cover", "content", "split", "statement"}:
            raise ValueError("unsupported slide layout")
        if layout == "cover":
            title_box.top = Inches(2.0)
            title_box.height = Inches(1.6)
            title_paragraph.font.size = Pt(38 if len(slide_title) < 70 else 32)

        body_box = slide.shapes.add_textbox(
            Inches(1),
            Inches(4.2 if layout == "cover" else 2),
            Inches(11.2),
            Inches(2.0 if layout == "cover" else 4.4),
        )
        frame = body_box.text_frame
        frame.word_wrap = True
        frame.clear()
        if layout == "split" and len(body_lines) > 1:
            split = (len(body_lines) + 1) // 2
            columns = [body_lines[:split], body_lines[split:]]
            body_box.width = Inches(5.2)
        else:
            columns = [body_lines or [""]]
        for column_index, lines in enumerate(columns):
            if column_index:
                frame = slide.shapes.add_textbox(
                    Inches(7.0), Inches(2), Inches(5.2), Inches(4.4)
                ).text_frame
                frame.word_wrap = True
                frame.clear()
            for line_index, line in enumerate(lines):
                paragraph = (
                    frame.paragraphs[0] if line_index == 0 else frame.add_paragraph()
                )
                paragraph.text = line
                paragraph.font.name = "Arial"
                paragraph.font.size = Pt(
                    30
                    if layout == "statement" and len(line) < 90 and line_index == 0
                    else 21
                )
                paragraph.font.color.rgb = text_color if line_index == 0 else muted
                paragraph.space_after = Pt(18 if layout == "statement" else 13)
                paragraph.level = 0

        number = slide.shapes.add_textbox(
            Inches(11.9), Inches(6.75), Inches(0.7), Inches(0.35)
        )
        number_p = number.text_frame.paragraphs[0]
        number_p.text = str(index)
        number_p.alignment = PP_ALIGN.RIGHT
        number_p.font.size = Pt(11)
        number_p.font.color.rgb = muted

    buffer = io.BytesIO()
    presentation.save(buffer)
    return buffer.getvalue()
