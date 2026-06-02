"""
bg_task — голосовая обёртка над Kanban для фоновых задач Тройки.

Триггер: «Запусти research про X, через час расскажешь», «Поставь в фон
собрать материалы про Y», «Сделай это в фоне».

Поведение: создаёт kanban-задачу с дефолтным assignee и опционально
выставляет push-уведомление по завершении (через body-инструкцию для
worker'а: вызови push_to_user когда закончишь). Workflow:

  1. bg_task(title="research про X", notify=True)
     → kanban_create(assignee="researcher", body=инструкция включая
        'когда всё готово — push_to_user(text="готово: <итог>")')
  2. Worker запускается через kanban dispatcher (отдельный процесс),
     делает свою работу, в конце сам пушит результат на телефон.

Минимум зависимостей: использует hermes_cli.kanban_db напрямую (как и
kanban_create), не дублирует логику.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from tools.registry import registry

logger = logging.getLogger(__name__)


_DEFAULT_ASSIGNEE = os.getenv("TROIKA_BG_ASSIGNEE", "researcher")


def _connect():
    """Прямой коннект к kanban.db через hermes_cli.kanban_db."""
    from hermes_cli.kanban_db import KanbanDB

    kb = KanbanDB()
    return kb, kb.connect()


def _compose_body(user_brief: str, notify: bool, push_title: str) -> str:
    """Собирает тело задачи: что сделать и как отрапортовать."""
    parts = [user_brief.strip()]
    if notify:
        parts.append(
            "\n\nКОГДА ЗАКОНЧИШЬ: вызови tool `push_to_user` с коротким "
            f"итогом (1-3 предложения, готовый к озвучке) и title=\"{push_title}\". "
            "Не пиши markdown, не используй списки — это будет озвучено."
        )
    parts.append(
        "\n\nЕсли задача невыполнима — закрой через kanban_block с понятной "
        "причиной и тоже пушни Мише."
    )
    return "".join(parts)


async def _handle(args: Dict[str, Any], **_kw) -> str:
    title = (args.get("title") or "").strip()
    if not title:
        return json.dumps({"ok": False, "error": "missing 'title'"}, ensure_ascii=False)
    if len(title) > 200:
        title = title[:200]

    brief = (args.get("brief") or args.get("body") or title).strip()
    notify = bool(args.get("notify", True))
    push_title = (args.get("push_title") or "Тройка: готово").strip()[:80]
    assignee = (args.get("assignee") or _DEFAULT_ASSIGNEE).strip()

    body = _compose_body(brief, notify, push_title)

    try:
        kb, conn = _connect()
    except Exception as e:
        return json.dumps(
            {"ok": False, "error": f"kanban_unavailable: {e}",
             "hint": "Kanban db не открывается. Проверь HERMES_HOME."},
            ensure_ascii=False,
        )
    try:
        new_tid = kb.create_task(
            conn,
            title=title,
            body=body,
            assignee=assignee,
            parents=(),
            tenant=os.environ.get("HERMES_TENANT"),
            priority=int(args.get("priority", 0) or 0),
            workspace_kind="scratch",
            workspace_path=None,
            triage=False,
            idempotency_key=None,
            max_runtime_seconds=int(args["max_runtime_seconds"]) if args.get("max_runtime_seconds") else None,
            skills=None,
            initial_status="running",
            created_by=os.environ.get("HERMES_PROFILE") or "troika",
            session_id=os.environ.get("HERMES_SESSION_ID"),
        )
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return json.dumps({"ok": False, "error": f"create_failed: {e}"}, ensure_ascii=False)

    try:
        conn.close()
    except Exception:
        pass

    return json.dumps(
        {
            "ok": True,
            "task_id": new_tid,
            "assignee": assignee,
            "notify": notify,
            "say_to_user": f"Поставил в фон. Сообщу когда закончу.",
        },
        ensure_ascii=False,
    )


BG_TASK_SCHEMA = {
    "name": "bg_task",
    "description": (
        "Запустить фоновую задачу через Kanban. Используется когда Миша говорит "
        "'запусти research про X, через час расскажешь', 'поставь в фон', "
        "'сделай это пока я занят'. Worker (отдельный профиль hermes) сделает "
        "работу асинхронно и при notify=true пушнёт Мише голосом результат "
        "через push_to_user. Не использовать для быстрых задач — для них просто "
        "выполняй сразу в текущей сессии."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Короткий заголовок задачи (до 200 символов).",
            },
            "brief": {
                "type": "string",
                "description": (
                    "Что именно сделать — полная формулировка задачи для worker'а. "
                    "Если опущено, берётся title."
                ),
            },
            "assignee": {
                "type": "string",
                "description": (
                    "Имя профиля Hermes, который будет исполнять. По умолчанию "
                    f"'{_DEFAULT_ASSIGNEE}' (можно переопределить env TROIKA_BG_ASSIGNEE)."
                ),
            },
            "notify": {
                "type": "boolean",
                "description": (
                    "По умолчанию true — worker пушнёт результат на телефон через "
                    "push_to_user когда закончит. false = тихая задача без уведомления."
                ),
            },
            "push_title": {
                "type": "string",
                "description": "Заголовок push-уведомления (default 'Тройка: готово').",
            },
            "priority": {
                "type": "integer",
                "description": "Приоритет 0..N (выше → раньше в очереди dispatcher'а).",
            },
            "max_runtime_seconds": {
                "type": "integer",
                "description": "Жёсткий таймаут на исполнение, секунд.",
            },
        },
        "required": ["title"],
    },
}


registry.register(
    name="bg_task",
    toolset="bg_task",
    schema=BG_TASK_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="⏳",
)
