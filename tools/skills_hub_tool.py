"""
Skills hub — большой набор лёгких полезных tools для голосового ассистента.

Все используют только бесплатные публичные API:
  - погода (open-meteo)
  - Wikipedia (поиск + текст статьи)
  - переводчик (Google Translate через unofficial endpoint)
  - курсы валют (exchangerate-api открытый)
  - криптовалюты (coingecko)
  - новости (Hacker News, Lenta RSS через RSS-парсер)
  - QR-код (qrcode lib)
  - калькулятор
  - конвертер единиц
  - URL shortener (is.gd)
  - случайные факты, цитаты, шутки
  - YouTube search (через scraping без API)
  - время в любом городе (worldtimeapi)
  - таймер обратного отсчёта (для приготовления, тренировок)
  - дни до даты / возраст
  - случайные числа / выбор / монетка
"""

from __future__ import annotations

import io
import json
import logging
import random
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List

import aiohttp

logger = logging.getLogger(__name__)


def _bridge():
    from gateway.platforms.phone_bridge import bridge
    return bridge


async def _http_get_json(url: str, timeout: float = 15.0, headers: dict = None):
    async with aiohttp.ClientSession(headers=headers or {}) as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            if r.status != 200:
                return {"_status": r.status, "_text": (await r.text())[:300]}
            try:
                return await r.json(content_type=None)
            except Exception:
                return {"_text": (await r.text())[:5000]}


async def _http_get_text(url: str, timeout: float = 15.0, headers: dict = None) -> str:
    async with aiohttp.ClientSession(headers=headers or {}) as s:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            return await r.text()


# ============================================================================
# 1. Weather (open-meteo, free, no key)
# ============================================================================

async def _handle_weather(args: Dict[str, Any], **kw) -> str:
    city = (args.get("city") or args.get("location") or "").strip()
    if not city:
        return json.dumps({"ok": False, "error": "missing 'city'"}, ensure_ascii=False)

    # 1. Геокодинг через open-meteo
    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(city)}&count=1&language=ru&format=json"
    geo = await _http_get_json(geo_url)
    results = geo.get("results") if isinstance(geo, dict) else None
    if not results:
        return json.dumps({"ok": False, "error": f"city_not_found: {city}"}, ensure_ascii=False)
    loc = results[0]
    lat, lon = loc["latitude"], loc["longitude"]
    name = f"{loc.get('name')}, {loc.get('country', '')}"

    # 2. Текущая погода + прогноз на сегодня
    w_url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
             "&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
             "weather_code,wind_speed_10m,wind_direction_10m"
             "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum"
             "&timezone=auto&forecast_days=3")
    w = await _http_get_json(w_url)
    current = w.get("current", {})
    daily = w.get("daily", {})

    codes = {0: "ясно", 1: "в основном ясно", 2: "переменная облачность", 3: "пасмурно",
             45: "туман", 48: "изморозь",
             51: "морось", 53: "морось", 55: "сильная морось",
             61: "лёгкий дождь", 63: "дождь", 65: "сильный дождь",
             71: "лёгкий снег", 73: "снег", 75: "сильный снег",
             77: "снежная крупа",
             80: "ливни", 81: "сильные ливни", 82: "очень сильные ливни",
             85: "снег", 86: "сильный снег",
             95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом"}
    cur_code = current.get("weather_code")

    return json.dumps({
        "ok": True,
        "location": name,
        "current": {
            "temp_c": current.get("temperature_2m"),
            "feels_like_c": current.get("apparent_temperature"),
            "humidity_pct": current.get("relative_humidity_2m"),
            "wind_kmh": current.get("wind_speed_10m"),
            "is_day": bool(current.get("is_day")),
            "condition": codes.get(cur_code, f"код {cur_code}"),
        },
        "forecast_3days": [
            {"date": daily.get("time", [None, None, None])[i],
             "tmax_c": daily.get("temperature_2m_max", [None]*3)[i],
             "tmin_c": daily.get("temperature_2m_min", [None]*3)[i],
             "precip_mm": daily.get("precipitation_sum", [None]*3)[i],
             "condition": codes.get(daily.get("weather_code", [None]*3)[i], "")}
            for i in range(min(3, len(daily.get("time", []))))
        ],
    }, ensure_ascii=False)


# ============================================================================
# 2. Wikipedia
# ============================================================================

async def _handle_wikipedia(args: Dict[str, Any], **kw) -> str:
    query = (args.get("query") or args.get("topic") or "").strip()
    lang = args.get("lang", "ru")
    sentences = int(args.get("sentences", 5))
    if not query:
        return json.dumps({"ok": False, "error": "missing 'query'"}, ensure_ascii=False)

    # Сначала ищем
    search_url = (f"https://{lang}.wikipedia.org/w/api.php?action=opensearch&format=json"
                  f"&search={urllib.parse.quote(query)}&limit=1")
    search = await _http_get_json(search_url)
    if not isinstance(search, list) or len(search) < 4 or not search[1]:
        return json.dumps({"ok": False, "error": "not_found"}, ensure_ascii=False)
    title = search[1][0]
    url = search[3][0]

    # Получаем summary
    sum_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title)}"
    s = await _http_get_json(sum_url)
    extract = s.get("extract", "") if isinstance(s, dict) else ""

    # Обрезаем до N предложений
    sents = re.split(r"(?<=[.!?])\s+", extract)
    short = " ".join(sents[:sentences])

    return json.dumps({"ok": True, "title": title, "summary": short,
                       "url": url, "lang": lang}, ensure_ascii=False)


