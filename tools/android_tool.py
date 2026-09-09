"""
Android phone control tools — LLM управляет подключённым к Hermes Android-телефоном.

Реализация — тонкая обёртка над ``gateway.platforms.phone_bridge.bridge``,
которое держит WebSocket с приложением Hermes на телефоне.
Все вызовы возвращают JSON-результат от телефона.

Подключение телефона:
- На PC должен быть запущен ``hermes gateway --platforms api`` (порт 8642)
- Телефон с приложением Hermes должен иметь URL сервера в настройках
- Tailscale (или другой VPN) должен соединять оба устройства

Чтобы сложные действия (нажатия, ввод текста) работали, на телефоне нужен
включённый AccessibilityService Hermes (Настройки → Спец. возможности → Hermes).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def _bridge():
    if _is_product_phone_context():
        from gateway.platforms.phone_bridge import product_bridge

        return product_bridge
    from gateway.platforms.phone_bridge import bridge

    return bridge


def _product_device_id() -> str:
    """Return the server-derived device identity for a product agent turn."""
    try:
        from gateway.session_context import get_session_env

        return get_session_env("TROIKA_PRODUCT_DEVICE_ID", "").strip()
    except Exception:
        return ""


def _is_product_phone_context() -> bool:
    try:
        from gateway.session_context import get_session_env

        return get_session_env("TROIKA_PRODUCT_MODE", "") == "1"
    except Exception:
        return False


def _check_phone_connected():
    """Возвращает True если телефон подключён (для check_fn в registry)."""
    try:
        if _is_product_phone_context():
            device_id = _product_device_id()
            return bool(device_id and _bridge().is_connected(device_id))
        return _bridge().is_connected()
    except Exception:
        return False


def _product_approval_description(action: str, params: Dict[str, Any]) -> str:
    """Build a short, user-visible description without exposing server state."""
    def text(name: str, fallback: str = "") -> str:
        value = " ".join(str(params.get(name, fallback) or "").split())
        return value[:160]

    if action == "open_app":
        return f"Открыть приложение «{text('app', 'выбранное')}» на вашем телефоне."
    if action == "web_search":
        return f"Открыть поиск «{text('query', 'запрос')}» на вашем телефоне."
    if action == "set_alarm":
        return f"Установить будильник на {text('hour', '0')}:{text('minute', '00')} на вашем телефоне."
    if action == "set_timer":
        return f"Запустить таймер на {text('seconds', '0')} секунд на вашем телефоне."
    if action == "navigate":
        return f"Открыть маршрут до «{text('destination', 'указанного места')}» на вашем телефоне."
    if action == "volume":
        return f"Изменить громкость телефона на «{text('level', 'указанный уровень')}»."
    if action == "brightness":
        return f"Изменить яркость экрана на «{text('level', 'указанный уровень')}»."
    if action == "torch":
        return "Изменить состояние фонарика на вашем телефоне."
    if action == "camera_photo":
        return "Открыть камеру на вашем телефоне."
    return "Выполнить действие на вашем телефоне."


async def _call_phone(action: str, params: Dict[str, Any] | None = None, timeout: float = 15.0) -> str:
    """Послать команду на телефон и вернуть JSON-результат для LLM."""
    command_params = params or {}
    if _is_product_phone_context():
        device_id = _product_device_id()
        if not device_id:
            return json.dumps({"ok": False, "error": "product_device_required"}, ensure_ascii=False)
        product_phone = _bridge()
        if not product_phone.is_allowed_action(action):
            return json.dumps({"ok": False, "error": "product_action_not_available"}, ensure_ascii=False)
        if product_phone.requires_confirmation(action):
            from tools.approval import request_gateway_approval

            approval = request_gateway_approval(
                f"phone.{action}", _product_approval_description(action, command_params)
            )
            if not approval.get("approved"):
                return json.dumps(
                    {"ok": False, "error": "phone_action_not_confirmed"},
                    ensure_ascii=False,
                )
        result = await product_phone.send_command(
            device_id, action, command_params, timeout=timeout
        )
    else:
        result = await _bridge().send_command(action, command_params, timeout=timeout)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Handlers — асинхронные, принимают dict с параметрами, возвращают строку
# ---------------------------------------------------------------------------

async def _handle_open_app(args: Dict[str, Any], **kw) -> str:
    app = args.get("app") or args.get("name") or ""
    if not app:
        return json.dumps({"ok": False, "error": "missing 'app'"}, ensure_ascii=False)
    return await _call_phone("open_app", {"app": app}, timeout=10)


async def _handle_call(args: Dict[str, Any], **kw) -> str:
    number = args.get("number") or args.get("phone") or ""
    if not number:
        return json.dumps({"ok": False, "error": "missing 'number'"}, ensure_ascii=False)
    return await _call_phone("call", {"number": number}, timeout=10)


async def _handle_send_sms(args: Dict[str, Any], **kw) -> str:
    number = args.get("number") or ""
    text = args.get("text") or args.get("message") or ""
    if not number or not text:
        return json.dumps({"ok": False, "error": "need 'number' and 'text'"}, ensure_ascii=False)
    return await _call_phone("send_sms", {"number": number, "text": text}, timeout=10)


async def _handle_set_alarm(args: Dict[str, Any], **kw) -> str:
    hour = args.get("hour")
    minute = args.get("minute", 0)
    label = args.get("label", "")
    if hour is None:
        return json.dumps({"ok": False, "error": "missing 'hour'"}, ensure_ascii=False)
    return await _call_phone(
        "set_alarm",
        {"hour": int(hour), "minute": int(minute), "label": label},
        timeout=10,
    )


async def _handle_set_timer(args: Dict[str, Any], **kw) -> str:
    seconds = args.get("seconds")
    if seconds is None:
        return json.dumps({"ok": False, "error": "missing 'seconds'"}, ensure_ascii=False)
    return await _call_phone("set_timer", {"seconds": int(seconds)}, timeout=10)


async def _handle_navigate(args: Dict[str, Any], **kw) -> str:
    destination = args.get("destination") or args.get("address") or ""
    if not destination:
        return json.dumps({"ok": False, "error": "missing 'destination'"}, ensure_ascii=False)
    return await _call_phone("navigate", {"destination": destination}, timeout=10)


async def _handle_web_search(args: Dict[str, Any], **kw) -> str:
    query = args.get("query") or args.get("q") or ""
    if not query:
        return json.dumps({"ok": False, "error": "missing 'query'"}, ensure_ascii=False)
    return await _call_phone("web_search", {"query": query}, timeout=10)


async def _handle_volume(args: Dict[str, Any], **kw) -> str:
    level = args.get("level")  # 0..100 или "max"/"mute"/"up"/"down"
    return await _call_phone("volume", {"level": level}, timeout=10)


async def _handle_brightness(args: Dict[str, Any], **kw) -> str:
    level = args.get("level")
    return await _call_phone("brightness", {"level": level}, timeout=10)


async def _handle_tap(args: Dict[str, Any], **kw) -> str:
    text = args.get("text") or ""
    desc = args.get("desc") or args.get("description") or ""
    x = args.get("x")
    y = args.get("y")
    if not text and not desc and (x is None or y is None):
        return json.dumps({"ok": False, "error": "need 'text', 'desc' or ('x' and 'y')"}, ensure_ascii=False)
    return await _call_phone(
        "tap",
        {"text": text, "desc": desc, "x": x, "y": y},
        timeout=10,
    )


async def _handle_type_text(args: Dict[str, Any], **kw) -> str:
    text = args.get("text") or ""
    if not text:
        return json.dumps({"ok": False, "error": "missing 'text'"}, ensure_ascii=False)
    return await _call_phone("type_text", {"text": text}, timeout=10)


async def _handle_swipe(args: Dict[str, Any], **kw) -> str:
    direction = args.get("direction", "down")  # up/down/left/right
    return await _call_phone("swipe", {"direction": direction}, timeout=10)


async def _handle_press_back(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("press_back", {}, timeout=5)


async def _handle_press_home(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("press_home", {}, timeout=5)


async def _handle_read_screen(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("read_screen", {}, timeout=10)


async def _handle_status(args: Dict[str, Any], **kw) -> str:
    connected = _check_phone_connected()
    if not connected:
        return json.dumps({"ok": False, "connected": False, "error": "phone not connected"}, ensure_ascii=False)
    return await _call_phone("status", {}, timeout=5)


# ---- File operations on the phone ----------------------------------------

async def _handle_file_list(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("file_list", {
        "path": args.get("path", ""),
        "recursive": bool(args.get("recursive", False)),
        "pattern": args.get("pattern"),
    }, timeout=20)


async def _handle_file_read(args: Dict[str, Any], **kw) -> str:
    path = args.get("path") or ""
    if not path:
        return json.dumps({"ok": False, "error": "missing 'path'"}, ensure_ascii=False)
    return await _call_phone("file_read", {
        "path": path,
        "encoding": args.get("encoding", "auto"),
        "max_bytes": int(args.get("max_bytes", 5 * 1024 * 1024)),
    }, timeout=30)


async def _handle_file_write(args: Dict[str, Any], **kw) -> str:
    path = args.get("path") or ""
    if not path:
        return json.dumps({"ok": False, "error": "missing 'path'"}, ensure_ascii=False)
    return await _call_phone("file_write", {
        "path": path,
        "content": args.get("content", ""),
        "encoding": args.get("encoding", "text"),
        "append": bool(args.get("append", False)),
    }, timeout=30)


async def _handle_push_file(args: Dict[str, Any], **kw) -> str:
    """Скинуть файл С СЕРВЕРА на телефон. «Скинь мне на телефон X».

    Берёт файл по пути на сервере (например результат gemini_code, скачанный
    файл, скриншот), сам читает+кодирует base64 и пишет на телефон — без
    протаскивания контента через контекст LLM (работает для больших файлов).
    По умолчанию кладёт в Downloads/. Картинки можно сразу в галерею
    (to_gallery=true → команда save_to_gallery на телефоне).
    """
    import base64 as _b64
    import os

    src = args.get("server_path") or args.get("src") or ""
    if not src:
        return json.dumps({"ok": False, "error": "missing 'server_path'"}, ensure_ascii=False)
    if not os.path.isfile(src):
        return json.dumps({"ok": False, "error": f"file_not_found_on_server: {src}"}, ensure_ascii=False)

    try:
        size = os.path.getsize(src)
        # Защита: не тащим гигабайты по WS
        if size > 50 * 1024 * 1024:
            return json.dumps({"ok": False, "error": f"file_too_big: {size} bytes (max 50MB)"}, ensure_ascii=False)
        with open(src, "rb") as f:
            data_b64 = _b64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        return json.dumps({"ok": False, "error": f"read_failed: {e}"}, ensure_ascii=False)

    filename = args.get("filename") or os.path.basename(src)
    to_gallery = bool(args.get("to_gallery", False))

    if to_gallery:
        # Картинка/видео → в галерею телефона (MediaStore)
        return await _call_phone("save_to_gallery", {
            "filename": filename,
            "content": data_b64,
        }, timeout=60)

    # Обычный файл → в Downloads/ (или указанный путь)
    dest = args.get("phone_path") or filename
    return await _call_phone("file_write", {
        "path": dest,
        "content": data_b64,
        "encoding": "base64",
    }, timeout=60)


async def _handle_file_delete(args: Dict[str, Any], **kw) -> str:
    path = args.get("path") or ""
    if not path:
        return json.dumps({"ok": False, "error": "missing 'path'"}, ensure_ascii=False)
    return await _call_phone("file_delete", {
        "path": path,
        "recursive": bool(args.get("recursive", False)),
    }, timeout=15)


async def _handle_file_move(args: Dict[str, Any], **kw) -> str:
    src = args.get("src") or ""
    dst = args.get("dst") or ""
    if not src or not dst:
        return json.dumps({"ok": False, "error": "need 'src' and 'dst'"}, ensure_ascii=False)
    return await _call_phone("file_move", {
        "src": src,
        "dst": dst,
        "overwrite": bool(args.get("overwrite", False)),
    }, timeout=20)


async def _handle_file_info(args: Dict[str, Any], **kw) -> str:
    path = args.get("path") or ""
    if not path:
        return json.dumps({"ok": False, "error": "missing 'path'"}, ensure_ascii=False)
    return await _call_phone("file_info", {"path": path}, timeout=10)


async def _handle_request_all_files_access(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("request_all_files_access", {}, timeout=5)


# ---- System / hardware tools --------------------------------------------

async def _handle_clipboard_get(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("clipboard_get", {}, timeout=5)


async def _handle_clipboard_set(args: Dict[str, Any], **kw) -> str:
    text = args.get("text") or ""
    return await _call_phone("clipboard_set", {"text": text}, timeout=5)


async def _handle_torch(args: Dict[str, Any], **kw) -> str:
    on = args.get("on")
    if on is None:
        return await _call_phone("torch_toggle", {}, timeout=5)
    return await _call_phone("torch", {"on": bool(on)}, timeout=5)


async def _handle_battery(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("battery", {}, timeout=5)


async def _handle_network(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("network", {}, timeout=5)


async def _handle_camera_photo(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("camera_photo", {"front": bool(args.get("front", False))}, timeout=10)


async def _handle_calendar_list_calendars(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("calendar_list_calendars", {}, timeout=10)


async def _handle_calendar_list_events(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("calendar_list_events", {
        "from": args.get("from") or args.get("from_iso"),
        "to": args.get("to") or args.get("to_iso"),
        "max": int(args.get("max", 50)),
    }, timeout=15)


async def _handle_calendar_create_event(args: Dict[str, Any], **kw) -> str:
    title = args.get("title") or ""
    start = args.get("start") or args.get("start_iso") or ""
    if not title or not start:
        return json.dumps({"ok": False, "error": "need 'title' and 'start' (ISO 8601)"}, ensure_ascii=False)
    payload = {
        "title": title,
        "start": start,
        "end": args.get("end") or args.get("end_iso"),
        "description": args.get("description"),
        "location": args.get("location"),
        "reminder_minutes": args.get("reminder_minutes"),
        "calendar_id": args.get("calendar_id"),
    }
    return await _call_phone("calendar_create_event", payload, timeout=15)


async def _handle_calendar_update_event(args: Dict[str, Any], **kw) -> str:
    event_id = args.get("event_id")
    if event_id is None:
        return json.dumps({"ok": False, "error": "missing 'event_id'"}, ensure_ascii=False)
    payload = {
        "event_id": int(event_id),
        "title": args.get("title"),
        "start": args.get("start") or args.get("start_iso"),
        "end": args.get("end") or args.get("end_iso"),
        "description": args.get("description"),
        "location": args.get("location"),
    }
    return await _call_phone("calendar_update_event", payload, timeout=15)


async def _handle_calendar_delete_event(args: Dict[str, Any], **kw) -> str:
    event_id = args.get("event_id")
    if event_id is None:
        return json.dumps({"ok": False, "error": "missing 'event_id'"}, ensure_ascii=False)
    return await _call_phone("calendar_delete_event", {"event_id": int(event_id)}, timeout=10)


async def _handle_calendar_check_permissions(args: Dict[str, Any], **kw) -> str:
    return await _call_phone("calendar_check_permissions", {}, timeout=5)


async def _handle_screenshot(args: Dict[str, Any], **kw) -> str:
    """Снимок экрана через Accessibility (требует включения сервиса).

    Возвращает base64-PNG. Если запрошен analyze=true, дополнительно
    отправляет картинку в vision_analyze для описания.
    """
    raw = await _call_phone("screenshot", {}, timeout=20)
    try:
        result = json.loads(raw)
    except Exception:
        return raw

    if not result.get("ok"):
        return raw

    # Сохранить скриншот в Галерею телефона, если попросили
    if args.get("to_gallery"):
        image_b64 = result.get("image")
        if image_b64:
            import time as _time
            fname = f"screenshot_{int(_time.time())}.png"
            save_res = await _call_phone("save_to_gallery", {
                "filename": fname,
                "content": image_b64,
            }, timeout=30)
            try:
                result["gallery"] = json.loads(save_res)
            except Exception:
                result["gallery"] = save_res

    if not args.get("analyze"):
        result.pop("image", None)  # не тащим огромный base64 в ответ LLM
        return json.dumps(result, ensure_ascii=False)

    # Vision-анализ скриншота
    image_b64 = result.get("image")
    if not image_b64:
        return raw
    try:
        # Сохраняем в temp файл и зовём vision_analyze
        import base64 as _b64
        import os
        import tempfile
        fd, tmp_path = tempfile.mkstemp(suffix=".png", prefix="hermes_screenshot_")
        os.close(fd)
        with open(tmp_path, "wb") as f:
            f.write(_b64.b64decode(image_b64))
        try:
            # Не передаём весь base64 обратно в результат — это огромно
            result.pop("image", None)
            result["screenshot_path"] = tmp_path
            from tools.vision_tools import _handle_vision_analyze
            vision_awaitable = _handle_vision_analyze(
                {
                    "image_url": tmp_path,
                    "question": args.get("prompt") or "Опиши что на этом скриншоте.",
                }
            )
            vision_result = await vision_awaitable
            result["analysis"] = vision_result
        except Exception as e:
            result["analysis_error"] = str(e)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"screenshot_analyze_failed: {e}"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

OPEN_APP_SCHEMA = {
    "name": "android_open_app",
    "description": "Open an app on the user's Android phone by name (e.g. 'Telegram', 'YouTube', 'Карты').",
    "parameters": {
        "type": "object",
        "properties": {
            "app": {"type": "string", "description": "App name in Russian or English. E.g. 'телеграм', 'youtube', 'спотифай'."}
        },
        "required": ["app"],
    },
}

CALL_SCHEMA = {
    "name": "android_call",
    "description": "Open the Android dialer with a phone number prefilled. The user must tap CALL on their phone to actually dial — Android does not allow making calls without confirmation.",
    "parameters": {
        "type": "object",
        "properties": {
            "number": {"type": "string", "description": "Phone number including country code, e.g. '+79991234567'."}
        },
        "required": ["number"],
    },
}

SEND_SMS_SCHEMA = {
    "name": "android_send_sms",
    "description": "Open the SMS app with a recipient and pre-filled text. User must tap SEND.",
    "parameters": {
        "type": "object",
        "properties": {
            "number": {"type": "string"},
            "text": {"type": "string"},
        },
        "required": ["number", "text"],
    },
}

SET_ALARM_SCHEMA = {
    "name": "android_set_alarm",
    "description": "Set an alarm on the user's Android phone for a specific time of day.",
    "parameters": {
        "type": "object",
        "properties": {
            "hour": {"type": "integer", "description": "Hour 0-23"},
            "minute": {"type": "integer", "description": "Minute 0-59, default 0"},
            "label": {"type": "string", "description": "Optional alarm label"},
        },
        "required": ["hour"],
    },
}

SET_TIMER_SCHEMA = {
    "name": "android_set_timer",
    "description": "Start a countdown timer on the user's Android phone.",
    "parameters": {
        "type": "object",
        "properties": {
            "seconds": {"type": "integer", "description": "Duration in seconds"},
        },
        "required": ["seconds"],
    },
}

NAVIGATE_SCHEMA = {
    "name": "android_navigate",
    "description": "Open Google Maps with turn-by-turn navigation to the given destination.",
    "parameters": {
        "type": "object",
        "properties": {
            "destination": {"type": "string", "description": "Address or place name."},
        },
        "required": ["destination"],
    },
}

WEB_SEARCH_SCHEMA = {
    "name": "android_web_search",
    "description": "Open a web search in the user's default browser on the phone.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
        },
        "required": ["query"],
    },
}

VOLUME_SCHEMA = {
    "name": "android_volume",
    "description": "Adjust phone media volume.",
    "parameters": {
        "type": "object",
        "properties": {
            "level": {"description": "Integer 0-100 (percent), or 'max', 'mute', 'up', 'down'."},
        },
        "required": ["level"],
    },
}

BRIGHTNESS_SCHEMA = {
    "name": "android_brightness",
    "description": "Adjust phone screen brightness. Requires WRITE_SETTINGS permission granted on the phone.",
    "parameters": {
        "type": "object",
        "properties": {
            "level": {"description": "Integer 0-100, or 'max', 'min', 'up', 'down'."},
        },
        "required": ["level"],
    },
}

TAP_SCHEMA = {
    "name": "android_tap",
    "description": "Tap on a UI element on the phone screen. Requires AccessibilityService enabled. Provide either visible text, content-description, or absolute coordinates.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Visible button/label text to tap on."},
            "desc": {"type": "string", "description": "Content-description (accessibility label)."},
            "x": {"type": "integer", "description": "Absolute X coordinate (px)."},
            "y": {"type": "integer", "description": "Absolute Y coordinate (px)."},
        },
    },
}

TYPE_TEXT_SCHEMA = {
    "name": "android_type_text",
    "description": "Type text into the currently focused input field. Requires AccessibilityService.",
    "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
}

SWIPE_SCHEMA = {
    "name": "android_swipe",
    "description": "Swipe the screen in a direction. Requires AccessibilityService.",
    "parameters": {
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
        },
        "required": ["direction"],
    },
}

PRESS_BACK_SCHEMA = {
    "name": "android_press_back",
    "description": "Press the Android back button. Requires AccessibilityService.",
    "parameters": {"type": "object", "properties": {}},
}

PRESS_HOME_SCHEMA = {
    "name": "android_press_home",
    "description": "Go to the Android home screen.",
    "parameters": {"type": "object", "properties": {}},
}

READ_SCREEN_SCHEMA = {
    "name": "android_read_screen",
    "description": "Return a structured snapshot of the current screen's visible UI elements (text, descriptions, bounds). Requires AccessibilityService. Use this to see what's on screen before tapping.",
    "parameters": {"type": "object", "properties": {}},
}

STATUS_SCHEMA = {
    "name": "android_status",
    "description": "Check whether a phone is currently connected to Hermes, AccessibilityService state, and all-files filesystem access.",
    "parameters": {"type": "object", "properties": {}},
}

# ---- File operation schemas ----------------------------------------------

FILE_LIST_SCHEMA = {
    "name": "android_file_list",
    "description": (
        "List files in a folder on the Android phone. "
        "Without 'path' or with path='.' — returns available roots "
        "(Downloads, Documents, Pictures, Music, Movies, DCIM by default; "
        "or full /storage if user granted MANAGE_EXTERNAL_STORAGE). "
        "Supports recursive listing and regex pattern matching on filenames. "
        "Capped at 500 entries per call."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path or relative (e.g. 'Download/notes/'). Empty/'.' lists roots."},
            "recursive": {"type": "boolean", "description": "Recurse into subdirs."},
            "pattern": {"type": "string", "description": "Case-insensitive regex matched against filename."},
        },
    },
}

FILE_READ_SCHEMA = {
    "name": "android_file_read",
    "description": (
        "Read file content from the Android phone. "
        "Default encoding 'auto' returns text for text files, base64 for binary. "
        "Hard limits: 5MB text, 20MB base64. For larger files use chunked reads via byte ranges (not yet supported — read in pieces or move smaller copies)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "encoding": {"type": "string", "enum": ["auto", "text", "base64"], "description": "Default 'auto'."},
            "max_bytes": {"type": "integer", "description": "Optional cap for text reads."},
        },
        "required": ["path"],
    },
}

FILE_WRITE_SCHEMA = {
    "name": "android_file_write",
    "description": (
        "Write content to a file on the Android phone. Creates parent directories as needed. "
        "Use encoding='text' for plain text or 'base64' for binary content (decoded server-side)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Target path. Relative paths default to Downloads/."},
            "content": {"type": "string"},
            "encoding": {"type": "string", "enum": ["text", "base64"]},
            "append": {"type": "boolean", "description": "Append instead of overwrite. Default false."},
        },
        "required": ["path", "content"],
    },
}

PUSH_FILE_SCHEMA = {
    "name": "android_push_file",
    "description": (
        "Скинуть файл С СЕРВЕРА на телефон пользователя. Используй когда юзер "
        "говорит «скинь мне на телефон», «отправь файл», «загрузи в галерею». "
        "Берёт файл по пути на сервере (результат gemini_code/кодера, скачанный "
        "файл, скриншот и т.п.) и кладёт на телефон. Работает с большими файлами "
        "(до 50MB). По умолчанию в Downloads/; для фото/видео ставь to_gallery=true "
        "чтобы появилось в Галерее."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "server_path": {"type": "string", "description": "Абсолютный путь к файлу НА СЕРВЕРЕ."},
            "filename": {"type": "string", "description": "Имя файла на телефоне (по умолчанию — как на сервере)."},
            "phone_path": {"type": "string", "description": "Целевой путь на телефоне (отн. = Downloads/). Игнорируется если to_gallery."},
            "to_gallery": {"type": "boolean", "description": "true для фото/видео → в Галерею. Default false (Downloads)."},
        },
        "required": ["server_path"],
    },
}

FILE_DELETE_SCHEMA = {
    "name": "android_file_delete",
    "description": "Delete a file or (with recursive=true) a directory on the phone. Be cautious — no undo.",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "recursive": {"type": "boolean"},
        },
        "required": ["path"],
    },
}

FILE_MOVE_SCHEMA = {
    "name": "android_file_move",
    "description": "Move or rename a file/directory on the phone.",
    "parameters": {
        "type": "object",
        "properties": {
            "src": {"type": "string"},
            "dst": {"type": "string"},
            "overwrite": {"type": "boolean"},
        },
        "required": ["src", "dst"],
    },
}

FILE_INFO_SCHEMA = {
    "name": "android_file_info",
    "description": "Get size, type, mtime and permissions for a file or directory on the phone.",
    "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    },
}

CLIPBOARD_GET_SCHEMA = {
    "name": "android_clipboard_get",
    "description": "Read the current text from the phone's clipboard. May fail on Android 10+ if the Hermes app is not in the foreground (system restriction).",
    "parameters": {"type": "object", "properties": {}},
}

CLIPBOARD_SET_SCHEMA = {
    "name": "android_clipboard_set",
    "description": "Copy text to the phone's clipboard so the user can paste it anywhere.",
    "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
}

TORCH_SCHEMA = {
    "name": "android_torch",
    "description": "Turn the phone's flashlight on or off. Omit 'on' to toggle.",
    "parameters": {
        "type": "object",
        "properties": {"on": {"type": "boolean"}},
    },
}

BATTERY_SCHEMA = {
    "name": "android_battery",
    "description": "Get current battery level, charging status, and time-to-full estimate.",
    "parameters": {"type": "object", "properties": {}},
}

NETWORK_SCHEMA = {
    "name": "android_network",
    "description": "Get current network state: WiFi/cellular/ethernet, connection quality, WiFi SSID and signal.",
    "parameters": {"type": "object", "properties": {}},
}

CAMERA_PHOTO_SCHEMA = {
    "name": "android_camera_photo",
    "description": "Open the camera app for the user to take a photo. The photo will be saved to Pictures/Hermes/. Set front=true for selfie camera.",
    "parameters": {
        "type": "object",
        "properties": {"front": {"type": "boolean"}},
    },
}

CALENDAR_LIST_CALENDARS_SCHEMA = {
    "name": "android_calendar_list_calendars",
    "description": (
        "List all calendar accounts available on the user's phone (Google, Samsung, Outlook, local). "
        "Returns id, display_name, account_name, owner_account, access_level, is_primary. "
        "Useful when the user has multiple calendars and you need to pick the right calendar_id "
        "for android_calendar_create_event."
    ),
    "parameters": {"type": "object", "properties": {}},
}

CALENDAR_LIST_EVENTS_SCHEMA = {
    "name": "android_calendar_list_events",
    "description": (
        "List events from the user's phone calendars between two ISO-8601 timestamps. "
        "Use this when the user asks: 'что у меня на сегодня/завтра/неделю', "
        "'какие встречи', 'что запланировано'. "
        "If 'from' is omitted, defaults to now. If 'to' is omitted, defaults to 7 days from 'from'. "
        "Returns events with id, title, description, location, start_iso, end_iso, all_day."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "from": {"type": "string", "description": "ISO-8601 start, e.g. '2026-05-28T00:00:00+03:00'. Default: now."},
            "to": {"type": "string", "description": "ISO-8601 end. Default: from + 7 days."},
            "max": {"type": "integer", "description": "Max events to return. Default 50."},
        },
    },
}

CALENDAR_CREATE_EVENT_SCHEMA = {
    "name": "android_calendar_create_event",
    "description": (
        "Create an event in the user's phone calendar. "
        "USE THIS for any 'поставь встречу / заведи событие / запиши на завтра / напомни в календаре' request. "
        "Writes directly to the phone's system calendar via CalendarContract — visible in Google/Samsung/Outlook calendar apps. "
        "Default duration is 1 hour if 'end' is omitted. "
        "If reminder_minutes is set, schedules a system alert that many minutes before start."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event title (mandatory)."},
            "start": {"type": "string", "description": "ISO-8601 start time. E.g. '2026-05-29T15:00:00+03:00'."},
            "end": {"type": "string", "description": "ISO-8601 end. Optional — defaults to start + 1h."},
            "description": {"type": "string"},
            "location": {"type": "string"},
            "reminder_minutes": {"type": "integer", "description": "Minutes before event to alert (e.g. 15)."},
            "calendar_id": {"type": "integer", "description": "Specific calendar to use. Default: primary writable calendar."},
        },
        "required": ["title", "start"],
    },
}

CALENDAR_UPDATE_EVENT_SCHEMA = {
    "name": "android_calendar_update_event",
    "description": (
        "Update an existing calendar event by id. "
        "Use after android_calendar_list_events to find the event_id. "
        "Only provided fields are changed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "event_id": {"type": "integer"},
            "title": {"type": "string"},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "description": {"type": "string"},
            "location": {"type": "string"},
        },
        "required": ["event_id"],
    },
}

CALENDAR_DELETE_EVENT_SCHEMA = {
    "name": "android_calendar_delete_event",
    "description": "Delete a calendar event by id. Find the id first via android_calendar_list_events.",
    "parameters": {
        "type": "object",
        "properties": {"event_id": {"type": "integer"}},
        "required": ["event_id"],
    },
}

CALENDAR_CHECK_PERMISSIONS_SCHEMA = {
    "name": "android_calendar_check_permissions",
    "description": (
        "Check whether the Hermes app has READ_CALENDAR and WRITE_CALENDAR permissions on the phone. "
        "If not, the user must grant them in Hermes Settings → 'Разрешить доступ к календарю'. "
        "Call this before calendar_list/create/delete if you get a 'calendar_permission_missing' error."
    ),
    "parameters": {"type": "object", "properties": {}},
}

SCREENSHOT_SCHEMA = {
    "name": "android_screenshot",
    "description": "Capture a screenshot of the phone's current screen (requires AccessibilityService enabled). Set to_gallery=true to save it into the phone's Gallery (Photos). Optionally analyze the image with vision LLM by setting analyze=true.",
    "parameters": {
        "type": "object",
        "properties": {
            "to_gallery": {"type": "boolean", "description": "Сохранить скриншот в Галерею телефона (появится в Фото). Используй когда юзер просит «сохрани скрин» / «в галерею»."},
            "analyze": {"type": "boolean", "description": "If true, also describe the screenshot via vision LLM."},
            "prompt": {"type": "string", "description": "Custom vision prompt. Default: 'Describe what's on this screenshot.'"},
        },
    },
}

REQUEST_ALL_FILES_SCHEMA = {
    "name": "android_request_all_files_access",
    "description": (
        "Open the Android system settings page where the user can grant 'All files access' "
        "(MANAGE_EXTERNAL_STORAGE) for Hermes. Use this when the user asks to read/write files "
        "outside the standard public folders and android_status shows all_files_access=false."
    ),
    "parameters": {"type": "object", "properties": {}},
}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

from tools.registry import registry  # noqa: E402

# Регистрируем каждый tool отдельно — discover_builtin_tools (AST-сканер)
# распознаёт только top-level вызовы registry.register, не цикл for.

registry.register(name="android_open_app", toolset="android", schema=OPEN_APP_SCHEMA,
                  handler=_handle_open_app, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_call", toolset="android", schema=CALL_SCHEMA,
                  handler=_handle_call, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_send_sms", toolset="android", schema=SEND_SMS_SCHEMA,
                  handler=_handle_send_sms, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_set_alarm", toolset="android", schema=SET_ALARM_SCHEMA,
                  handler=_handle_set_alarm, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_set_timer", toolset="android", schema=SET_TIMER_SCHEMA,
                  handler=_handle_set_timer, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_navigate", toolset="android", schema=NAVIGATE_SCHEMA,
                  handler=_handle_navigate, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_web_search", toolset="android", schema=WEB_SEARCH_SCHEMA,
                  handler=_handle_web_search, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_volume", toolset="android", schema=VOLUME_SCHEMA,
                  handler=_handle_volume, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_brightness", toolset="android", schema=BRIGHTNESS_SCHEMA,
                  handler=_handle_brightness, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_tap", toolset="android", schema=TAP_SCHEMA,
                  handler=_handle_tap, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_type_text", toolset="android", schema=TYPE_TEXT_SCHEMA,
                  handler=_handle_type_text, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_swipe", toolset="android", schema=SWIPE_SCHEMA,
                  handler=_handle_swipe, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_press_back", toolset="android", schema=PRESS_BACK_SCHEMA,
                  handler=_handle_press_back, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_press_home", toolset="android", schema=PRESS_HOME_SCHEMA,
                  handler=_handle_press_home, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_read_screen", toolset="android", schema=READ_SCREEN_SCHEMA,
                  handler=_handle_read_screen, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_status", toolset="android", schema=STATUS_SCHEMA,
                  handler=_handle_status, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_file_list", toolset="android", schema=FILE_LIST_SCHEMA,
                  handler=_handle_file_list, check_fn=_check_phone_connected,
                  is_async=True, emoji="📁")
registry.register(name="android_file_read", toolset="android", schema=FILE_READ_SCHEMA,
                  handler=_handle_file_read, check_fn=_check_phone_connected,
                  is_async=True, emoji="📄")
registry.register(name="android_push_file", toolset="android", schema=PUSH_FILE_SCHEMA,
                  handler=_handle_push_file, check_fn=_check_phone_connected,
                  is_async=True, emoji="📱")
registry.register(name="android_file_write", toolset="android", schema=FILE_WRITE_SCHEMA,
                  handler=_handle_file_write, check_fn=_check_phone_connected,
                  is_async=True, emoji="📝")
registry.register(name="android_file_delete", toolset="android", schema=FILE_DELETE_SCHEMA,
                  handler=_handle_file_delete, check_fn=_check_phone_connected,
                  is_async=True, emoji="🗑")
registry.register(name="android_file_move", toolset="android", schema=FILE_MOVE_SCHEMA,
                  handler=_handle_file_move, check_fn=_check_phone_connected,
                  is_async=True, emoji="📁")
registry.register(name="android_file_info", toolset="android", schema=FILE_INFO_SCHEMA,
                  handler=_handle_file_info, check_fn=_check_phone_connected,
                  is_async=True, emoji="ℹ")
registry.register(name="android_request_all_files_access", toolset="android",
                  schema=REQUEST_ALL_FILES_SCHEMA,
                  handler=_handle_request_all_files_access,
                  check_fn=_check_phone_connected,
                  is_async=True, emoji="🔓")
registry.register(name="android_clipboard_get", toolset="android",
                  schema=CLIPBOARD_GET_SCHEMA, handler=_handle_clipboard_get,
                  check_fn=_check_phone_connected, is_async=True, emoji="📋")
registry.register(name="android_clipboard_set", toolset="android",
                  schema=CLIPBOARD_SET_SCHEMA, handler=_handle_clipboard_set,
                  check_fn=_check_phone_connected, is_async=True, emoji="📋")
registry.register(name="android_torch", toolset="android",
                  schema=TORCH_SCHEMA, handler=_handle_torch,
                  check_fn=_check_phone_connected, is_async=True, emoji="🔦")
registry.register(name="android_battery", toolset="android",
                  schema=BATTERY_SCHEMA, handler=_handle_battery,
                  check_fn=_check_phone_connected, is_async=True, emoji="🔋")
registry.register(name="android_network", toolset="android",
                  schema=NETWORK_SCHEMA, handler=_handle_network,
                  check_fn=_check_phone_connected, is_async=True, emoji="📶")
registry.register(name="android_camera_photo", toolset="android",
                  schema=CAMERA_PHOTO_SCHEMA, handler=_handle_camera_photo,
                  check_fn=_check_phone_connected, is_async=True, emoji="📷")
registry.register(name="android_screenshot", toolset="android",
                  schema=SCREENSHOT_SCHEMA, handler=_handle_screenshot,
                  check_fn=_check_phone_connected, is_async=True, emoji="🖼")
registry.register(name="android_calendar_list_calendars", toolset="android",
                  schema=CALENDAR_LIST_CALENDARS_SCHEMA,
                  handler=_handle_calendar_list_calendars,
                  check_fn=_check_phone_connected, is_async=True, emoji="📅")
registry.register(name="android_calendar_list_events", toolset="android",
                  schema=CALENDAR_LIST_EVENTS_SCHEMA,
                  handler=_handle_calendar_list_events,
                  check_fn=_check_phone_connected, is_async=True, emoji="📅")
registry.register(name="android_calendar_create_event", toolset="android",
                  schema=CALENDAR_CREATE_EVENT_SCHEMA,
                  handler=_handle_calendar_create_event,
                  check_fn=_check_phone_connected, is_async=True, emoji="📅")
registry.register(name="android_calendar_update_event", toolset="android",
                  schema=CALENDAR_UPDATE_EVENT_SCHEMA,
                  handler=_handle_calendar_update_event,
                  check_fn=_check_phone_connected, is_async=True, emoji="📅")
registry.register(name="android_calendar_delete_event", toolset="android",
                  schema=CALENDAR_DELETE_EVENT_SCHEMA,
                  handler=_handle_calendar_delete_event,
                  check_fn=_check_phone_connected, is_async=True, emoji="📅")
registry.register(name="android_calendar_check_permissions", toolset="android",
                  schema=CALENDAR_CHECK_PERMISSIONS_SCHEMA,
                  handler=_handle_calendar_check_permissions,
                  check_fn=_check_phone_connected, is_async=True, emoji="📅")
