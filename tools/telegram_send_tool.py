"""
telegram_send — отправка сообщения/файла Мише в его личный Telegram.

«Отправь мне в телеграм», «скинь файл в избранное», «отправь ссылку в ТГ» →
Тройка шлёт это боту в личку Миши (его chat_id). Под капотом Bot API.

Конфиг (env, лежат в ~/.troika/.env на сервере):
  TELEGRAM_BOT_TOKEN  — токен бота от @BotFather
  TELEGRAM_CHAT_ID    — личный chat_id Миши (куда слать «мне»/«в избранное»)

operations:
  text  — отправить текстовое сообщение (по умолчанию)
  file  — отправить файл/документ по пути на сервере (zip лендинга и т.п.)

Деградация:
  • нет токена/chat_id → понятная ошибка с подсказкой;
  • файла нет по пути → ошибка;
  • Telegram вернул не-200 → текст ошибки от API.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from tools.registry import registry

logger = logging.getLogger(__name__)

_API = "https://api.telegram.org"


def _token() -> Optional[str]:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip() or None


def _chat_id(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return str(explicit).strip()
    return (os.environ.get("TELEGRAM_CHAT_ID") or "").strip() or None


def _send_text(token: str, chat_id: str, text: str) -> Dict[str, Any]:
    url = f"{_API}/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "false",
    }).encode("utf-8")
    req = urllib.request.Request(url, data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("ok"):
            return {"ok": True, "sent": "text", "say_to_user": "Отправил тебе в телеграм."}
        return {"ok": False, "error": f"telegram: {body.get('description')}"}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        return {"ok": False, "error": f"http_{e.code}: {detail}"}
    except Exception as e:
        return {"ok": False, "error": f"send_failed: {e}"}


def _send_file(token: str, chat_id: str, path: Path, caption: str = "") -> Dict[str, Any]:
    """Multipart sendDocument — без внешних зависимостей."""
    url = f"{_API}/bot{token}/sendDocument"
    boundary = f"----troika{uuid.uuid4().hex}"
    filename = path.name
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"

    try:
        file_bytes = path.read_bytes()
    except Exception as e:
        return {"ok": False, "error": f"cannot_read_file: {e}"}

    # Размер: Telegram Bot API лимит на документ — 50 МБ.
    if len(file_bytes) > 50 * 1024 * 1024:
        return {"ok": False, "error": "file_too_large",
                "say_to_user": "Файл больше 50 МБ — Telegram такой не примет."}

    parts: list[bytes] = []

    def add_field(name: str, value: str) -> None:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(f"{value}\r\n".encode())

    add_field("chat_id", chat_id)
    if caption:
        add_field("caption", caption)

    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'.encode()
    )
    parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    payload = b"".join(parts)

    req = urllib.request.Request(url, data=payload)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("ok"):
            return {"ok": True, "sent": "file", "filename": filename,
                    "say_to_user": f"Отправил файл {filename} тебе в телеграм."}
        return {"ok": False, "error": f"telegram: {body.get('description')}"}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        return {"ok": False, "error": f"http_{e.code}: {detail}"}
    except Exception as e:
        return {"ok": False, "error": f"send_failed: {e}"}


async def _handle(args: Dict[str, Any], **_kw) -> str:
    token = _token()
    if not token:
        return json.dumps({
            "ok": False, "error": "no_bot_token",
            "hint": "TELEGRAM_BOT_TOKEN не задан в ~/.troika/.env.",
        }, ensure_ascii=False)

    chat_id = _chat_id(args.get("chat_id"))
    if not chat_id:
        return json.dumps({
            "ok": False, "error": "no_chat_id",
            "hint": "TELEGRAM_CHAT_ID не задан — Миша должен один раз написать боту.",
        }, ensure_ascii=False)

    op = (args.get("operation") or "").strip().lower()
    file_path = (args.get("file_path") or args.get("path") or "").strip()
    text = (args.get("text") or args.get("message") or "").strip()
    caption = (args.get("caption") or "").strip()

    # Авто-режим: если указан file_path — отправляем файл, иначе текст.
    if not op:
        op = "file" if file_path else "text"

    if op == "file":
        if not file_path:
            return json.dumps({"ok": False, "error": "missing file_path"}, ensure_ascii=False)
        p = Path(file_path)
        if not p.exists() or not p.is_file():
            return json.dumps({
                "ok": False, "error": f"file_not_found: {file_path}",
            }, ensure_ascii=False)
        res = _send_file(token, chat_id, p, caption or text)
    else:
        if not text:
            return json.dumps({"ok": False, "error": "missing text"}, ensure_ascii=False)
        res = _send_text(token, chat_id, text)

    return json.dumps(res, ensure_ascii=False)


TELEGRAM_SEND_SCHEMA = {
    "name": "telegram_send",
    "description": (
        "Отправить Мише сообщение или файл в его личный Telegram (в «Избранное»/"
        "личку с ботом). Используй когда Миша говорит «отправь мне в телеграм», "
        "«скинь файл/ссылку в ТГ», «отправь в избранное». "
        "operations: text (текст/ссылка), file (документ по пути на сервере, "
        "например готовый zip лендинга). Если указан file_path — шлёт файл."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["text", "file"],
                "description": "text — сообщение/ссылка, file — документ. Авто по file_path.",
            },
            "text": {
                "type": "string",
                "description": "Текст сообщения или ссылка (для operation=text).",
            },
            "file_path": {
                "type": "string",
                "description": "Путь к файлу на сервере (для operation=file).",
            },
            "caption": {
                "type": "string",
                "description": "Подпись к файлу (необязательно).",
            },
        },
        "required": [],
    },
}


registry.register(
    name="telegram_send",
    toolset="messaging",
    schema=TELEGRAM_SEND_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="✈️",
)
