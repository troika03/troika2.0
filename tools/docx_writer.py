"""
docx_writer — общий генератор Word-документов (.docx) для Тройки.

Все человекочитаемые отчёты (бизнес-разборы, research, документация) Тройка
пишет через этот хелпер — чтобы Миша мог открыть их как обычный Word-файл,
переслать, распечатать.

Принимает текст с лёгкой markdown-разметкой (## заголовки, **жирный**,
- списки, | таблицы |) и превращает в аккуратный .docx с нормальной
типографикой. НЕ требует pandoc — чистый python-docx.

API:
    from tools.docx_writer import write_docx
    path = write_docx(title="Анализ конкурентов", body=report_text,
                      out_dir="/opt/data/vault/business", filename="...")
"""
from __future__ import annotations
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (s or "document").lower()).strip()
    return (re.sub(r"[\s_-]+", "-", s) or "document")[:60]


def _apply_inline(paragraph, text: str) -> None:
    """Разложить **жирный** на runs внутри абзаца."""
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        else:
            paragraph.add_run(part)


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.count("|") >= 2


def _is_separator_row(line: str) -> bool:
    s = line.strip().strip("|")
    return bool(s) and all(set(c.strip()) <= set("-: ") for c in s.split("|"))


def write_docx(
    title: str,
    body: str,
    out_dir: str,
    filename: Optional[str] = None,
    subtitle: Optional[str] = None,
) -> Optional[str]:
    """Сгенерировать .docx из markdown-подобного текста. Вернёт путь к файлу."""
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except Exception as e:
        logger.warning("python-docx недоступен: %s", e)
        return None

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if not filename:
        date = datetime.now().strftime("%Y-%m-%d")
        filename = f"{date}-{_slug(title)}.docx"
    if not filename.endswith(".docx"):
        filename += ".docx"
    fpath = out / filename

    doc = Document()

    # Базовый шрифт — нейтральный, как в обычном документе
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    # Заголовок
    h = doc.add_heading(title, level=0)
    if subtitle:
        sub = doc.add_paragraph(subtitle)
        sub.alignment = WD_ALIGN_PARAGRAPH.LEFT
        for r in sub.runs:
            r.italic = True
            r.font.size = Pt(10)
            r.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    lines = (body or "").replace("\r\n", "\n").split("\n")
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Таблица: собрать блок подряд идущих |...| строк
        if _is_table_row(line):
            rows = []
            while i < n and _is_table_row(lines[i]):
                if not _is_separator_row(lines[i]):
                    cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                    rows.append(cells)
                i += 1
            if rows:
                cols = max(len(r) for r in rows)
                table = doc.add_table(rows=0, cols=cols)
                table.style = "Light Grid Accent 1"
                for ridx, r in enumerate(rows):
                    tr = table.add_row().cells
                    for cidx in range(cols):
                        val = r[cidx] if cidx < len(r) else ""
                        cell_p = tr[cidx].paragraphs[0]
                        _apply_inline(cell_p, val)
                        if ridx == 0:
                            for run in cell_p.runs:
                                run.bold = True
                doc.add_paragraph()
            continue

        # Заголовки markdown
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            level = min(len(m.group(1)), 4)
            doc.add_heading(m.group(2).strip(), level=level)
            i += 1
            continue

        # Списки
        m = re.match(r"^[-*•]\s+(.*)$", stripped)
        if m:
            p = doc.add_paragraph(style="List Bullet")
            _apply_inline(p, m.group(1))
            i += 1
            continue
        m = re.match(r"^\d+[.)]\s+(.*)$", stripped)
        if m:
            p = doc.add_paragraph(style="List Number")
            _apply_inline(p, m.group(1))
            i += 1
            continue

        # Цитата
        if stripped.startswith(">"):
            p = doc.add_paragraph()
            _apply_inline(p, stripped.lstrip("> ").strip())
            for r in p.runs:
                r.italic = True
            i += 1
            continue

        # Обычный абзац
        p = doc.add_paragraph()
        _apply_inline(p, stripped)
        i += 1

    try:
        doc.save(str(fpath))
        return str(fpath)
    except Exception as e:
        logger.warning("save docx failed: %s", e)
        return None
