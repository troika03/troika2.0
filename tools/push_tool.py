"""
Push tool — Тройка инициативно говорит с Мишей.

Когда напоминание сработало по cron, или Тройка хочет сама что-то сказать
(финал долгой задачи, заметила интересный факт) — она вызывает push_to_user
и текст уходит через phone_bridge на Android. На телефоне action notify_user
озвучивает текст через EdgeTTS + кидает notification в шторку.

В отличие от send_message (который шлёт текст в существующий канал) этот
tool именно ИНИЦИИРУЕТ разговор — Миша мог даже не открывать Тройку.

Использование:
  push_to_user(text="Напоминаю: позвонить маме")
  push_to_user(text="Готово, отчёт собран", speak=False)  — только тихий банер
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict

from tools.registry import registry

logger = logging.getLogger(__name__)


async def _handle(args: Dict[str, Any], **_kw) -> str:
    from gateway.platforms.phone_bridge import bridge

    text = (args.get("text") or "").strip()
    if not text:
        return json.dumps({"ok": False, "error": "missing 'text'"}, ensure_ascii=False)
    if len(text) > 2000:
        text = text[:2000]

    if not bridge.is_connected():
        return json.dumps(
            {"ok": False, "error": "phone_not_connected",
             "hint": "Android-приложение Тройки не на связи — push доставить нельзя."},
            ensure_ascii=False,
        )

    speak = bool(args.get("speak", True))
    title = (args.get("title") or "Тройка").strip()[:80]

    try:
        result = await bridge.send_command(
            "notify_user",
            {"text": text, "speak": speak, "title": title},
            timeout=10.0,
        )
    except Exception as e:
        return json.dumps({"ok": False, "error": f"send_failed: {e}"}, ensure_ascii=False)

    return json.dumps(
        {"ok": bool(result.get("ok", True)), "delivered": True, "phone_result": result},
        ensure_ascii=False,
    )


PUSH_SCHEMA = {
    "name": "push_to_user",
    "description": (
        "Отправить голосовое push-уведомление Мише на телефон. "
        "Используется когда Тройке нужно ИНИЦИИРОВАТЬ разговор — напомнить "
        "о чём-то, сообщить о результате долгой задачи, заметить важный факт. "
        "По умолчанию озвучивается через TTS + показывается notification. "
        "Передавать только готовый к озвучке текст (без markdown, чистый русский)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Текст для озвучки/показа. До 2000 символов.",
            },
            "speak": {
                "type": "boolean",
                "description": "Озвучить голосом (default true). false = только тихий банер.",
            },
            "title": {
                "type": "string",
                "description": "Заголовок notification (default 'Тройка').",
            },
        },
        "required": ["text"],
    },
}


registry.register(
    name="push_to_user",
    toolset="push",
    schema=PUSH_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="📣",
)
