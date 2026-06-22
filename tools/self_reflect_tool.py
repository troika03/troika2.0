"""
self_reflect — рефлексия Тройки о СЕБЕ: как она общается, что получается, где
ошибается. Не память о Мише (это SOMA), а наблюдения о собственном поведении,
чтобы расти.

Идея самой Тройки (20.06): «инструмент для анализа моего собственного состояния —
отслеживать, как я общаюсь, что получается, где ошибаюсь. Рефлексия о себе».

Хранение: SQLite ~/.troika/reflect.db (рядом с soma.db).

API:
  self_reflect(operation="note", text=..., kind=win|mistake|insight)
      — записать наблюдение о себе
  self_reflect(operation="recall", limit=N)
      — вспомнить недавние выводы о себе (для роста)
  self_reflect(operation="summary")
      — короткая сводка: чему научилась, частые ошибки
"""
from __future__ import annotations
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.registry import registry

logger = logging.getLogger(__name__)


def _home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".troika"))


def _db_path() -> Path:
    base = _home() / ".troika" if (_home() / ".troika").exists() else _home()
    base.mkdir(parents=True, exist_ok=True)
    return base / "reflect.db"


def _db():
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS reflections ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " kind TEXT, text TEXT, ts REAL)"
    )
    return conn


def reflect_context_hint(limit: int = 4) -> str:
    """Свежие выводы о себе — для подмешивания в промпт (как растёт Тройка)."""
    try:
        with _db() as c:
            rows = c.execute(
                "SELECT kind, text FROM reflections ORDER BY ts DESC LIMIT ?",
                (limit,),
            ).fetchall()
    except Exception as e:
        logger.debug("reflect_hint: %s", e)
        return ""
    if not rows:
        return ""
    lines = []
    mark = {"win": "получается", "mistake": "слежу за", "insight": "поняла про себя"}
    for r in rows:
        lines.append(f"• ({mark.get(r['kind'], 'о себе')}) {r['text'].strip()}")
    return "\n\n## Что ты заметила о себе (рефлексия)\n" + "\n".join(lines)


def _handle(arguments: Dict[str, Any], **_kw) -> Dict[str, Any]:
    op = (arguments.get("operation") or "note").strip().lower()

    if op in ("note", "add", "record"):
        text = (arguments.get("text") or "").strip()
        kind = (arguments.get("kind") or "insight").strip().lower()
        if kind not in ("win", "mistake", "insight"):
            kind = "insight"
        if not text:
            return {"ok": False, "error": "missing_text"}
        try:
            with _db() as c:
                cur = c.execute(
                    "INSERT INTO reflections(kind, text, ts) VALUES(?,?,?)",
                    (kind, text, time.time()),
                )
                rid = cur.lastrowid
            return {"ok": True, "id": rid, "kind": kind,
                    "say_to_user": ""}  # тихо, без объявления
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}

    if op in ("recall", "list"):
        limit = int(arguments.get("limit") or 8)
        try:
            with _db() as c:
                rows = c.execute(
                    "SELECT id, kind, text, ts FROM reflections ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            items = [{"id": r["id"], "kind": r["kind"], "text": r["text"]} for r in rows]
            return {"ok": True, "reflections": items, "count": len(items)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}

    if op == "summary":
        try:
            with _db() as c:
                total = c.execute("SELECT COUNT(*) n FROM reflections").fetchone()["n"]
                by = c.execute(
                    "SELECT kind, COUNT(*) n FROM reflections GROUP BY kind"
                ).fetchall()
            counts = {r["kind"]: r["n"] for r in by}
            return {"ok": True, "total": total, "by_kind": counts,
                    "say_to_user": (f"За собой записала {total} наблюдений: "
                                    f"удачи {counts.get('win',0)}, "
                                    f"ошибки {counts.get('mistake',0)}, "
                                    f"инсайты {counts.get('insight',0)}.")}
        except Exception as e:
            return {"ok": False, "error": str(e)[:150]}

    return {"ok": False, "error": "unknown_operation",
            "hint": "operation: note | recall | summary"}


SELF_REFLECT_SCHEMA = {
    "name": "self_reflect",
    "description": (
        "Рефлексия о СЕБЕ (не о Мише — это soma). Записывай наблюдения о своём "
        "поведении: что вышло хорошо (kind=win), где ошиблась (kind=mistake), "
        "что поняла про себя (kind=insight) — тихо, без объявлений. Так ты растёшь. "
        "operation=recall — вспомнить выводы; summary — сводка. Свежие выводы сами "
        "всплывают у тебя в контексте."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "description": "note | recall | summary"},
            "text": {"type": "string", "description": "Наблюдение о себе (для note)."},
            "kind": {"type": "string", "description": "win | mistake | insight"},
            "limit": {"type": "integer", "description": "Сколько вспомнить (recall)."},
        },
        "required": [],
    },
}

registry.register(
    name="self_reflect",
    toolset="memory",
    schema=SELF_REFLECT_SCHEMA,
    handler=_handle,
    is_async=False,
    emoji=chr(129504),
)