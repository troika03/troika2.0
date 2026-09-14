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
import math
import os
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hermes_constants import get_hermes_home
from tools.registry import registry

logger = logging.getLogger(__name__)


# Кэш последнего пришедшего device_context, key=session_key.
# api_server.py пишет сюда при обработке /v1/chat/completions.
# Tool читает (а ещё этим кэшем пользуется _system_prompt_amendment).
#
# 13.08.2026: добавлена персистентность на диск. Раньше кеш жил в процессе
# gateway → после каждого рестарта пустой → Тройка не знала где Миша пока
# он снова не заговорит wake-word'ом (Flutter-путь не шлёт header). Теперь
# кеш пишется в hermes_home/device_context.json — при импорте модуля
# восстанавливается, при обновлении — перезаписывается.
_DEVICE_CONTEXT_CACHE: Dict[str, Dict[str, Any]] = {}


def _cache_file() -> Path:
    return get_hermes_home() / "device_context.json"


def _load_cache_from_disk() -> None:
    """Восстановить кеш из файла при старте процесса. Тихо игнорит ошибки."""
    try:
        p = _cache_file()
        if not p.exists():
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _DEVICE_CONTEXT_CACHE.update({k: v for k, v in data.items() if isinstance(v, dict)})
    except Exception as e:
        logger.debug("device_context cache load failed: %s", e)


