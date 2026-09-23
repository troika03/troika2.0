"""Persistent project and reminder tool for authenticated Troika users."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gateway.session_context import get_session_env
from tools.registry import registry
from troika_product.access import AccessPrincipal
from troika_product.memory import MemoryStore
from troika_product.proactive import ProactiveStore


def _identity_and_stores(
) -> tuple[AccessPrincipal, ProactiveStore, MemoryStore] | None:
    if get_session_env("TROIKA_PRODUCT_MODE", "") != "1":
        return None
    values = [
        get_session_env("TROIKA_PRODUCT_USER_ID", ""),
        get_session_env("TROIKA_PRODUCT_DEVICE_ID", ""),
        get_session_env("TROIKA_PRODUCT_TOKEN_ID", ""),
        get_session_env("TROIKA_PRODUCT_ACCESS_DB", ""),
    ]
    if not all(values):
        return None
    database_path = Path(values[3])
    return (
        AccessPrincipal(*values[:3]),
        ProactiveStore(database_path),
        MemoryStore(database_path),
    )


def _handle(args: dict[str, Any], **_: Any) -> str:
    resolved = _identity_and_stores()
    if resolved is None:
        return json.dumps({"ok": False, "error": "product_identity_required"})
    principal, store, memory_store = resolved
    action = str(args.get("action") or "").strip()
    try:
        if action == "project_create":
            result: object = store.create_project(
                principal, name=args.get("name"), summary=args.get("summary", ""),
            ).to_dict()
        elif action == "project_list":
            result = [item.to_dict() for item in store.list_projects(principal)]
        elif action == "project_activate":
            result = store.set_active_project(principal, args.get("project_id")).to_dict()
        elif action == "note_add":
            result = store.add_note(
                principal,
                project_id=args.get("project_id"),
                kind=args.get("note_kind", "context"),
                content=args.get("content"),
                idempotency_key=args.get("idempotency_key"),
            )
        elif action == "note_list":
            result = store.list_notes(principal, project_id=args.get("project_id"))
        elif action == "task_add":
            result = store.create_task(
                principal,
                project_id=args.get("project_id"),
                title=args.get("title"),
                details=args.get("details", ""),
                due_at=args.get("due_at"),
                action_mode=args.get("action_mode", "remind"),
                action_summary=args.get("action_summary", ""),
                idempotency_key=args.get("idempotency_key"),
            ).to_dict()
        elif action == "task_list":
            result = [
                item.to_dict()
                for item in store.list_tasks(
                    principal,
                    project_id=args.get("project_id"),
                    include_closed=args.get("include_closed", False),
                )
            ]
        elif action == "task_update":
            result = store.update_task(
                principal, args.get("task_id"), status=args.get("status")
            ).to_dict()
        elif action == "memory_add":
            result = memory_store.create_memory(
                principal,
                kind=args.get("memory_kind", "fact"),
                title=args.get("title"),
                content=args.get("content"),
                idempotency_key=args.get("idempotency_key"),
            ).to_dict()
        elif action == "memory_list":
            result = [
                item.to_dict() for item in memory_store.list_memories(principal)
            ]
        elif action == "memory_update":
            changes = {
                key: args[key]
                for key in ("title", "content")
                if key in args
            }
            if "memory_kind" in args:
                changes["kind"] = args["memory_kind"]
            result = memory_store.update_memory(
                principal, args.get("memory_id"), **changes
            ).to_dict()
        elif action == "memory_delete":
            item = memory_store.delete_memory(principal, args.get("memory_id"))
            result = {"deleted": True, "memory_id": item.id}
        elif action == "reminder_schedule":
            if not args.get("due_at"):
                raise ValueError("reminder_schedule requires due_at")
            title = args.get("title")
            message_id = store.enqueue_message(
                principal,
                kind="reminder",
                category="reminder",
                title=title,
                body=args.get("body") or f"Напоминание: {title}.",
                reason=args.get("reason") or "Пользователь явно попросил это напоминание.",
                project_id=args.get("project_id"),
                task_id=args.get("task_id"),
                available_at=args.get("due_at"),
                requires_approval=False,
                idempotency_key=args.get("idempotency_key"),
            )
            result = {
                "message_id": message_id,
                "kind": "reminder",
                "title": title,
                "delivery_enabled": store.notification_preferences(
                    principal
                ).reminders_enabled,
            }
        elif action == "follow_up_schedule":
            message_id = store.enqueue_message(
                principal,
                kind="proactive",
                category=args.get("category"),
                title=args.get("title"),
                body=args.get("body"),
                reason=args.get("reason"),
                project_id=args.get("project_id"),
                task_id=args.get("task_id"),
                available_at=args.get("due_at"),
                requires_approval=args.get("requires_approval", False),
                idempotency_key=args.get("idempotency_key"),
            )
            result = {"message_id": message_id}
        else:
            return json.dumps({"ok": False, "error": "unsupported_action"})
    except PermissionError as exc:
        return json.dumps({"ok": False, "error": "permission_denied", "message": str(exc)})
    except LookupError as exc:
        return json.dumps({"ok": False, "error": "not_found", "message": str(exc)})
    except ValueError as exc:
        return json.dumps({"ok": False, "error": "invalid_request", "message": str(exc)})
    payload = {"ok": True, "result": result}
    if action in {
        "project_create", "project_activate", "note_add", "task_add",
        "task_update", "memory_add", "memory_update", "memory_delete",
        "reminder_schedule", "follow_up_schedule",
    }:
        payload["action"] = action
    return json.dumps(payload, ensure_ascii=False)


SCHEMA = {
    "name": "troika_assistant",
    "description": (
        "Persist the user's private memory, projects, notes, tasks, reminders, and concrete follow-ups. "
        "Use when the user says to remember something for a project, add work, or remind later. "
        "Use memory_add for a durable personal fact, preference, or communication rule only when "
        "the user explicitly asks to remember it or clearly confirms it. Use memory_update or "
        "memory_delete only for an explicit change to an existing memory. Never store passwords, "
        "access tokens, payment credentials, or authentication secrets. "
        "Use reminder_schedule only for a reminder explicitly requested by the user. Use "
        "follow_up_schedule only for a concrete project follow-up allowed by proactive opt-in. "
        "If reminder_schedule returns delivery_enabled=false, tell the user to enable reminders. "
        "Never schedule greetings or generic check-ins. Future external actions are proposals only; "
        "execute them later through the relevant tool and its separate approval."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "project_create", "project_list", "project_activate",
                    "note_add", "note_list", "task_add", "task_list",
                    "task_update", "memory_add", "memory_list", "memory_update",
                    "memory_delete", "reminder_schedule", "follow_up_schedule",
                ],
            },
            "project_id": {"type": "string", "description": "Omit to use active project."},
            "name": {"type": "string"},
            "summary": {"type": "string"},
            "note_kind": {"type": "string", "enum": ["idea", "decision", "context"]},
            "memory_id": {"type": "string"},
            "memory_kind": {
                "type": "string",
                "enum": ["fact", "preference", "instruction"],
            },
            "content": {"type": "string"},
            "task_id": {"type": "string"},
            "title": {"type": "string"},
            "details": {"type": "string"},
            "status": {
                "type": "string",
                "enum": ["open", "in_progress", "blocked", "completed", "cancelled"],
            },
            "due_at": {
                "type": "string",
                "description": "RFC 3339 timestamp with time zone.",
            },
            "action_mode": {"type": "string", "enum": ["remind", "propose_action"]},
            "action_summary": {
                "type": "string",
                "description": "Concrete future action. Required for propose_action.",
            },
            "category": {
                "type": "string",
                "enum": [
                    "deadline", "project_follow_up", "blocked_task",
                    "progress_review", "decision_needed",
                ],
            },
            "body": {"type": "string"},
            "reason": {
                "type": "string",
                "description": "Concrete user-visible reason for this message.",
            },
            "requires_approval": {"type": "boolean"},
            "include_closed": {"type": "boolean"},
            "idempotency_key": {
                "type": "string",
                "description": "Stable unique key. Reuse it when retrying the same write.",
            },
        },
        "required": ["action"],
    },
}


registry.register(
    name="troika_assistant",
    toolset="troika_assistant",
    schema=SCHEMA,
    handler=_handle,
    check_fn=lambda: True,
    emoji="📌",
)
