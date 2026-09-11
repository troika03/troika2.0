"""HTTP API for private project, task, and inbox state."""

import asyncio
import json
from unittest.mock import patch

from aiohttp import ClientSession

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from troika_product.notifications import NotificationPreferences


def _adapter(tmp_path):
    return APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True,
        "product_auth_db": str(tmp_path / "access.db"),
        "product_artifact_root": str(tmp_path / "artifacts"),
        "host": "127.0.0.1", "port": 0,
    }))


def test_assistant_api_isolated_and_idempotent(tmp_path):
    async def scenario():
        adapter = _adapter(tmp_path)
        registry = adapter._access_registry
        first_user = registry.create_user("one@example.com")
        second_user = registry.create_user("two@example.com")
        first = registry.issue_device_token(registry.create_device(first_user, name="A", platform="android"))
        second = registry.issue_device_token(registry.create_device(second_user, name="B", platform="android"))
        with patch("tools.job_runner.cleanup_orphan_jobs", return_value=0), patch("tools.job_runner.ensure_watchdog_started"):
            assert await adapter.connect()
        try:
            port = adapter._site._server.sockets[0].getsockname()[1]
            async with ClientSession(base_url=f"http://127.0.0.1:{port}") as client:
                h1 = {"Authorization": f"Bearer {first}"}
                h2 = {"Authorization": f"Bearer {second}"}
                assert (await client.get("/v1/assistant/projects")).status == 401
                response = await client.post("/v1/assistant/projects", json={"name": "Запуск", "summary": "Beta"}, headers=h1)
                assert response.status == 201
                project = (await response.json())["project"]
                task_body = {"project_id": project["id"], "title": "Проверить сборку", "due_at": "2026-09-12T10:00:00+03:00"}
                first_task = await client.post("/v1/assistant/tasks", json=task_body, headers={**h1, "Idempotency-Key": "build-v1"})
                second_task = await client.post("/v1/assistant/tasks", json={**task_body, "title": "Другой текст"}, headers={**h1, "Idempotency-Key": "build-v1"})
                assert first_task.status == second_task.status == 201
                assert (await first_task.json())["task"]["id"] == (await second_task.json())["task"]["id"]
                assert (await (await client.get("/v1/assistant/projects", headers=h2)).json())["projects"] == []
                assert (await (await client.get("/v1/assistant/tasks", headers=h2)).json())["tasks"] == []
                adapter._access_registry.set_notification_preferences(
                    registry.authenticate(first), NotificationPreferences(reminders_enabled=True)
                )
                inbox = await client.get("/v1/assistant/inbox", headers=h1)
                assert inbox.status == 200
                messages = (await inbox.json())["messages"]
                assert len(messages) == 0
        finally:
            await adapter.disconnect()
    asyncio.run(scenario())


def test_product_context_is_added_to_run_prompt(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path)
    registry = adapter._access_registry
    user_id = registry.create_user("one@example.com")
    token = registry.issue_device_token(registry.create_device(user_id, name="A", platform="android"))
    principal = registry.authenticate(token)
    project = adapter._proactive_store.create_project(principal, name="Релиз")
    captured = {}
    async def fake_run_agent(**kwargs):
        captured.update(kwargs)
        return ({"final_response": "ok", "messages": [], "session_id": "s"}, {"total_tokens": 0})
    monkeypatch.setattr(adapter, "_run_agent", fake_run_agent)
    from tests.gateway.test_product_auth import _ChatRequest
    request = _ChatRequest(token, {"messages": [{"role": "user", "content": "что дальше"}]})
    response = asyncio.run(adapter._handle_chat_completions(request))
    assert response.status == 200
    assert "Релиз" in captured["ephemeral_system_prompt"]