def _save_cache_to_disk(*, strict: bool = False) -> None:
    """Сохранить весь кеш в файл. Вызывается после remember_device_context."""
    try:
        p = _cache_file()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(_DEVICE_CONTEXT_CACHE, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        logger.debug("device_context cache save failed: %s", e)
        if strict:
            raise


# Загружаем сразу при импорте модуля.
_load_cache_from_disk()


# ── Reverse geocoding (Nominatim/OSM, без ключа) ─────────────────────────────
# Кэш адресов по округлённым координатам, чтобы не дёргать Nominatim на каждый
# запрос (их лимит ~1 req/sec). Ключ — (lat,lon) с округлением до ~100 м.
_GEOCODE_CACHE: Dict[Tuple[float, float], Tuple[str, float]] = {}
_GEOCODE_TTL_SEC = 3600  # адрес для одной точки кэшируем час


def _geocode_key(lat: float, lon: float) -> Tuple[float, float]:
    # 3 знака после запятой ≈ 110 м — достаточно, чтобы не геокодить каждый шаг.
    return (round(lat, 3), round(lon, 3))


def _external_geocoding_enabled() -> bool:
    """Keep exact coordinates on the product server unless operator opts in."""
    return os.getenv("TROIKA_EXTERNAL_GEOCODING_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """Координаты → человекочитаемый адрес (RU). None при ошибке/таймауте.

    ВАЖНО: Nominatim ходим НАПРЯМУЮ, минуя HTTPS_PROXY/HTTP_PROXY. На сервере
    Тройки proxy = Tor SOCKS5 для обхода блокировок LLM-провайдеров; urllib
    stdlib не умеет socks и падает «Tor is not an HTTP Proxy». Nominatim
    публичный сервис — Tor не нужен.
    """
    if not _external_geocoding_enabled():
        return None
    key = _geocode_key(lat, lon)
    now = time.time()
    cached = _GEOCODE_CACHE.get(key)
    if cached and (now - cached[1]) < _GEOCODE_TTL_SEC:
        return cached[0]
    try:
        params = urllib.parse.urlencode({
            "lat": f"{lat:.6f}",
            "lon": f"{lon:.6f}",
            "format": "json",
            "accept-language": "ru",
            "zoom": "18",
        })
        url = f"https://nominatim.openstreetmap.org/reverse?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "TroikaAssistant/1.0"})
        # Пустой ProxyHandler = обход системного proxy env (Tor SOCKS5).
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        addr = _format_address(data)
        if addr:
            _GEOCODE_CACHE[key] = (addr, now)
        return addr
    except Exception as e:
        logger.warning("reverse_geocode failed for %s,%s: %s", lat, lon, e)
        return None


def _format_address(data: Dict[str, Any]) -> Optional[str]:
    """Собрать короткий понятный адрес из ответа Nominatim."""
    a = data.get("address") or {}
    if not a and data.get("display_name"):
        # запасной — первые 3 части display_name
        parts = [p.strip() for p in str(data["display_name"]).split(",")]
        return ", ".join(parts[:3]) or None
    road = a.get("road") or a.get("pedestrian") or a.get("neighbourhood")
    house = a.get("house_number")
    city = (
        a.get("city") or a.get("town") or a.get("village")
        or a.get("municipality") or a.get("suburb") or a.get("city_district")
    )
    region = a.get("state") or a.get("region")
    bits: List[str] = []
    if road:
        bits.append(f"{road} {house}".strip() if house else road)
    if city and city not in bits:
        bits.append(city)
    if region and region != city:
        bits.append(region)
    return ", ".join(bits) or None


def _db_path() -> Path:
    return get_hermes_home() / "locations.db"


def _conn() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute(
        "CREATE TABLE IF NOT EXISTS locations ("
        " session_key TEXT NOT NULL,"
        " name TEXT NOT NULL,"
        " bssid TEXT,"
        " ssid TEXT,"
        " network_type TEXT,"
        " bluetooth TEXT,"
        " device_name TEXT,"
        " updated_at REAL,"
        " PRIMARY KEY (session_key, name)"
        ")"
    )
    # Older builds used name as a global primary key, letting one account
    # overwrite or list another account's saved locations.  Migrate in place
    # while preserving the old rows in a deliberately isolated legacy scope.
    columns = c.execute("PRAGMA table_info(locations)").fetchall()
    primary_key = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
    if primary_key != ["session_key", "name"]:
        c.execute("ALTER TABLE locations RENAME TO locations_legacy")
        c.execute(
            "CREATE TABLE locations ("
            " session_key TEXT NOT NULL,"
            " name TEXT NOT NULL,"
            " bssid TEXT,"
            " ssid TEXT,"
            " network_type TEXT,"
            " bluetooth TEXT,"
            " device_name TEXT,"
            " updated_at REAL,"
            " PRIMARY KEY (session_key, name)"
            ")"
        )
        c.execute(
            "INSERT OR REPLACE INTO locations "
            "(session_key, name, bssid, ssid, network_type, bluetooth, device_name, updated_at) "
            "SELECT COALESCE(NULLIF(session_key, ''), 'legacy'), name, bssid, ssid, "
            "network_type, bluetooth, device_name, updated_at FROM locations_legacy"
        )
        c.execute("DROP TABLE locations_legacy")
    return c


def remember_device_context(session_key: str, ctx: Dict[str, Any]) -> None:
    """Вызывается api_server при получении X-Hermes-Device-Context."""
    if not session_key:
        logger.debug("device context ignored: no session scope")
        return
    _DEVICE_CONTEXT_CACHE[session_key] = dict(ctx) if ctx else {}
    # Пишем на диск чтобы пережить рестарт gateway. Иначе после каждого
    # рестарта Тройка не знает где Миша, пока он снова не заговорит wake-word'ом
    # (Flutter-путь пока не шлёт X-Hermes-Device-Context header).
    _save_cache_to_disk()


def clear_device_context(session_key: str) -> None:
    """Remove transient device context when a product user revokes consent."""
    if not session_key:
        return
    if _DEVICE_CONTEXT_CACHE.pop(session_key, None) is not None:
        _save_cache_to_disk()


def delete_location_scope(session_key: str) -> None:
    """Delete transient context and saved fingerprints for one product scope."""
    if not session_key:
        return
    _DEVICE_CONTEXT_CACHE.pop(session_key, None)
    # Reverse-geocode entries are keyed only by rounded coordinates, so their
    # owner cannot be identified safely. Clear this short-lived process cache.
    _GEOCODE_CACHE.clear()
    _save_cache_to_disk(strict=True)
    path = _db_path()
    if not path.exists():
        return
    connection = _conn()
    try:
        connection.execute(
            "DELETE FROM locations WHERE session_key = ?", (session_key,)
        )
        connection.commit()
    finally:
        connection.close()


def export_location_scope(session_key: str) -> Dict[str, Any]:
    """Return transient context and saved places for exactly one owner scope."""
    if not session_key:
        return {"device_context": {}, "saved_locations": []}
    device_context = dict(_DEVICE_CONTEXT_CACHE.get(session_key, {}))
    path = _db_path()
    if not path.exists():
        return {
            "device_context": device_context,
            "saved_locations": [],
        }
    connection = _conn()
    connection.row_factory = sqlite3.Row
    try:
        saved_locations = [
            dict(row)
            for row in connection.execute(
                "SELECT name, bssid, ssid, network_type, bluetooth, device_name, "
                "updated_at FROM locations WHERE session_key = ? "
                "ORDER BY updated_at, name",
                (session_key,),
            ).fetchall()
        ]
    finally:
        connection.close()
    return {
        "device_context": device_context,
        "saved_locations": saved_locations,
    }


def get_device_context(session_key: Optional[str] = None) -> Dict[str, Any]:
    if session_key and session_key in _DEVICE_CONTEXT_CACHE:
        return dict(_DEVICE_CONTEXT_CACHE[session_key])
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


def _identify_location(ctx: Dict[str, Any], session_key: str) -> Optional[Tuple[str, float]]:
    """Возвращает (name, score) лучшего совпадения или None."""
    if not ctx:
        return None
    try:
        c = _conn()
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM locations WHERE session_key = ?", (session_key,)
        ).fetchall()
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


def _gps_hint(ctx: Dict[str, Any]) -> str:
    """Строка с координатами для system prompt, если есть свежий GPS-fix."""
    gps = _gps(ctx)
    if not gps:
        return ""
    age = gps.get("age_sec")
    fresh = age is None or age <= 600  # ≤10 мин считаем актуальным
    age_note = ""
    if age is not None:
        if age <= 120:
            age_note = " (только что)"
        elif age <= 600:
            age_note = f" (~{age // 60} мин назад)"
        else:
            age_note = f" (устарело, ~{age // 60} мин назад)"
    acc = gps.get("accuracy_m")
    acc_note = f", точность ±{int(acc)} м" if acc else ""
    # Реальный адрес по координатам (Nominatim). Без него модель «угадывает» и
    # путает — например называет «центр Москвы», хотя это область.
    addr = reverse_geocode(gps["lat"], gps["lon"])
    if addr:
        addr_note = f" Адрес: {addr}."
        auth_rule = (
            "Это ТОЧНОЕ местоположение Миши — бери адрес ОТСЮДА, не выдумывай город/"
            "район. Используй для погоды рядом, мест поблизости, маршрутов, «где я»."
            if fresh
            else "Координаты могли устареть — учитывай это."
        )
    else:
        # Nominatim не ответил (таймаут/прокси/rate-limit). Даём чёткое указание:
        # НЕ ВЫДУМЫВАТЬ адрес, дать только координаты + ссылку. LLM обожает
        # придумать «Москва, метро X» по цифрам — это ложь, надо запретить.
        addr_note = " (адрес не получен — Nominatim не ответил)"
        auth_rule = (
            "У тебя есть ТОЛЬКО lat/lon. НЕ ВЫДУМЫВАЙ адрес, район, метро или улицу. "
            "Если Миша спросит «где я» — назови координаты и дай карту-ссылку, "
            "адрес честно скажи «не смогла получить». Не подставляй знакомые районы Москвы."
        )
    return (
        f"\n\nГДЕ МИША СЕЙЧАС (по GPS телефона): {gps['lat']}, {gps['lon']}"
        f"{acc_note}{age_note}.{addr_note} Карта: {gps['maps_url']}. "
        + auth_rule
    )


def system_prompt_amendment(session_key: Optional[str]) -> str:
    """Кусок текста для добавления в system prompt. Пусто если ничего не понятно."""
    ctx = get_device_context(session_key)
    if not ctx:
        return ""
    gps_hint = _gps_hint(ctx)
    match = _identify_location(ctx, session_key or "")
    if match is None:
        # Известен только тип сети — это тоже полезный сигнал
        net = (ctx.get("network_type") or "").lower()
        if net == "cellular":
            return gps_hint + (
                "\n\nКОНТЕКСТ МЕСТА: телефон Миши на мобильной сети (не дома и не на "
                "работе — возможно в дороге). Отвечай короче и без markdown."
            )
        return gps_hint

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
    return gps_hint + f"\n\nКОНТЕКСТ МЕСТА: {rule}"


# ── Tool operations ─────────────────────────────────────────────────────────


def _session_scope(args: Dict[str, Any]) -> Optional[str]:
    """Return framework-injected scope; models cannot select another user's ID."""
    value = args.get("_session_id")
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _set(args: Dict[str, Any], session_key: str) -> Dict[str, Any]:
    name = (args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "missing 'name'"}
    if len(name) > 40:
        name = name[:40]

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


def _gps(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """GPS-координаты из контекста, если телефон их прислал."""
    lat = ctx.get("lat")
    lon = ctx.get("lon")
    if lat is None or lon is None:
        return None
    try:
        out: Dict[str, Any] = {"lat": round(float(lat), 6), "lon": round(float(lon), 6)}
    except (TypeError, ValueError):
        return None
    acc = ctx.get("accuracy_m")
    if acc is not None:
        try:
            out["accuracy_m"] = round(float(acc), 1)
        except (TypeError, ValueError):
            pass
    age = ctx.get("location_age_sec")
    if age is not None:
        try:
            out["age_sec"] = int(age)
        except (TypeError, ValueError):
            pass
    out["maps_url"] = f"https://maps.google.com/?q={out['lat']},{out['lon']}"
    addr = reverse_geocode(out["lat"], out["lon"])
    if addr:
        out["address"] = addr
    return out


def _get(args: Dict[str, Any], session_key: str) -> Dict[str, Any]:
    ctx = get_device_context(session_key)
    if not ctx:
        return {"ok": True, "location": None, "reason": "no_device_context_yet"}
    gps = _gps(ctx)
    match = _identify_location(ctx, session_key)
    if match is None:
        net = ctx.get("network_type") or "?"
        return {
            "ok": True,
            "location": None,
            "network_type": net,
            "bluetooth_count": len(_bt_set(ctx)),
            "gps": gps,  # реальные координаты, даже если место не распознано
            "reason": "no_named_place" if gps else "no_match",
        }
    name, score = match
    return {
        "ok": True,
        "location": name,
        "confidence": round(score, 2),
        "gps": gps,
        "context_snapshot": {
            "network_type": ctx.get("network_type"),
            "bluetooth_count": len(_bt_set(ctx)),
            "has_bssid": bool(ctx.get("bssid")),
        },
    }


def _list(session_key: str) -> Dict[str, Any]:
    try:
        c = _conn()
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT name, network_type, ssid, bluetooth, updated_at FROM locations "
            "WHERE session_key = ? ORDER BY name",
            (session_key,),
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


def _forget(args: Dict[str, Any], session_key: str) -> Dict[str, Any]:
    name = (args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "missing 'name'"}
    try:
        c = _conn()
        cur = c.execute(
            "DELETE FROM locations WHERE session_key = ? AND name = ?",
            (session_key, name),
        )
        c.commit()
        deleted = cur.rowcount
        c.close()
    except sqlite3.Error as e:
        return {"ok": False, "error": f"sqlite: {e}"}
    return {"ok": True, "deleted": deleted, "name": name}


async def _handle(args: Dict[str, Any], **_kw) -> str:
    op = (args.get("operation") or "get").strip().lower()
    session_key = _session_scope(args)
    if not session_key:
        return json.dumps(
            {"ok": False, "error": "session_scope_unavailable"}, ensure_ascii=False
        )
    if op == "set":
        res = _set(args, session_key)
    elif op == "get":
        res = _get(args, session_key)
    elif op == "list":
        res = _list(session_key)
    elif op == "forget":
        res = _forget(args, session_key)
    else:
        res = {"ok": False, "error": f"unknown operation '{op}'", "allowed": ["set", "get", "list", "forget"]}
    return json.dumps(res, ensure_ascii=False)


LOCATION_SCHEMA = {
    "name": "location",
    "description": (
        "Где сейчас Миша: реальные GPS-координаты (lat/lon + ссылка на карту, если "
        "телефон их прислал) И/ИЛИ распознанное место по fingerprint'у (Wi-Fi BSSID, "
        "Bluetooth, тип сети). Используется когда Миша спрашивает 'где я', 'какие "
        "координаты', 'запомни это место как дом', 'я дома?', 'покажи мои места'. "
        "operations: get (где я сейчас — вернёт gps если есть), set (сохранить "
        "текущее место под именем), list (все места), forget (удалить место)."
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
