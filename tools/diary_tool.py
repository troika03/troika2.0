"""
diary — Тройка ведёт дневник в своём vault'е.

Локация: <vault>/diary/YYYY-MM-DD.md
Один файл на день, дописывается через append. Записи короткие:
  - что было сегодня (события)
  - что Тройка узнала о Мише или о мире
  - открытые вопросы

Tools:
  • diary_add  — добавить запись в дневник сегодняшнего дня
  • diary_read — прочитать конкретный день (или последние N дней)

Используется когда Тройка хочет «запомнить мгновение» — что-то наблюдательное,
эмоциональное, неоднозначное. Не дубликат project memory: project — это факты,
diary — это процесс.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from tools.registry import registry

logger = logging.getLogger(__name__)


_DEFAULT_VAULT = Path("C:/Users/kiqu/.claude/projects/d--troikahermes/memory")
_VAULT = Path(os.environ.get("HERMES_MEMORY_VAULT") or _DEFAULT_VAULT)
_DIARY_DIR = _VAULT / "diary"


def _today_path() -> Path:
    return _DIARY_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.md"


def _ensure_today_file() -> Path:
    _DIARY_DIR.mkdir(parents=True, exist_ok=True)
    path = _today_path()
    if not path.exists():
        today = datetime.now().strftime("%Y-%m-%d (%A)")
        header = (
            f"---\n"
            f"name: diary-{datetime.now().strftime('%Y-%m-%d')}\n"
            f"description: Дневник Тройки за {today}\n"
            f"metadata:\n"
            f"  node_type: memory\n"
            f"  type: diary\n"
            f"---\n\n"
            f"# {today}\n\n"
        )
        path.write_text(header, encoding="utf-8")
    return path


async def _handle_add(arguments: dict, **_kw) -> dict:
    note = (arguments.get("note") or "").strip()
    if not note:
        return {"ok": False, "error": "missing_note"}
    category = (arguments.get("category") or "обычное").strip()
    if len(note) > 500:
        note = note[:500] + "…"

    path = _ensure_today_file()
    now = datetime.now().strftime("%H:%M")
    entry = f"- **{now}** ({category}) — {note}\n"
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)
        return {"ok": True, "file": path.name, "say_to_user": "Записала."}
    except Exception as e:
        return {"ok": False, "error": f"write_failed: {e}"}


async def _handle_read(arguments: dict, **_kw) -> dict:
    days_back = int(arguments.get("days_back", 0))
    days_back = max(0, min(days_back, 30))

    target_date = datetime.now() - timedelta(days=days_back)
    path = _DIARY_DIR / f"{target_date.strftime('%Y-%m-%d')}.md"
    if not path.exists():
        return {"ok": True, "date": target_date.strftime("%Y-%m-%d"),
                "content": "", "say_to_user": "В этот день дневник пустой."}
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        # Срезаем frontmatter для удобства чтения LLM
        if content.startswith("---"):
            end = content.find("\n---", 3)
            if end != -1:
                content = content[end + 4:].lstrip()
        return {"ok": True, "date": target_date.strftime("%Y-%m-%d"),
                "content": content[:3000]}
    except Exception as e:
        return {"ok": False, "error": f"read_failed: {e}"}


ADD_SCHEMA = {
    "name": "diary_add",
    "description": "Добавить короткую запись в дневник сегодняшнего дня. Используй когда хочешь зафиксировать наблюдение, эмоцию, момент — не голый факт (для фактов есть obsidian_note). Например: «Миша устал к вечеру», «впервые запустилось сразу с первой попытки», «Миша смеялся над моей ошибкой».",
    "parameters": {
        "type": "object",
        "properties": {
            "note": {"type": "string", "description": "Что хочешь запомнить. 1-3 предложения."},
            "category": {"type": "string", "description": "Опционально: наблюдение|урок|вопрос|радость|облом. Default 'обычное'."},
        },
        "required": ["note"],
    },
}

READ_SCHEMA = {
    "name": "diary_read",
    "description": "Прочитать дневник. days_back=0 — сегодня, 1 — вчера, и т.д. (max 30). Используй чтобы вспомнить контекст недавних дней.",
    "parameters": {
        "type": "object",
        "properties": {
            "days_back": {"type": "integer", "description": "0=сегодня, 1=вчера, etc. Default 0."},
        },
    },
}


registry.register(name="diary_add", toolset="memory",
                  schema=ADD_SCHEMA, handler=_handle_add,
                  is_async=True, emoji="📔")
registry.register(name="diary_read", toolset="memory",
                  schema=READ_SCHEMA, handler=_handle_read,
                  is_async=True, emoji="📖")
