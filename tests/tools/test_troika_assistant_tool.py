"""Authenticated persistent assistant tool checks."""

import json
from datetime import datetime, timedelta, timezone

from gateway.session_context import clear_session_override, set_session_override
from tools import troika_assistant_tool
from troika_product.access import AccessRegistry
from troika_product.notifications import NotificationPreferences
from troika_product.proactive import ProactiveStore


def _overrides(database, principal):
    return {
        "TROIKA_PRODUCT_MODE": "1",
        "TROIKA_PRODUCT_USER_ID": principal.user_id,
        "TROIKA_PRODUCT_DEVICE_ID": principal.device_id,
        "TROIKA_PRODUCT_TOKEN_ID": principal.token_id,
        "TROIKA_PRODUCT_ACCESS_DB": str(database),
    }


def test_tool_requires_server_derived_product_identity():
    payload = json.loads(troika_assistant_tool._handle({"action": "project_list"}))
    assert payload == {"ok": False, "error": "product_identity_required"}


def test_tool_persists_project_note_and_task(tmp_path):
    database = tmp_path / "access.db"
    registry = AccessRegistry(database)
    user_id = registry.create_user("owner@example.com")
    token = registry.issue_device_token(
        registry.create_device(user_id, name="Phone", platform="android")
    )
    principal = registry.authenticate(token)
    assert principal is not None
    overrides = _overrides(database, principal)
    try:
        for name, value in overrides.items():
            set_session_override(name, value)
        project = json.loads(
            troika_assistant_tool._handle(
                {"action": "project_create", "name": "Запуск", "summary": "Beta"}
            )
        )["result"]
        note = json.loads(
            troika_assistant_tool._handle(
                {
                    "action": "note_add",
                    "content": "Не включать пустые приветствия",
                    "note_kind": "decision",
                    "idempotency_key": "decision-no-greetings",
                }
            )
        )
        task = json.loads(
            troika_assistant_tool._handle(
                {
                    "action": "task_add",
                    "title": "Проверить полезное напоминание",
                    "due_at": "2026-09-12T10:00:00+03:00",
                    "idempotency_key": "task-useful-reminder",
                }
            )
        )
    finally:
        for name in reversed(overrides):
            clear_session_override(name)

    assert project["is_active"] is True
    assert note["ok"] is True
    assert task["ok"] is True
    assert task["result"]["project_id"] == project["id"]


def test_explicit_reminder_does_not_require_proactive_opt_in(tmp_path):
    database = tmp_path / "access.db"
    registry = AccessRegistry(database)
    user_id = registry.create_user("reminders@example.com")
    token = registry.issue_device_token(
        registry.create_device(user_id, name="Phone", platform="android")
    )
    principal = registry.authenticate(token)
    assert principal is not None
    registry.set_notification_preferences(
        principal,
        NotificationPreferences(reminders_enabled=True, proactive_enabled=False),
    )
    store = ProactiveStore(database)
    due_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    overrides = _overrides(database, principal)
    try:
        for name, value in overrides.items():
            set_session_override(name, value)
        result = json.loads(
            troika_assistant_tool._handle(
                {
                    "action": "reminder_schedule",
                    "title": "Проверить сборку",
                    "due_at": due_at.isoformat(),
                    "idempotency_key": "explicit-build-reminder",
                }
            )
        )
    finally:
        for name in reversed(overrides):
            clear_session_override(name)

    assert result["ok"] is True
    assert result["result"]["kind"] == "reminder"
    assert result["result"]["delivery_enabled"] is True
    delivered = store.list_inbox(principal, now=due_at)
    assert len(delivered) == 1
    assert delivered[0].kind == "reminder"
    assert delivered[0].title == "Проверить сборку"


def test_memory_tool_uses_only_server_derived_owner(tmp_path):
    database = tmp_path / "access.db"
    registry = AccessRegistry(database)
    first_user = registry.create_user("one@example.com")
    second_user = registry.create_user("two@example.com")
    first = registry.authenticate(
        registry.issue_device_token(
            registry.create_device(first_user, name="First", platform="android")
        )
    )
    second = registry.authenticate(
        registry.issue_device_token(
            registry.create_device(second_user, name="Second", platform="android")
        )
    )
    assert first is not None and second is not None

    first_overrides = _overrides(database, first)
    try:
        for name, value in first_overrides.items():
            set_session_override(name, value)
        created = json.loads(
            troika_assistant_tool._handle(
                {
                    "action": "memory_add",
                    "memory_kind": "preference",
                    "title": "Формат",
                    "content": "Предпочитаю краткие ответы.",
                    "idempotency_key": "memory-format-v1",
                }
            )
        )["result"]
    finally:
        for name in reversed(first_overrides):
            clear_session_override(name)

    second_overrides = _overrides(database, second)
    try:
        for name, value in second_overrides.items():
            set_session_override(name, value)
        listed = json.loads(
            troika_assistant_tool._handle({"action": "memory_list"})
        )
        denied = json.loads(
            troika_assistant_tool._handle(
                {
                    "action": "memory_update",
                    "memory_id": created["id"],
                    "content": "Чужая правка",
                }
            )
        )
    finally:
        for name in reversed(second_overrides):
            clear_session_override(name)

    assert listed == {"ok": True, "result": []}
    assert denied["ok"] is False
    assert denied["error"] == "not_found"