# ============================================================================
# 3. Translator (Google Translate unofficial)
# ============================================================================

async def _handle_translate(args: Dict[str, Any], **kw) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return json.dumps({"ok": False, "error": "missing 'text'"}, ensure_ascii=False)
    target = args.get("target_lang", "en")
    source = args.get("source_lang", "auto")

    url = (f"https://translate.googleapis.com/translate_a/single?client=gtx"
           f"&sl={source}&tl={target}&dt=t&q={urllib.parse.quote(text[:5000])}")
    try:
        result = await _http_get_json(url, timeout=20.0,
                                       headers={"User-Agent": "Mozilla/5.0"})
        if not isinstance(result, list) or not result[0]:
            return json.dumps({"ok": False, "error": "no_translation"}, ensure_ascii=False)
        translated = "".join(part[0] for part in result[0] if part and part[0])
        detected_lang = result[2] if len(result) > 2 else source
        return json.dumps({"ok": True, "translated": translated,
                           "source_lang": detected_lang, "target_lang": target},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"translate_failed: {e}"}, ensure_ascii=False)


# ============================================================================
# 4. Currency rates (exchangerate.host alternative — open.er-api.com, free)
# ============================================================================

async def _handle_currency_rate(args: Dict[str, Any], **kw) -> str:
    base = (args.get("base") or "USD").upper()
    target = (args.get("target") or "RUB").upper()
    amount = float(args.get("amount", 1))

    url = f"https://open.er-api.com/v6/latest/{base}"
    data = await _http_get_json(url)
    if not isinstance(data, dict) or data.get("result") != "success":
        return json.dumps({"ok": False, "error": "rates_unavailable",
                           "raw": str(data)[:200]}, ensure_ascii=False)
    rate = data.get("rates", {}).get(target)
    if rate is None:
        return json.dumps({"ok": False, "error": f"unknown_target: {target}"}, ensure_ascii=False)
    return json.dumps({"ok": True, "base": base, "target": target,
                       "rate": rate, "amount": amount, "result": round(amount * rate, 4),
                       "as_of": data.get("time_last_update_utc")}, ensure_ascii=False)


# ============================================================================
# 5. Crypto price (CoinGecko free)
# ============================================================================

