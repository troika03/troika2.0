"""
Location tool — режим «где я» для Тройки.

Не GPS. Маппинг по fingerprint'у того что телефон видит вокруг:
- network type (wifi/cell/ethernet) + BSSID если телефон смог его узнать
- список Bluetooth-устройств (paired + connected)
- имя устройства (Build.MODEL)

Миша один раз говорит "запомни это место как дом" → fingerprint сохраняется
в state.db. Дальше при каждом запросе сервер сравнивает приходящий контекст
с сохранёнными местами и подмешивает результат в system prompt.

Tool: location
operations:
  - set    — запомнить текущий fingerprint как место с именем
  - get    — где я сейчас (на основе последнего полученного контекста)
  - list   — все сохранённые места
  - forget — удалить место по имени

Контекст приходит через X-Hermes-Device-Context header, парсится в
api_server и кладётся в локальный кэш _DEVICE_CONTEXT_CACHE по session_key.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hermes_constants import get_hermes_home
from tools.registry import registry

logger = logging.getLogger(__name__)


# Кэш последнего пришедшего device_context, key=session_key.
# api_server.py пишет сюда при обработке /v1/chat/completions.
# Tool читает (а ещё этим кэшем пользуется _system_prompt_amendment).
_DEVICE_CONTEXT_CACHE: Dict[str, Dict[str, Any]] = {}


def _db_path() -> Path:
    return get_hermes_home() / "locations.db"


def _conn() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE IF NOT EXISTS locations ("
        " name TEXT PRIMARY KEY,"
        " session_key TEXT,"
        " bssid TEXT,"
        " ssid TEXT,"
        " network_type TEXT,"
        " bluetooth TEXT,"
        " device_name TEXT,"
        " updated_at REAL"
        ")"
    )
    return c


def remember_device_context(session_key: str, ctx: Dict[str, Any]) -> None:
    """Вызывается api_server при получении X-Hermes-Device-Context."""
    if not session_key:
        session_key = "default"
    _DEVICE_CONTEXT_CACHE[session_key] = dict(ctx) if ctx else {}


def get_device_context(session_key: Optional[str] = None) -> Dict[str, Any]:
    if session_key and session_key in _DEVICE_CONTEXT_CACHE:
        return dict(_DEVICE_CONTEXT_CACHE[session_key])
    if _DEVICE_CONTEXT_CACHE:
        # Fallback на последний известный — для tool-вызовов когда session_key
        # не передан явно.
        last = sorted(_DEVICE_CONTEXT_CACHE.items())[-1]
        return dict(last[1])
    return {}


def _bt_set(ctx: Dict[str, Any]) -> set[str]:
    bt = ctx.get("bluetooth")
    if isinstance(bt, list):
        return {str(x).lower() for x in bt if x}
    if isinstance(bt, str):
        return {p.strip().lower() for p in bt.split(",") if p.strip()}
    return set()


def _match_score(ctx: Dict[str, Any], row: sqlite3.Row) -> float:
    """0..1. Сравнение fingerprint входящего контекста с сохранённым местом."""
    score = 0.0
    weight = 0.0

    bssid = (ctx.get("bssid") or "").lower()
    if bssid and row["bssid"]:
        weight += 0.6
        if bssid == row["bssid"].lower():
            score += 0.6

    ssid = (ctx.get("ssid") or "").lower()
    if ssid and row["ssid"]:
        weight += 0.2
        if ssid == row["ssid"].lower():
            score += 0.2

    cur_bt = _bt_set(ctx)
    saved_bt = {p.strip().lower() for p in (row["bluetooth"] or "").split(",") if p.strip()}
    if saved_bt:
        weight += 0.3
        if cur_bt:
            overlap = len(cur_bt & saved_bt) / max(len(saved_bt), 1)
            score += 0.3 * overlap

    net = (ctx.get("network_type") or "").lower()
    if net and row["network_type"]:
        weight += 0.05
        if net == row["network_type"].lower():
            score += 0.05

    if weight == 0:
        return 0.0
    return score / weight


def _identify_location(ctx: Dict[str, Any]) -> Optional[Tuple[str, float]]:
    """Возвращает (name, score) лучшего совпадения или None."""
    if not ctx:
        return None
    try:
        c = _conn()
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM locations").fetchall()
        c.close()
    except sqlite3.Error as e:
        logger.warning("locations.db read failed: %s", e)
        return None
    if not rows:
        return None

    best_name: Optional[str] = None
    best_score = 0.0
    for r in rows:
        s = _match_score(ctx, r)
        if s > best_score:
            best_score = s
            best_name = r["name"]
    if best_name and best_score >= 0.55:
        return best_name, best_score
    return None


def system_prompt_amendment(session_key: Optional[str]) -> str:
    """Кусок текста для добавления в system prompt. Пусто если ничего не понятно."""
    ctx = get_device_context(session_key)
    if not ctx:
        return ""
    match = _identify_location(ctx)
    if match is None:
        # Известен только тип сети — это тоже полезный сигнал
        net = (ctx.get("network_type") or "").lower()
        if net == "cellular":
            return (
                "\n\nКОНТЕКСТ МЕСТА: телефон Миши на мобильной сети (не дома и не на "
                "работе — возможно в дороге). Отвечай короче и без markdown."
            )
        return ""

    name, score = match
    name_l = name.strip().lower()
    hints = {
        "дом": "Миша дома. Можешь говорить нормальной длины ответы, спокойно.",
        "home": "Misha is at home. Normal-length answers, calm tone.",
        "работа": (
            "Миша на работе. Отвечай очень кратко (1-2 предложения), без юмора. "
            "Не предлагай отвлечься на личные дела."
        ),
        "office": "Misha is at the office. Be terse, no humor, focus on the task.",
        "машина": (
            "Миша в машине — за рулём или пассажиром. Отвечай предельно кратко "
            "(одна фраза), не предлагай открывать приложения, не давай ссылки. "
            "Если задача требует визуального — скажи 'покажу когда остановишься'."
        ),
        "car": "Misha is driving. One-sentence answers. No links, no app launches.",
    }
    rule = hints.get(name_l, f"Миша сейчас в месте «{name}» (по сохранённому fingerprint).")
    return f"\n\nКОНТЕКСТ МЕСТА: {rule}"


# ── Tool operations ─────────────────────────────────────────────────────────


def _set(args: Dict[str, Any]) -> Dict[str, Any]:
    name = (args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "missing 'name'"}
    if len(name) > 40:
        name = name[:40]

    session_key = args.get("session_key") or "phone-misha"
    ctx = get_device_context(session_key)
    if not ctx:
        return {
            "ok": False,
            "error": "no_device_context",
            "hint": (
                "С телефона ещё не пришёл device_context — нечего запоминать. "
                "Попроси Мишу сказать что-нибудь голосом, потом снова."
            ),
        }

    bssid = (ctx.get("bssid") or "").strip()
    ssid = (ctx.get("ssid") or "").strip()
    net = (ctx.get("network_type") or "").strip().lower()
    device_name = (ctx.get("device_name") or "").strip()
    bt = ctx.get("bluetooth")
    bt_str = ",".join(str(x) for x in bt) if isinstance(bt, list) else (str(bt) if bt else "")

    try:
        c = _conn()
        c.execute(
            "INSERT OR REPLACE INTO locations "
            "(name, session_key, bssid, ssid, network_type, bluetooth, device_name, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, session_key, bssid, ssid, net, bt_str, device_name, time.time()),
        )
        c.commit()
        c.close()
    except sqlite3.Error as e:
        return {"ok": False, "error": f"sqlite: {e}"}

    fingerprint_parts: List[str] = []
    if bssid:
        fingerprint_parts.append(f"wifi-bssid={bssid[:8]}…")
    elif ssid:
        fingerprint_parts.append(f"wifi={ssid}")
    if bt_str:
        fingerprint_parts.append(f"bt={len(bt_str.split(','))} устр.")
    if net and not fingerprint_parts:
        fingerprint_parts.append(f"net={net}")

    return {
        "ok": True,
        "saved_as": name,
        "fingerprint": "; ".join(fingerprint_parts) or "(пусто)",
    }


def _get(args: Dict[str, Any]) -> Dict[str, Any]:
    session_key = args.get("session_key") or "phone-misha"
    ctx = get_device_context(session_key)
    if not ctx:
        return {"ok": True, "location": None, "reason": "no_device_context_yet"}
    match = _identify_location(ctx)
    if match is None:
        net = ctx.get("network_type") or "?"
        return {
            "ok": True,
            "location": None,
            "network_type": net,
            "bluetooth_count": len(_bt_set(ctx)),
            "reason": "no_match",
        }
    name, score = match
    return {
        "ok": True,
        "location": name,
        "confidence": round(score, 2),
        "context_snapshot": {
            "network_type": ctx.get("network_type"),
            "bluetooth_count": len(_bt_set(ctx)),
            "has_bssid": bool(ctx.get("bssid")),
        },
    }


def _list() -> Dict[str, Any]:
    try:
        c = _conn()
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT name, network_type, ssid, bluetooth, updated_at FROM locations ORDER BY name"
        ).fetchall()
        c.close()
    except sqlite3.Error as e:
        return {"ok": False, "error": f"sqlite: {e}"}
    items: List[Dict[str, Any]] = []
    for r in rows:
        items.append({
            "name": r["name"],
            "network_type": r["network_type"],
            "ssid": r["ssid"] or None,
            "bluetooth_devices": len([p for p in (r["bluetooth"] or "").split(",") if p.strip()]),
            "updated_at": r["updated_at"],
        })
    return {"ok": True, "count": len(items), "locations": items}


def _forget(args: Dict[str, Any]) -> Dict[str, Any]:
    name = (args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "missing 'name'"}
    try:
        c = _conn()
        cur = c.execute("DELETE FROM locations WHERE name = ?", (name,))
        c.commit()
        deleted = cur.rowcount
        c.close()
    except sqlite3.Error as e:
        return {"ok": False, "error": f"sqlite: {e}"}
    return {"ok": True, "deleted": deleted, "name": name}


async def _handle(args: Dict[str, Any], **_kw) -> str:
    op = (args.get("operation") or "get").strip().lower()
    if op == "set":
        res = _set(args)
    elif op == "get":
        res = _get(args)
    elif op == "list":
        res = _list()
    elif op == "forget":
        res = _forget(args)
    else:
        res = {"ok": False, "error": f"unknown operation '{op}'", "allowed": ["set", "get", "list", "forget"]}
    return json.dumps(res, ensure_ascii=False)


LOCATION_SCHEMA = {
    "name": "location",
    "description": (
        "Где сейчас Миша по fingerprint'у телефона (Wi-Fi BSSID, Bluetooth-устройства, "
        "тип сети). Используется когда Миша говорит 'запомни это место как дом', "
        "'я дома?', 'покажи мои места'. "
        "operations: set (сохранить текущий fingerprint под именем), get (где я "
        "сейчас), list (все места), forget (удалить место)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["set", "get", "list", "forget"],
                "description": "Что сделать. По умолчанию get.",
            },
            "name": {
                "type": "string",
                "description": "Имя места для set/forget (например 'дом', 'работа', 'машина').",
            },
            "session_key": {
                "type": "string",
                "description": "Привязка к каналу (default phone-misha).",
            },
        },
        "required": [],
    },
}


registry.register(
    name="location",
    toolset="location",
    schema=LOCATION_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="📍",
)
