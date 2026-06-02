"""
Tool task_status — статус фоновых задач Тройки.

Использование:
- `task_status()` — список активных задач (queued/running).
- `task_status(task_id="abc123")` — статус конкретной задачи.
- `task_status(recent=True)` — последние 5 задач (включая done/failed).
- `task_status(cancel="abc123")` — отменить задачу.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime
from typing import Any, Dict, List

from tools import job_runner
from tools.registry import registry

logger = logging.getLogger(__name__)


def _format_age(ts: float) -> str:
    if not ts:
        return "—"
    delta = datetime.now().timestamp() - ts
    if delta < 60:
        return f"{int(delta)}с назад"
    if delta < 3600:
        return f"{int(delta / 60)} мин назад"
    return f"{int(delta / 3600)} ч назад"


def _summary(job: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "task_id": job["id"],
        "kind": job["kind"],
        "status": job["status"],
        "label": job.get("short_label") or job["kind"],
        "age": _format_age(job.get("created_at") or 0),
        "error": job.get("error"),
    }


async def _handle_impl(args: Dict[str, Any]) -> Dict[str, Any]:
    cancel_id = (args.get("cancel") or "").strip()
    if cancel_id:
        ok = job_runner.cancel(cancel_id)
        return {"ok": ok, "task_id": cancel_id,
                "say_to_user": "Отменил." if ok else "Не нашёл активную задачу с таким id."}

    task_id = (args.get("task_id") or "").strip()
    if task_id:
        job = job_runner.get_status(task_id)
        if not job:
            return {"ok": False, "error": "not_found",
                    "say_to_user": "Не нашёл задачу."}
        info = _summary(job)
        if job["status"] == "done":
            info["result"] = job.get("result_json")
            say = f"Задача '{info['label']}' готова."
        elif job["status"] == "failed":
            say = f"Задача '{info['label']}' упала: {job.get('error') or '...'}."
        elif job["status"] == "running":
            say = f"Работаю над '{info['label']}', началась {info['age']}."
        else:
            say = f"Задача '{info['label']}' в очереди."
        return {"ok": True, **info, "say_to_user": say}

    if args.get("recent"):
        items = [_summary(j) for j in job_runner.list_recent(limit=5)]
        if not items:
            return {"ok": True, "items": [], "say_to_user": "Недавних задач нет."}
        return {"ok": True, "items": items,
                "say_to_user": f"Последние задачи: {len(items)} шт."}

    # default: active list
    items = [_summary(j) for j in job_runner.list_active()]
    if not items:
        return {"ok": True, "items": [], "say_to_user": "Сейчас в фоне ничего нет."}
    say_parts = []
    for it in items:
        verb = "делаю" if it["status"] == "running" else "в очереди"
        say_parts.append(f"{it['label']} — {verb}")
    return {"ok": True, "items": items,
            "say_to_user": "В работе: " + "; ".join(say_parts) + "."}


async def _handle(args: Dict[str, Any], **_kw) -> str:
    try:
        result = await _handle_impl(args)
    except Exception as e:
        logger.exception("task_status crashed")
        result = {"ok": False, "error": str(e), "say_to_user": "Ошибка статуса задач."}
    return json.dumps(result, ensure_ascii=False)


SCHEMA = {
    "name": "task_status",
    "description": (
        "Узнать статус фоновых задач Тройки (gemini_code и др., работающих параллельно). "
        "Без аргументов — список активных. С task_id — конкретная задача. "
        "С recent=true — последние 5 (включая завершённые). С cancel=<id> — отмена."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "ID конкретной задачи."},
            "recent": {"type": "boolean", "description": "Показать последние задачи (вкл. завершённые)."},
            "cancel": {"type": "string", "description": "ID задачи для отмены."},
        },
    },
}


registry.register(
    name="task_status",
    toolset="gemini_code",  # включён в тот же toolset
    schema=SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="⏳",
)