async def _handle_crypto_price(args: Dict[str, Any], **kw) -> str:
    coin = (args.get("coin") or "bitcoin").lower()
    vs = (args.get("vs") or "usd").lower()
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin}&vs_currencies={vs}&include_24hr_change=true"
    data = await _http_get_json(url)
    if not isinstance(data, dict) or coin not in data:
        return json.dumps({"ok": False, "error": "coin_not_found"}, ensure_ascii=False)
    return json.dumps({"ok": True, "coin": coin,
                       "price": data[coin].get(vs),
                       "change_24h_pct": data[coin].get(f"{vs}_24h_change"),
                       "vs": vs}, ensure_ascii=False)


# ============================================================================
# 6. News (Hacker News top)
# ============================================================================

async def _handle_hackernews(args: Dict[str, Any], **kw) -> str:
    n = int(args.get("limit", 5))
    ids = await _http_get_json("https://hacker-news.firebaseio.com/v0/topstories.json")
    if not isinstance(ids, list):
        return json.dumps({"ok": False, "error": "hn_unavailable"}, ensure_ascii=False)
    items = []
    for sid in ids[:n]:
        item = await _http_get_json(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
        if isinstance(item, dict):
            items.append({"title": item.get("title"), "url": item.get("url"),
                          "score": item.get("score"), "by": item.get("by")})
    return json.dumps({"ok": True, "items": items}, ensure_ascii=False)


# ============================================================================
# 7. QR code
# ============================================================================

async def _handle_qr_code(args: Dict[str, Any], **kw) -> str:
    try:
        import qrcode
    except ImportError:
        return json.dumps({"ok": False, "error": "qrcode library not installed"}, ensure_ascii=False)

    data = args.get("data") or args.get("text") or ""
    if not data:
        return json.dumps({"ok": False, "error": "missing 'data'"}, ensure_ascii=False)
    filename = args.get("filename") or "qr.png"
    if not filename.lower().endswith(".png"):
        filename += ".png"

    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    img_data = buf.getvalue()

    import base64
    encoded = base64.b64encode(img_data).decode("ascii")
    result = await _bridge().send_command(
        "file_write",
        {"path": f"Pictures/Hermes/{filename}", "content": encoded,
         "encoding": "base64", "append": False},
        timeout=30.0,
    )
    return json.dumps({"ok": result.get("ok", False), "filename": filename,
                       "data": data[:100], "size": len(img_data),
                       "phone_result": result}, ensure_ascii=False)


# ============================================================================
# 8. Calculator (safe eval)
# ============================================================================

async def _handle_calculator(args: Dict[str, Any], **kw) -> str:
    expr = (args.get("expression") or "").strip()
    if not expr:
        return json.dumps({"ok": False, "error": "missing 'expression'"}, ensure_ascii=False)
    # Безопасный eval: только цифры, операторы, sqrt/sin/cos/pi/e
    allowed = re.compile(r"^[\d\s+\-*/().,%^a-z_]+$", re.IGNORECASE)
    if not allowed.match(expr):
        return json.dumps({"ok": False, "error": "unsafe characters"}, ensure_ascii=False)
    expr_py = expr.replace("^", "**").replace(",", ".")
    import math
    safe_funcs = {k: getattr(math, k) for k in
                  ["sqrt", "sin", "cos", "tan", "log", "log10", "exp", "pi", "e",
                   "floor", "ceil", "fabs", "atan", "asin", "acos"]}
    safe_funcs.update({"abs": abs, "round": round, "min": min, "max": max})
    try:
        result = eval(expr_py, {"__builtins__": {}}, safe_funcs)
        return json.dumps({"ok": True, "expression": expr, "result": result},
                          ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"calc_error: {e}"}, ensure_ascii=False)


# ============================================================================
# 9. Unit converter (simple offline)
# ============================================================================

