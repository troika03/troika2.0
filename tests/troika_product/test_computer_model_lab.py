import json
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer
import pytest

from scripts.troika_computer_lab import create_app, openrouter_planner


TOKEN = "test_computer_lab_token_for_one_process"
OBS_ID = "a" * 32
GOAL = "Запиши пробную строку и сохрани."


def payload(observation=None):
    return {"version": 1, "goal": GOAL, "observation": observation, "last_result": "start"}


@pytest.mark.asyncio
async def test_only_the_approved_fields_reach_the_model():
    seen = []

    def choose(state):
        seen.append(state)
        return {"action": "inspect"}

    async with TestClient(TestServer(create_app(TOKEN, choose))) as client:
        url = "/v1/computer-lab/next"
        assert (await client.post(url, json=payload())).status == 401
        headers = {"Authorization": "Bearer " + TOKEN}
        private = {"id": OBS_ID, "can_write": True, "can_save": False, "window_text": "private sentinel"}
        assert (await client.post(url, headers=headers, json=payload(private))).status == 400
        assert seen == []
        allowed = {"id": OBS_ID, "can_write": True, "can_save": False}
        reply = await client.post(url, headers=headers, json=payload(allowed))
        assert reply.status == 200 and await reply.json() == {"action": "inspect"}
        assert reply.headers["Cache-Control"] == "no-store"
        assert seen == [payload(allowed)]


@pytest.mark.asyncio
@pytest.mark.parametrize("command", [
    {"action": "save", "observation_id": OBS_ID},
    {"action": "write", "observation_id": "b" * 32, "text": "fixture"},
    {"action": "write", "observation_id": OBS_ID, "text": "fixture", "path": "other.txt"},
])
async def test_model_cannot_select_an_unavailable_action(command):
    async with TestClient(TestServer(create_app(TOKEN, lambda _: command))) as client:
        allowed = {"id": OBS_ID, "can_write": True, "can_save": False}
        response = await client.post("/v1/computer-lab/next", json=payload(allowed),
                                     headers={"Authorization": "Bearer " + TOKEN})
        assert response.status == 502 and await response.json() == {"error": "invalid_command"}


def test_planner_reuses_the_hermes_openrouter_client_without_tools(monkeypatch):
    from agent import auxiliary_client

    calls = []
    clients = []

    def call(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"inspect"}'))])

    class SDK:
        chat = SimpleNamespace(completions=SimpleNamespace(create=call))

        def __init__(self, **kwargs):
            clients.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    monkeypatch.setattr(auxiliary_client, "OpenAI", SDK)
    monkeypatch.setenv("HERMES_OPENROUTER_CACHE", "true")
    assert openrouter_planner("fixture/model", "test-key")(payload()) == {"action": "inspect"}
    assert len(calls) == 1
    sent = calls[0]
    assert len(clients) == 1 and clients[0]["base_url"].rstrip("/") == "https://openrouter.ai/api/v1"
    assert clients[0]["max_retries"] == 0 and clients[0]["api_key"] == "test-key"
    assert not clients[0]["http_client"].follow_redirects
    assert "X-OpenRouter-Cache" not in clients[0]["default_headers"]
    assert sent["model"] == "fixture/model" and "tools" not in sent
    assert json.loads(sent["messages"][1]["content"]) == payload()
