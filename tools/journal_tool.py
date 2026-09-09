"""
Journal tool — что было сегодня/вчера/на неделе.

Читает state.db напрямую и собирает user-сообщения Тройки за период.
Используется когда Миша спрашивает "что я говорил вчера", "о чём мы
вчера болтали", "что сегодня обсуждали", "напомни про неделю".

Не пытается пересказать ответы LLM — только user-реплики (это сам Миша
говорил, тут самая ценная информация о том что он делал/думал).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

from hermes_constants import get_hermes_home
from tools.registry import registry

logger = logging.getLogger(__name__)


def _state_db_path() -> Path:
    return get_hermes_home() / "state.db"


def _period_to_range(period: str) -> tuple[float, float, str]:
    """Возвращает (start_ts, end_ts, label) для UNIX-таймстампов."""
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    p = (period or "today").strip().lower()
    if p in ("today", "сегодня"):
        return today_start.timestamp(), now.timestamp(), "сегодня"
    if p in ("yesterday", "вчера"):
        ystart = today_start - timedelta(days=1)
        return ystart.timestamp(), today_start.timestamp(), "вчера"
    if p in ("week", "неделя", "7d"):
        wstart = today_start - timedelta(days=7)
        return wstart.timestamp(), now.timestamp(), "за неделю"
    if p in ("month", "месяц", "30d"):
        mstart = today_start - timedelta(days=30)
        return mstart.timestamp(), now.timestamp(), "за месяц"
    return today_start.timestamp(), now.timestamp(), "сегодня"


async def _handle(args: Dict[str, Any], **_kw) -> str:
    db_path = _state_db_path()
    if not db_path.exists():
        return json.dumps(
            {"ok": False, "error": "state_db_not_found", "path": str(db_path)},
            ensure_ascii=False,
        )

    period = args.get("period", "today")
    session_id = (args.get("_session_id") or "").strip()
    if not session_id:
        return json.dumps(
            {"ok": False, "error": "session_scope_unavailable"},
            ensure_ascii=False,
        )
    max_items = int(args.get("max_items") or 50)
    start_ts, end_ts, label = _period_to_range(period)

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT role, content, timestamp "
            "FROM messages "
            "WHERE session_id = ? AND timestamp >= ? AND timestamp < ? "
            "AND role IN ('user', 'assistant') "
            "ORDER BY timestamp ASC",
            (session_id, start_ts, end_ts),
        ).fetchall()
        conn.close()
    except sqlite3.Error as e:
        return json.dumps({"ok": False, "error": f"sqlite: {e}"}, ensure_ascii=False)

    user_lines: List[Dict[str, Any]] = []
    assistant_count = 0
    for row in rows:
        role = row["role"]
        content = row["content"] or ""
        if not content.strip():
            continue
        if role == "assistant":
            assistant_count += 1
            continue
        ts = datetime.fromtimestamp(row["timestamp"]).strftime("%H:%M")
        text = content.strip()
        if len(text) > 280:
            text = text[:280].rstrip() + "…"
        user_lines.append({"time": ts, "text": text})

    if len(user_lines) > max_items:
        user_lines = user_lines[-max_items:]

    return json.dumps(
        {
            "ok": True,
            "period": label,
            "session_id": session_id,
            "user_message_count": len(user_lines),
            "assistant_reply_count": assistant_count,
            "messages": user_lines,
        },
        ensure_ascii=False,
    )


JOURNAL_SCHEMA = {
    "name": "journal_today",
    "description": (
        "Что Миша говорил Тройке сегодня/вчера/на неделе. "
        "Возвращает список его реплик (без ответов Тройки) с временем. "
        "Использовать когда Миша спрашивает 'что я вчера говорил', "
        "'о чём мы болтали', 'напомни что я хотел', 'что я просил'. "
        "По умолчанию — сегодня. Период: today/yesterday/week/month."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "period": {
                "type": "string",
                "enum": ["today", "yesterday", "week", "month"],
                "description": "Какой период взять. По умолчанию today.",
            },
            "max_items": {
                "type": "integer",
                "description": "Максимум реплик (по умолчанию 50, последние).",
            },
        },
        "required": [],
    },
}


registry.register(
    name="journal_today",
    toolset="journal",
    schema=JOURNAL_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="📓",
)