_UNIT_CONV = {
    "length": {"m": 1, "km": 1000, "cm": 0.01, "mm": 0.001,
               "mile": 1609.344, "miles": 1609.344, "ft": 0.3048, "feet": 0.3048,
               "inch": 0.0254, "inches": 0.0254, "yard": 0.9144},
    "mass": {"g": 1, "kg": 1000, "mg": 0.001, "t": 1000000, "tonne": 1000000,
             "lb": 453.592, "oz": 28.3495, "pound": 453.592, "ounce": 28.3495},
    "temperature": None,  # специально
    "volume": {"l": 1, "ml": 0.001, "m3": 1000, "cup": 0.24, "pint": 0.473, "gallon": 3.785},
    "speed": {"kmh": 1, "mph": 1.60934, "ms": 3.6, "knot": 1.852},
    "time": {"s": 1, "min": 60, "h": 3600, "day": 86400, "week": 604800, "month": 2628000, "year": 31536000},
}


async def _handle_unit_convert(args: Dict[str, Any], **kw) -> str:
    value = args.get("value")
    src = (args.get("from") or "").lower()
    dst = (args.get("to") or "").lower()
    if value is None or not src or not dst:
        return json.dumps({"ok": False, "error": "need value, from, to"}, ensure_ascii=False)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "invalid value"}, ensure_ascii=False)

    # Temperature
    if src in ("c", "celsius", "°c") or dst in ("c", "celsius", "°c") or \
       src in ("f", "fahrenheit", "°f") or dst in ("f", "fahrenheit", "°f") or \
       src in ("k", "kelvin") or dst in ("k", "kelvin"):
        def to_c(v, u):
            if u in ("c", "celsius", "°c"): return v
            if u in ("f", "fahrenheit", "°f"): return (v - 32) * 5 / 9
            if u in ("k", "kelvin"): return v - 273.15
            raise ValueError(f"unknown temp unit: {u}")
        def from_c(v, u):
            if u in ("c", "celsius", "°c"): return v
            if u in ("f", "fahrenheit", "°f"): return v * 9 / 5 + 32
            if u in ("k", "kelvin"): return v + 273.15
            raise ValueError(f"unknown temp unit: {u}")
        try:
            celsius = to_c(value, src)
            result = from_c(celsius, dst)
            return json.dumps({"ok": True, "value": value, "from": src, "to": dst,
                               "result": round(result, 4)}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)

    for category, units in _UNIT_CONV.items():
        if units is None:
            continue
        if src in units and dst in units:
            base = value * units[src]
            result = base / units[dst]
            return json.dumps({"ok": True, "value": value, "from": src, "to": dst,
                               "result": round(result, 6),
                               "category": category}, ensure_ascii=False)
    return json.dumps({"ok": False, "error": "incompatible_or_unknown_units"}, ensure_ascii=False)


# ============================================================================
# 10. World time
# ============================================================================

async def _handle_world_time(args: Dict[str, Any], **kw) -> str:
    timezone_str = (args.get("timezone") or args.get("city") or "Europe/Moscow").strip()
    # worldtimeapi.org
    if "/" not in timezone_str:
        # пытаемся угадать через города
        guesses = {
            "moscow": "Europe/Moscow", "москва": "Europe/Moscow",
            "london": "Europe/London", "лондон": "Europe/London",
            "new york": "America/New_York", "нью-йорк": "America/New_York",
            "tokyo": "Asia/Tokyo", "токио": "Asia/Tokyo",
            "paris": "Europe/Paris", "париж": "Europe/Paris",
            "berlin": "Europe/Berlin", "берлин": "Europe/Berlin",
            "dubai": "Asia/Dubai", "дубай": "Asia/Dubai",
            "kiev": "Europe/Kyiv", "киев": "Europe/Kyiv",
            "minsk": "Europe/Minsk", "минск": "Europe/Minsk",
        }
        timezone_str = guesses.get(timezone_str.lower(), timezone_str)
    url = f"https://worldtimeapi.org/api/timezone/{timezone_str}"
    data = await _http_get_json(url)
    if not isinstance(data, dict) or "datetime" not in data:
        return json.dumps({"ok": False, "error": "tz_not_found", "raw": str(data)[:200]}, ensure_ascii=False)
    return json.dumps({"ok": True, "timezone": data.get("timezone"),
                       "datetime": data.get("datetime"),
                       "utc_offset": data.get("utc_offset"),
                       "day_of_week": data.get("day_of_week"),
                       "day_of_year": data.get("day_of_year")}, ensure_ascii=False)


