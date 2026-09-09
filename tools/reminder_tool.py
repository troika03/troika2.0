"""
Reminder tool — голосовые напоминалки для Тройки.

Тонкий wrapper над cron-инфраструктурой: голосом сказал "напомни через
час позвонить маме" — создаётся one-shot cron job с prompt'ом который
триггерит send_message на phone в указанное время.

Под капотом — `create_job` из cron/jobs.py. Reminder = job с
`origin.source = "reminder"` чтобы их можно было фильтровать отдельно
от обычных кронов.

Поддерживает три операции:
  create — создать напоминание
  list   — показать активные
  cancel — удалить по id или последнее
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

from tools.registry import registry

logger = logging.getLogger(__name__)


_DURATION_RE = re.compile(
    r"^\s*(?:через\s+)?(\d+)\s*"
    r"(сек|секунд[уы]?|s|мин|минут[уы]?|m|час[аов]?|h|д[нея][неьйя]*|d)\s*$",
    re.IGNORECASE,
)


def _parse_when(when: str) -> str | None:
    """Конвертирует 'через 5 минут' / '14:30' / ISO в формат для parse_schedule."""
    if not when:
        return None
    w = when.strip().lower()

    m = _DURATION_RE.match(w)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit.startswith("с") or unit == "s":
            mins = max(1, round(n / 60))
            return f"{mins}m"
        if unit.startswith("мин") or unit == "m":
            return f"{n}m"
        if unit.startswith("ч") or unit == "h":
            return f"{n}h"
        if unit.startswith("д") or unit == "d":
            return f"{n}d"

    # HH:MM сегодня (или завтра если время уже прошло)
    tm = re.match(r"^(\d{1,2}):(\d{2})$", w)
    if tm:
        h, mm = int(tm.group(1)), int(tm.group(2))
        now = datetime.now()
        target = now.replace(hour=h, minute=mm, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        return target.strftime("%Y-%m-%dT%H:%M")

    if re.match(r"^\d{4}-\d{2}-\d{2}", when.strip()):
        return when.strip()

    return None


def _session_scope(args: Dict[str, Any]) -> str:
    """Return the framework-owned session scope, never a shared phone ID."""
    value = args.get("_session_id")
    return value.strip() if isinstance(value, str) else ""


async def _handle(args: Dict[str, Any], **_kw) -> str:
    from cron.jobs import list_jobs, remove_job

    op = (args.get("operation") or "create").strip().lower()
    session_id = _session_scope(args)
    if not session_id:
        return json.dumps(
            {"ok": False, "error": "session_scope_unavailable"}, ensure_ascii=False
        )

    if op == "create":
        text = (args.get("text") or "").strip()
        when = (args.get("when") or "").strip()
        if not text:
            return json.dumps({"ok": False, "error": "missing 'text'"}, ensure_ascii=False)
        if not when:
            return json.dumps({"ok": False, "error": "missing 'when'"}, ensure_ascii=False)

        schedule = _parse_when(when)
        if not schedule:
            return json.dumps(
                {"ok": False, "error": f"can_not_parse_when: {when!r}",
                 "hint": "Используй 'через N минут/часов', 'HH:MM' или ISO 'YYYY-MM-DDTHH:MM'"},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "ok": False,
                "error": "delivery_channel_not_configured",
                "text": text,
                "when": when,
                "schedule": schedule,
                "hint": (
                    "Напоминания отключены до подключения личного канала доставки "
                    "(push/in-app). Тройка не будет отправлять их в чужой или общий чат."
                ),
            },
            ensure_ascii=False,
        )

    if op == "list":
        jobs = list_jobs() or []
        reminders: List[Dict[str, Any]] = []
        for j in jobs:
            origin = j.get("origin") or {}
            if (
                origin.get("source") != "reminder"
                or origin.get("session_id") != session_id
            ):
                continue
            reminders.append({
                "id": j.get("id"),
                "text": origin.get("text") or j.get("name"),
                "next_run": j.get("next_run"),
                "state": j.get("state"),
            })
        return json.dumps(
            {"ok": True, "count": len(reminders), "reminders": reminders},
            ensure_ascii=False,
        )

    if op == "cancel":
        rid = (args.get("id") or "").strip()
        if not rid:
            jobs = list_jobs() or []
            candidates = [
                j for j in jobs
                if (j.get("origin") or {}).get("source") == "reminder"
                and (j.get("origin") or {}).get("session_id") == session_id
            ]
            if not candidates:
                return json.dumps({"ok": False, "error": "no_reminders"}, ensure_ascii=False)
            candidates.sort(key=lambda j: j.get("next_run") or "")
            rid = candidates[0].get("id")

        allowed_ids = {
            j.get("id") for j in list_jobs() or []
            if (j.get("origin") or {}).get("source") == "reminder"
            and (j.get("origin") or {}).get("session_id") == session_id
        }
        if rid not in allowed_ids:
            return json.dumps({"ok": False, "error": "reminder_not_found"}, ensure_ascii=False)
        try:
            removed = remove_job(rid)
        except Exception as e:
            return json.dumps({"ok": False, "error": f"cancel_failed: {e}"}, ensure_ascii=False)
        return json.dumps(
            {"ok": True, "action": "cancelled", "id": rid, "removed": bool(removed)},
            ensure_ascii=False,
        )

    return json.dumps({"ok": False, "error": f"unknown_operation: {op}"}, ensure_ascii=False)


REMINDER_SCHEMA = {
    "name": "reminder",
    "description": (
        "Напоминания для текущего пользователя. Телефонная доставка временно "
        "недоступна, пока не подключён личный push/in-app канал; не обещай "
        "создать напоминание до этого. Операции: create, list, cancel."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["create", "list", "cancel"],
                "description": "По умолчанию create.",
            },
            "text": {
                "type": "string",
                "description": "О чём напомнить. Например 'позвонить маме'.",
            },
            "when": {
                "type": "string",
                "description": (
                    "Когда напомнить: 'через 5 минут', 'через 2 часа', "
                    "'через час', 'через день', 'HH:MM' (сегодня или завтра), "
                    "или ISO 'YYYY-MM-DDTHH:MM'."
                ),
            },
            "id": {
                "type": "string",
                "description": "ID напоминания для cancel (опц., иначе последнее ближайшее).",
            },
        },
        "required": ["operation"],
    },
}


registry.register(
    name="reminder",
    toolset="reminder",
    schema=REMINDER_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="⏰",
)
