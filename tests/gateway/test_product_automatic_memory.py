"""Automatic memory on the text/run and background voice entry points."""

import asyncio
from unittest.mock import patch

from aiohttp import ClientSession

from tests.gateway.test_product_assistant import _adapter
from tests.gateway.test_product_auth import _ChatRequest


def test_authenticated_chat_captures_only_after_opt_in_and_scopes_context(tmp_path, monkeypatch):
    adapter = _adapter(tmp_path)
    registry = adapter._access_registry
    user = registry.create_user("first@example.com")
    token = registry.issue_device_token(registry.create_device(user, name="Phone", platform="android"))
    principal = registry.authenticate(token)
    captured = []
    async def fake_run_agent(**kwargs):
        captured.append(kwargs)
        return ({"final_response": "Хорошо", "messages": [], "session_id": "s"}, {"total_tokens": 0})
    monkeypatch.setattr(adapter, "_run_agent", fake_run_agent)

    request = _ChatRequest(token, {"messages": [{"role": "user", "content": "Я живу в Казани."}]})
    assert asyncio.run(adapter._handle_chat_completions(request)).status == 200
    assert adapter._memory_store.list_memories(principal) == []
    adapter._memory_store.set_preferences(principal, automatic_enabled=True)
    request = _ChatRequest(token, {"messages": [{"role": "user", "content": "Я живу в Казани."}]})
    assert asyncio.run(adapter._handle_chat_completions(request)).status == 200
    assert adapter._memory_store.list_memories(principal)[0].content == "Я живу в Казани."
    assert "Я живу в Казани." in captured[-1]["ephemeral_system_prompt"]
    request = _ChatRequest(token, {"messages": [{"role": "assistant", "content": "Меня зовут Ассистент."}]})
    assert asyncio.run(adapter._handle_chat_completions(request)).status == 200
    assert len(adapter._memory_store.list_memories(principal)) == 1


def test_http_preference_validation_isolation_and_revocation(tmp_path):
    async def scenario():
        adapter = _adapter(tmp_path)
        registry = adapter._access_registry
        tokens = [registry.issue_device_token(registry.create_device(
            registry.create_user(email), name="Phone", platform="android"))
            for email in ("first@example.com", "other@example.com")]
        headers = [{"Authorization": "Bearer " + token} for token in tokens]
        with patch("tools.job_runner.cleanup_orphan_jobs", return_value=0), patch("tools.job_runner.ensure_watchdog_started"):
            assert await adapter.connect()
        try:
            port = adapter._site._server.sockets[0].getsockname()[1]
            async with ClientSession(base_url=f"http://127.0.0.1:{port}") as client:
                assert (await client.get("/v1/memory-preferences")).status == 401
                original = await client.get("/v1/memory-preferences", headers=headers[0])
                assert await original.json() == {"automatic_enabled": False}
                invalid = await client.put("/v1/memory-preferences", headers=headers[0], json={"automatic_enabled": "true"})
                assert invalid.status == 400
                invalid = await client.put("/v1/memory-preferences", headers=headers[0], json={"automatic_enabled": True, "user_id": "other"})
                assert invalid.status == 400
                enabled = await client.put("/v1/memory-preferences", headers=headers[0], json={"automatic_enabled": True})
                assert enabled.status == 200
                snapshot = await client.get("/v1/memories", headers=headers[0])
                assert (await snapshot.json())["preferences"]["automatic_enabled"] is True
                other = await client.get("/v1/memory-preferences", headers=headers[1])
                assert (await other.json())["automatic_enabled"] is False
                registry.revoke_token(tokens[0])
                assert (await client.put("/v1/memory-preferences", headers=headers[0], json={"automatic_enabled": False})).status == 401
        finally:
            await adapter.disconnect()
    asyncio.run(scenario())