# ============================================================================
# 11. URL shortener (is.gd)
# ============================================================================

async def _handle_url_shorten(args: Dict[str, Any], **kw) -> str:
    url = (args.get("url") or "").strip()
    if not url:
        return json.dumps({"ok": False, "error": "missing 'url'"}, ensure_ascii=False)
    shortener = f"https://is.gd/create.php?format=simple&url={urllib.parse.quote(url)}"
    try:
        short = await _http_get_text(shortener)
        short = short.strip()
        if short.startswith("http"):
            return json.dumps({"ok": True, "original": url, "short": short},
                              ensure_ascii=False)
        return json.dumps({"ok": False, "error": short[:200]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


# ============================================================================
# 12. Random utilities
# ============================================================================

async def _handle_random(args: Dict[str, Any], **kw) -> str:
    kind = (args.get("kind") or "number").lower()
    if kind == "number":
        a = int(args.get("min", 1))
        b = int(args.get("max", 100))
        return json.dumps({"ok": True, "value": random.randint(a, b)})
    if kind == "coin":
        return json.dumps({"ok": True, "value": random.choice(["heads", "tails"])})
    if kind == "dice":
        sides = int(args.get("sides", 6))
        return json.dumps({"ok": True, "value": random.randint(1, sides)})
    if kind == "choice":
        opts = args.get("options") or []
        if not opts:
            return json.dumps({"ok": False, "error": "missing options"}, ensure_ascii=False)
        return json.dumps({"ok": True, "value": random.choice(opts)}, ensure_ascii=False)
    if kind == "uuid":
        import uuid
        return json.dumps({"ok": True, "value": str(uuid.uuid4())})
    if kind == "password":
        import string
        length = int(args.get("length", 16))
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        return json.dumps({"ok": True, "value": "".join(random.choice(alphabet) for _ in range(length))})
    return json.dumps({"ok": False, "error": f"unknown kind: {kind}"}, ensure_ascii=False)


# ============================================================================
# 13. Date math
# ============================================================================

async def _handle_date_math(args: Dict[str, Any], **kw) -> str:
    op = (args.get("op") or "days_until").lower()
    today = datetime.now()
    if op == "days_until":
        date_str = args.get("date")
        if not date_str:
            return json.dumps({"ok": False, "error": "missing 'date'"}, ensure_ascii=False)
        try:
            target = datetime.fromisoformat(date_str)
        except Exception:
            try:
                target = datetime.strptime(date_str, "%d.%m.%Y")
            except Exception:
                return json.dumps({"ok": False, "error": "bad date format"}, ensure_ascii=False)
        delta = (target.date() - today.date()).days
        return json.dumps({"ok": True, "days": delta,
                           "from": today.date().isoformat(),
                           "to": target.date().isoformat()}, ensure_ascii=False)
    if op == "age":
        date_str = args.get("birthdate") or args.get("date")
        try:
            bd = datetime.fromisoformat(date_str)
        except Exception:
            try:
                bd = datetime.strptime(date_str, "%d.%m.%Y")
            except Exception:
                return json.dumps({"ok": False, "error": "bad date format"}, ensure_ascii=False)
        years = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        return json.dumps({"ok": True, "age_years": years}, ensure_ascii=False)
    return json.dumps({"ok": False, "error": f"unknown op: {op}"}, ensure_ascii=False)


# ============================================================================
# 14. YouTube search (через scraping без API)
# ============================================================================

async def _handle_youtube_search(args: Dict[str, Any], **kw) -> str:
    query = (args.get("query") or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "missing 'query'"}, ensure_ascii=False)
    limit = int(args.get("limit", 5))
    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
    try:
        html = await _http_get_text(url, headers={"User-Agent": "Mozilla/5.0"})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    # Простой парсинг initial data
    ids = re.findall(r'"videoId":"([^"]+)"', html)
    titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"\}', html)
    seen = set()
    results = []
    for vid, title in zip(ids, titles):
        if vid in seen:
            continue
        seen.add(vid)
        results.append({"title": title, "url": f"https://youtube.com/watch?v={vid}",
                        "video_id": vid})
        if len(results) >= limit:
            break
    return json.dumps({"ok": True, "query": query, "results": results}, ensure_ascii=False)


# ============================================================================
# 15. Random joke / fact (бесплатные API)
# ============================================================================

async def _handle_joke(args: Dict[str, Any], **kw) -> str:
    lang = args.get("lang", "ru")
    if lang == "ru":
        # анекдоты от RandomUsefulAPI / lol-api fallback
        url = "https://anecdotica.ru/api/?method=getrandfact&fkey=BB1D"
        try:
            data = await _http_get_json(url)
            if isinstance(data, dict) and "item" in data:
                text = data["item"].get("text", "").strip()
                return json.dumps({"ok": True, "joke": text}, ensure_ascii=False)
        except Exception:
            pass
        # fallback на en и переводим
        en = await _http_get_json("https://official-joke-api.appspot.com/random_joke")
        if isinstance(en, dict):
            return json.dumps({"ok": True,
                               "joke": f"{en.get('setup', '')} {en.get('punchline', '')}",
                               "note": "english fallback"}, ensure_ascii=False)
    data = await _http_get_json("https://official-joke-api.appspot.com/random_joke")
    if isinstance(data, dict):
        return json.dumps({"ok": True, "joke": f"{data.get('setup', '')} {data.get('punchline', '')}"},
                          ensure_ascii=False)
    return json.dumps({"ok": False, "error": "no joke"}, ensure_ascii=False)


async def _handle_fact(args: Dict[str, Any], **kw) -> str:
    lang = args.get("lang", "ru")
    url = ("https://uselessfacts.jsph.pl/api/v2/facts/random?language=" +
           ("ru" if lang == "ru" else "en"))
    data = await _http_get_json(url)
    if isinstance(data, dict) and "text" in data:
        return json.dumps({"ok": True, "fact": data["text"]}, ensure_ascii=False)
    return json.dumps({"ok": False, "error": "no fact"}, ensure_ascii=False)


# ============================================================================
# Schemas
# ============================================================================

_SCHEMAS = [
    ("weather", _handle_weather, {
        "description": "Get current weather and 3-day forecast for any city (open-meteo, free).",
        "params": {"city": {"type": "string"}}, "required": ["city"]}),
    ("wikipedia", _handle_wikipedia, {
        "description": "Search Wikipedia and get a short summary of an article.",
        "params": {"query": {"type": "string"},
                   "lang": {"type": "string", "description": "ru/en/de/etc. Default ru."},
                   "sentences": {"type": "integer"}},
        "required": ["query"]}),
    ("translate", _handle_translate, {
        "description": "Translate text between languages (Google Translate, free unofficial).",
        "params": {"text": {"type": "string"},
                   "target_lang": {"type": "string", "description": "ru/en/de/es/fr/zh/etc."},
                   "source_lang": {"type": "string", "description": "'auto' to detect."}},
        "required": ["text", "target_lang"]}),
    ("currency_rate", _handle_currency_rate, {
        "description": "Get current currency exchange rate. Free API, no key.",
        "params": {"base": {"type": "string", "description": "e.g. USD"},
                   "target": {"type": "string", "description": "e.g. RUB"},
                   "amount": {"type": "number"}}, "required": []}),
    ("crypto_price", _handle_crypto_price, {
        "description": "Get crypto price via CoinGecko (free, no key).",
        "params": {"coin": {"type": "string", "description": "bitcoin/ethereum/solana/etc"},
                   "vs": {"type": "string", "description": "usd/eur/rub"}}, "required": []}),
    ("hackernews", _handle_hackernews, {
        "description": "Get top stories from Hacker News.",
        "params": {"limit": {"type": "integer"}}, "required": []}),
    ("qr_code", _handle_qr_code, {
        "description": "Generate a QR code for any text/URL and save to phone's Pictures/Hermes/.",
        "params": {"data": {"type": "string"}, "filename": {"type": "string"}},
        "required": ["data"]}),
    ("calculator", _handle_calculator, {
        "description": "Safe math expression evaluator. Supports +-*/^, sqrt/sin/cos/log/etc.",
        "params": {"expression": {"type": "string"}}, "required": ["expression"]}),
    ("unit_convert", _handle_unit_convert, {
        "description": "Convert units. Categories: length(m/km/mile/ft/inch), mass(g/kg/lb/oz), temperature(c/f/k), volume, speed, time.",
        "params": {"value": {"type": "number"}, "from": {"type": "string"},
                   "to": {"type": "string"}}, "required": ["value", "from", "to"]}),
    ("world_time", _handle_world_time, {
        "description": "Get current time in any timezone or city.",
        "params": {"timezone": {"type": "string",
                                "description": "Europe/Moscow, America/New_York, or city name."}},
        "required": []}),
    ("url_shorten", _handle_url_shorten, {
        "description": "Shorten a long URL via is.gd.",
        "params": {"url": {"type": "string"}}, "required": ["url"]}),
    ("random_value", _handle_random, {
        "description": "Generate random value. kind: number|coin|dice|choice|uuid|password.",
        "params": {"kind": {"type": "string"},
                   "min": {"type": "integer"}, "max": {"type": "integer"},
                   "sides": {"type": "integer"}, "length": {"type": "integer"},
                   "options": {"type": "array"}},
        "required": ["kind"]}),
    ("date_math", _handle_date_math, {
        "description": "Days until a date, or compute age from birthdate. op=days_until|age.",
        "params": {"op": {"type": "string"}, "date": {"type": "string"},
                   "birthdate": {"type": "string"}}, "required": ["op"]}),
    ("youtube_search", _handle_youtube_search, {
        "description": "Search YouTube and return top videos (title + url).",
        "params": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["query"]}),
    ("joke", _handle_joke, {
        "description": "Random joke. lang: ru|en.",
        "params": {"lang": {"type": "string"}}, "required": []}),
    ("fact", _handle_fact, {
        "description": "Random interesting fact. lang: ru|en.",
        "params": {"lang": {"type": "string"}}, "required": []}),
]


from tools.registry import registry  # noqa: E402

# Top-level зарегистрированный tool — нужен чтобы AST-сканер
# `discover_builtin_tools` подхватил этот файл. Сам по себе ничего не ломает,
# а после него в цикле регистрируются остальные.
registry.register(
    name="skill_weather",
    toolset="skills_hub",
    schema={
        "name": "skill_weather",
        "description": _SCHEMAS[0][2]["description"],
        "parameters": {"type": "object",
                       "properties": _SCHEMAS[0][2]["params"],
                       "required": _SCHEMAS[0][2].get("required", [])},
    },
    handler=_handle_weather,
    is_async=True,
    emoji="✨",
    override=True,
)

for name, handler, meta in _SCHEMAS:
    if name == "weather":
        continue  # уже зарегистрирован выше как top-level call
    schema = {
        "name": f"skill_{name}",
        "description": meta["description"],
        "parameters": {
            "type": "object",
            "properties": meta["params"],
            "required": meta.get("required", []),
        },
    }
    registry.register(name=f"skill_{name}", toolset="skills_hub",
                      schema=schema, handler=handler,
                      is_async=True, emoji="✨")
