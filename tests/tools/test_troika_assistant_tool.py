"""Authenticated persistent assistant tool checks."""

import json

from gateway.session_context import clear_session_override, set_session_override
from tools import troika_assistant_tool
from troika_product.access import AccessRegistry


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
