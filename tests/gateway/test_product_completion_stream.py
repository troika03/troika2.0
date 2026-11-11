"""Unverified completion claims never reach product text/voice consumers."""

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["chat", "runs"])
async def test_product_stream_withholds_unverified_model_text(tmp_path, monkeypatch, endpoint):
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True, "product_auth_db": str(tmp_path / "access.db"),
        "product_artifact_root": str(tmp_path / "artifacts"),
        "product_workspace_root": str(tmp_path / "workspace"), "product_quotas_enabled": False,
    }))
    registry = adapter._access_registry
    owner = registry.create_user("stream@example.com")
    token = registry.issue_device_token(registry.create_device(owner, name="Test", platform="android"))

    def create_agent(**kwargs):
        callback = kwargs["stream_delta_callback"]
        agent = MagicMock()
        agent.session_id = "test_stream"
        agent.session_prompt_tokens = agent.session_completion_tokens = agent.session_total_tokens = 0

        def conversation(**_):
            callback("Готово, я всё сделала!")
            return {"final_response": "Не удалось подтвердить выполнение просьбы.", "messages": []}

        agent.run_conversation.side_effect = conversation
        return agent

    monkeypatch.setattr(adapter, "_create_agent", create_agent)
    app = web.Application()
    app.router.add_post("/v1/chat/completions", adapter._handle_chat_completions)
    app.router.add_post("/v1/runs", adapter._handle_runs)
    app.router.add_get("/v1/runs/{run_id}/events", adapter._handle_run_events)
    async with TestClient(TestServer(app)) as client:
        headers = {"Authorization": f"Bearer {token}"}
        if endpoint == "chat":
            response = await client.post("/v1/chat/completions", headers=headers, json={
                "stream": True, "messages": [{"role": "user", "content": "Создай задачу"}],
            })
        else:
            started = await client.post("/v1/runs", headers=headers, json={"input": "Создай задачу"})
            data = await started.json()
            response = await client.get(f"/v1/runs/{data['run_id']}/events", headers=headers)
        assert response.status == 200
        text = await asyncio.wait_for(response.text(), timeout=5)
        events = [json.loads(line[6:]) for line in text.splitlines()
                  if line.startswith("data: ") and line[6:] != "[DONE]"]
        visible = "".join(
            event.get("delta", "") if endpoint == "runs"
            else event.get("choices", [{}])[0].get("delta", {}).get("content", "")
            for event in events
        )
        assert visible == "Не удалось подтвердить выполнение просьбы."
        assert "Готово, я всё сделала!" not in json.dumps(events, ensure_ascii=False)
