import asyncio
import base64
import io
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

from aiohttp.test_utils import TestClient, TestServer
from PIL import Image, PngImagePlugin
import pytest

from scripts import troika_computer_lab
from scripts.troika_computer_lab import create_app, create_vision_app, openrouter_planner


TOKEN = "test_computer_lab_token_for_one_process"
OBS_ID = "a" * 32
GOAL = "Запиши пробную строку и сохрани."
VISION_URL = "/v1/computer-lab/vision"
VISION_HEADERS = {"Authorization": "Bearer " + TOKEN, "Content-Type": "image/png"}


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


def fixture_png(size=(40, 20)):
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("comment", "private-png-metadata")
    with Image.new("RGB", size, (27, 67, 112)) as image, io.BytesIO() as buffer:
        image.save(buffer, "PNG", pnginfo=metadata)
        return buffer.getvalue()


def observe_model_frame(monkeypatch):
    seen = []
    model = troika_computer_lab._fixture_vision_response

    def inspect(request):
        payload = json.loads(request.content)
        assert "tools" not in payload
        parts = payload["messages"][1]["content"]
        assert [part["type"] for part in parts] == ["text", "image_url"]
        prefix, encoded = parts[1]["image_url"]["url"].split(",", 1)
        assert prefix == "data:image/png;base64"
        frame = base64.b64decode(encoded, validate=True)
        assert b"private-png-metadata" not in frame
        with Image.open(io.BytesIO(frame)) as image:
            assert image.mode == "RGB" and image.info == {}
            assert image.getpixel((image.width // 4, image.height // 4)) == (27, 67, 112)
            seen.append(image.size)
        return model(request)

    monkeypatch.setattr(troika_computer_lab, "_fixture_vision_response", inspect)
    return seen


@pytest.mark.asyncio
async def test_vision_accepts_one_bounded_authorized_frame(monkeypatch, caplog):
    caplog.set_level("DEBUG", logger="openai._base_client")
    seen = observe_model_frame(monkeypatch)
    async with TestClient(TestServer(create_vision_app(TOKEN))) as client:
        assert (await client.post(VISION_URL, data=fixture_png())).status == 401
        assert (await client.post("/v1/computer-lab/next", headers=VISION_HEADERS, data=fixture_png())).status == 404
        for invalid in [b"not an image", fixture_png()[:-20], fixture_png((1281, 1)), b"x" * (1024 * 1024 + 1)]:
            assert (await client.post(VISION_URL, headers=VISION_HEADERS, data=invalid)).status == 400
        assert not seen
        replies = await asyncio.gather(*[
            client.post(VISION_URL, headers=VISION_HEADERS, data=fixture_png()) for _ in range(2)
        ])
        assert sorted(reply.status for reply in replies) == [200, 409]
        accepted = next(reply for reply in replies if reply.status == 200)
        assert accepted.headers["Cache-Control"] == "no-store"
        assert await accepted.json() == {"summary": "Пробный кадр получен."}
        assert seen == [(40, 20)]
        assert "data:image/png" not in caplog.text


@pytest.mark.asyncio
async def test_vision_disallows_expired_grant_and_model_actions(monkeypatch):
    time = 0
    monkeypatch.setattr(troika_computer_lab, "fixture_vision_planner",
                        lambda _: {"summary": "Проба", "action": "write"})
    async with TestClient(TestServer(create_vision_app(TOKEN, clock=lambda: time))) as client:
        reply = await client.post(VISION_URL, headers=VISION_HEADERS, data=fixture_png())
        assert reply.status == 502 and await reply.json() == {"error": "vision_unavailable"}
        assert (await client.post(VISION_URL, headers=VISION_HEADERS, data=fixture_png())).status == 409
    async with TestClient(TestServer(create_vision_app(TOKEN, clock=lambda: time))) as client:
        time = 120
        assert (await client.post(VISION_URL, headers=VISION_HEADERS, data=fixture_png())).status == 410


@pytest.mark.asyncio
async def test_native_window_frame_reaches_the_stubbed_model(monkeypatch):
    executable = os.environ.get("TROIKA_WINDOWS_LAB_TEST_EXE")
    if os.name != "nt" or not executable:
        pytest.skip("requires the Windows Graphics Capture test build")
    executable = Path(executable).with_name("TroikaComputerUseEditor.exe")
    if not executable.is_file() or not executable.with_name("TroikaWindowCapture.dll").is_file():
        pytest.skip("requires the Windows Graphics Capture test build")

    seen = observe_model_frame(monkeypatch)
    async with TestClient(TestServer(create_vision_app(TOKEN))) as client:
        process = await asyncio.create_subprocess_exec(
            str(executable), "--verify-vision", str(client.make_url("/")),
            env={**os.environ, "TROIKA_COMPUTER_LAB_TOKEN": TOKEN},
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            assert await asyncio.wait_for(process.wait(), 35) == 0
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert len(seen) == 1 and seen[0][0] > 200 and seen[0][1] > 100
