"""Exercise the dry run through authenticated Run, Stop, and device routes."""

import asyncio
import base64
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
from types import SimpleNamespace
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import httpx
from PIL import Image
import pytest
import pytest_asyncio

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from troika_product.computer_api import (
    register_computer_dry_run_routes, register_windows_browser_routes,
    register_windows_computer_lab_routes, register_windows_computer_vision_routes,
)


def adapter_for(tmp_path, **extra):
    return APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True,
        "product_auth_db": str(tmp_path / "access.db"),
        "product_artifact_root": str(tmp_path / "artifacts"),
        "product_workspace_root": str(tmp_path / "workspace"),
        "product_quotas_enabled": False,
        **extra,
    }))


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [{}, {"product_auth_enabled": False, "product_computer_dry_run_enabled": True}])
async def test_routes_require_explicit_opt_in_and_product_auth(tmp_path, options):
    app = web.Application()
    adapter = adapter_for(tmp_path, **options)
    register_computer_dry_run_routes(app, adapter)
    register_windows_computer_lab_routes(app, adapter)
    register_windows_computer_vision_routes(app, adapter)
    register_windows_browser_routes(app, adapter)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/v1/runs/example/computer-dry-run/request", json={"version": 1})
        assert response.status == 404
        assert (await client.get("/v1/computer-dry-run/requests")).status == 404
        assert (await client.get("/v1/computer-windows-lab/requests")).status == 404
        assert (await client.get("/v1/computer-windows-vision/requests")).status == 404
        assert (await client.get("/v1/computer-windows-browser/requests")).status == 404


@pytest.mark.asyncio
async def test_windows_lab_requires_loopback_bind(tmp_path):
    app = web.Application()
    adapter = adapter_for(tmp_path, product_computer_windows_lab_enabled=True,
                          product_computer_windows_vision_enabled=True,
                          product_computer_windows_browser_enabled=True, host="0.0.0.0")
    register_windows_computer_lab_routes(app, adapter)
    register_windows_computer_vision_routes(app, adapter)
    register_windows_browser_routes(app, adapter)
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/v1/computer-windows-lab/requests")).status == 404
        assert (await client.get("/v1/computer-windows-vision/requests")).status == 404
        assert (await client.get("/v1/computer-windows-browser/requests")).status == 404


@pytest.mark.asyncio
async def test_vision_openrouter_mode_requires_a_key(tmp_path, monkeypatch):
    monkeypatch.setattr("hermes_cli.config.get_env_value", lambda _: None)
    app = web.Application()
    adapter = adapter_for(tmp_path, product_computer_windows_vision_enabled=True,
                          product_computer_windows_vision_model="fixture/vision:free", host="127.0.0.1")
    register_windows_computer_vision_routes(app, adapter)
    assert adapter._computer_windows_vision_config_error
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/v1/computer-windows-vision/requests")).status == 404


@pytest_asyncio.fixture
async def hosted(tmp_path, monkeypatch, request):
    monkeypatch.setattr("agent.model_metadata.fetch_model_metadata", lambda **_: {})
    openrouter = getattr(request, "param", False)
    if openrouter:
        monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-openrouter-key")
    adapter = adapter_for(tmp_path, product_computer_dry_run_enabled=True,
                          product_computer_windows_lab_enabled=True, product_computer_windows_vision_enabled=True,
                          product_computer_windows_vision_fixture=not openrouter,
                          product_computer_windows_vision_model="fixture/vision:free" if openrouter else None,
                          product_computer_windows_browser_enabled=openrouter,
                          product_computer_windows_browser_model="fixture/browser:free" if openrouter else None,
                          host="127.0.0.1")
    registry = adapter._access_registry
    owner = registry.create_user("computer-owner@example.invalid")
    outsider = registry.create_user("computer-outsider@example.invalid")

    def device(account, name, platform):
        device_id = registry.create_device(account, name=name, platform=platform)
        token = registry.issue_device_token(device_id)
        return SimpleNamespace(id=device_id, token=token, headers={"Authorization": "Bearer " + token})

    phone = device(owner, "Phone", "android")
    pc = device(owner, "PC", "windows")
    spare = device(owner, "Spare", "android")
    other = device(outsider, "Other", "windows")
    ended = threading.Event()
    started_worker = threading.Event()

    def run(**_):
        started_worker.set()
        assert ended.wait(30), "synthetic agent was not released"
        return {"final_response": "Тестовая задача завершена.", "completed": True}

    monkeypatch.setattr(adapter, "_create_agent", lambda **_: SimpleNamespace(
        run_conversation=run, interrupt=lambda *_: ended.set(),
    ))
    app = web.Application()
    app.router.add_post("/v1/runs", adapter._handle_runs)
    app.router.add_get("/v1/runs/{run_id}", adapter._handle_get_run)
    app.router.add_get("/v1/runs/{run_id}/events", adapter._handle_run_events)
    app.router.add_post("/v1/runs/{run_id}/stop", adapter._handle_stop_run)
    app.router.add_delete("/v1/account/devices/{device_id}", adapter._handle_revoke_account_device)
    register_computer_dry_run_routes(app, adapter)
    register_windows_computer_lab_routes(app, adapter)
    register_windows_computer_vision_routes(app, adapter)
    register_windows_browser_routes(app, adapter)
    now = [100.0]
    monkeypatch.setattr(adapter._computer_dry_run, "_clock", lambda: now[0])
    async with TestClient(TestServer(app)) as client:
        started = await client.post("/v1/runs", headers=phone.headers, json={"input": "Пробный запуск"})
        assert started.status == 202
        run_id = (await started.json())["run_id"]
        try:
            assert await asyncio.to_thread(started_worker.wait, 10)
            yield SimpleNamespace(client=client, adapter=adapter, run_id=run_id, now=now, ended=ended,
                                  phone=phone, pc=pc, spare=spare, other=other, registry=registry)
        finally:
            ended.set()
            task = adapter._active_run_tasks.get(run_id)
            if task is not None:
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)


async def operation(hosted, device, name, http_status=200, *, route="computer-dry-run", **payload):
    response = await hosted.client.post(
        f"/v1/runs/{hosted.run_id}/{route}/{name}",
        headers=device.headers, json={"version": 1, **payload},
    )
    body = await response.json()
    assert response.status == http_status, body
    if http_status != 401:
        assert response.headers["Cache-Control"] == "private, no-store"
    return body


@pytest.mark.asyncio
@pytest.mark.parametrize(("hosted", "target"), [
    (False, "protocol"), (False, "native"), (True, "protocol"), (True, "native"), (True, "rate_limit"),
], ids=["fixture-protocol", "fixture-native", "openrouter-protocol", "openrouter-native", "openrouter-rate-limit"],
    indirect=["hosted"])
async def test_windows_vision_run_delivers_one_frame_to_hermes(hosted, monkeypatch, target):
    from hermes_cli.plugins import PluginManager
    from troika_product import computer_agent
    from troika_product.computer_openrouter_vision import OpenRouterVision

    native = target == "native"
    executable = os.environ.get("TROIKA_WINDOWS_LAB_TEST_EXE", "")
    if native:
        if os.name != "nt" or not executable:
            pytest.skip("requires Windows Graphics Capture test build")
        executable = Path(executable).with_name("TroikaComputerUseEditor.exe")
        if not executable.is_file() or not executable.with_name("TroikaWindowCapture.dll").is_file():
            pytest.skip("requires Windows Graphics Capture test build")

    monkeypatch.setattr(hosted.adapter, "_create_agent", APIServerAdapter._create_agent.__get__(hosted.adapter))
    calls = []
    observed_hooks = []
    provider = hosted.adapter._computer_windows_vision.openrouter
    description = "В пробном окне синяя область и белый текст."
    fixture_reply = computer_agent._fixture_vision_completion
    plugin_hook = PluginManager.invoke_hook

    def observe_hook(manager, name, **kwargs):
        if name == "pre_api_request" and kwargs.get("model") == "fixture/window-vision":
            observed_hooks.append(name)
        return plugin_hook(manager, name, **kwargs)

    monkeypatch.setattr(PluginManager, "invoke_hook", observe_hook)

    def observe(payload):
        agent = hosted.adapter._active_run_agents[run.run_id]
        assert agent._dump_api_request_debug(payload, reason="vision_lab_privacy") is None
        content = [m["content"] for m in payload["messages"] if m["role"] == "user"][-1]
        assert content[0] == {"type": "text", "text": "Опиши пробное окно."}
        assert not payload.get("tools")
        data_url = content[1]["image_url"]["url"]
        with Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1], validate=True))) as image:
            assert image.getpixel((image.width // 4, image.height // 4)) == (27, 67, 112)
            assert image.info == {}
        calls.append(data_url)

    def reply(payload):
        assert provider is None
        observe(payload)
        return fixture_reply(payload)

    def openrouter_reply(request):
        assert request.url == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer synthetic-openrouter-key"
        payload = json.loads(request.content)
        assert payload["model"] == "fixture/vision:free" and payload["stream"] is False
        assert payload["provider"] == {"allow_fallbacks": False, "data_collection": "deny", "zdr": True}
        assert len(payload["messages"]) == 2
        observe(payload)
        if target == "rate_limit":
            return httpx.Response(429, json={"error": {"message": "private provider error sentinel"}})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": description}}]})

    monkeypatch.setattr(computer_agent, "_fixture_vision_completion", reply)
    monkeypatch.setattr(OpenRouterVision, "_client", staticmethod(
        lambda timeout: httpx.Client(timeout=timeout, transport=httpx.MockTransport(openrouter_reply))
    ))
    denied = await hosted.client.post("/v1/runs", headers=hosted.phone.headers,
                                     json={"input": "Опиши пробное окно.", "computer_windows_lab": True,
                                           "computer_windows_vision": True})
    assert denied.status == 400
    start = await hosted.client.post("/v1/runs", headers=hosted.phone.headers,
                                    json={"input": "Опиши пробное окно.", "computer_windows_vision": True})
    assert start.status == 202, await start.text()
    run = SimpleNamespace(**{**vars(hosted), "run_id": (await start.json())["run_id"]})
    route = "computer-windows-vision"
    grant = await operation(run, run.phone, "request", 201, route=route, target_device_id=run.pc.id, ttl_seconds=60)
    grant_id = grant["grant_id"]
    assert grant["mode"] == "windows_vision_lab" and grant["actions"] == ["inspect_frame"]
    assert grant["action_limit"] == 1
    assert grant["vision_provider"] == ("openrouter" if provider is not None else "fixture")
    if provider is not None:
        consent = await operation(run, run.pc, "consent", 400, route=route, grant_id=grant_id, allow=True)
        assert consent["error"]["code"] == "vision_provider_consent_required"
    await operation(run, run.phone, "request", 404, route="computer-windows-lab", target_device_id=run.pc.id,
                    ttl_seconds=60)
    url = f"/v1/runs/{run.run_id}/{route}/frame"
    headers = {"Content-Type": "image/png", "X-Troika-Grant-Id": grant_id, "X-Troika-Frame-Remaining-Ms": "12000"}
    with Image.new("RGB", (40, 20), (27, 67, 112)) as image, io.BytesIO() as buf:
        image.save(buf, "PNG")
        frame = buf.getvalue()
    before = await run.client.post(url, headers={**run.pc.headers, **headers}, data=frame)
    assert before.status == 409 and (await before.json())["error"]["code"] == "grant_pending"
    assert not calls

    child = None
    try:
        if native:
            child = await asyncio.create_subprocess_exec(
                str(executable), "--verify-run-vision", str(run.client.make_url("/")), run.run_id, grant_id,
                env={**os.environ, "TROIKA_COMPUTER_TEST_DEVICE_TOKEN": run.pc.token},
                creationflags=subprocess.CREATE_NO_WINDOW, stdin=asyncio.subprocess.PIPE,
            )
        else:
            await operation(run, run.pc, "consent", route=route, grant_id=grant_id, allow=True,
                            vision_provider=grant["vision_provider"])
            for wrong in (run.phone, run.spare, run.other):
                response = await run.client.post(url, headers={**wrong.headers, **headers}, data=frame)
                assert response.status == 404
            invalid = await run.client.post(url, headers={**run.pc.headers, **headers}, data=frame[:-25])
            assert invalid.status == 400
            accepted = await run.client.post(url, headers={**run.pc.headers, **headers}, data=frame)
            assert accepted.status == 200
            assert await accepted.json() == {"accepted": True, "mode": "windows_vision_lab", "version": 1}
            repeated = await run.client.post(url, headers={**run.pc.headers, **headers}, data=frame)
            assert repeated.status == 409
        response = await run.client.get(f"/v1/runs/{run.run_id}/events", headers=run.phone.headers)
        stream = await asyncio.wait_for(response.text(), 20)
        assert len(calls) == 1, stream
        assert not observed_hooks
        events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")]
        if target == "rate_limit":
            assert events[-1]["event"] == "run.failed" and events[-1]["error_code"] == "openrouter_rate_limited", stream
            assert "private provider error sentinel" not in stream
        else:
            assert events[-1]["event"] == "run.completed", stream
            expected = description if provider is not None else "Тестовая модель получила один подтверждённый кадр Windows."
            assert events[-1]["output"] == expected
        assert run.adapter._computer_windows_vision._grants[run.run_id].frame is None
        with sqlite3.connect(run.registry.database_path) as database:
            dump = "\n".join(database.iterdump())
        for private in (calls[0], "data:image/png", "Пробный кадр получен."):
            assert private not in stream and private not in dump
        if child is not None:
            child.stdin.write(b"\x01")
            await child.stdin.drain()
            assert await asyncio.wait_for(child.wait(), 10) == 0
    finally:
        if child is not None and child.returncode is None:
            child.stdin.close()
            try:
                await asyncio.wait_for(child.wait(), 5)
            except asyncio.TimeoutError:
                child.kill()
                await child.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize("end", ["stop", "expire"])
async def test_vision_run_rejects_frames_after_its_permission_ends(hosted, monkeypatch, end):
    control = hosted.adapter._computer_windows_vision
    monkeypatch.setattr(control, "_clock", lambda: hosted.now[0])
    start = await hosted.client.post("/v1/runs", headers=hosted.phone.headers,
                                     json={"input": "Опиши пробное окно.", "computer_windows_vision": True})
    assert start.status == 202
    run = SimpleNamespace(**{**vars(hosted), "run_id": (await start.json())["run_id"]})
    route = "computer-windows-vision"
    grant = await operation(run, run.phone, "request", 201, route=route, target_device_id=run.pc.id, ttl_seconds=5)
    grant_id = grant["grant_id"]
    await operation(run, run.pc, "consent", route=route, grant_id=grant_id, allow=True)
    if end == "stop":
        await operation(run, run.pc, "stop", route=route, grant_id=grant_id)
    else:
        hosted.now[0] += 5
    response = await run.client.post(
        f"/v1/runs/{run.run_id}/{route}/frame",
        headers={**run.pc.headers, "Content-Type": "image/png", "X-Troika-Grant-Id": grant_id,
                 "X-Troika-Frame-Remaining-Ms": "12000"},
        data=b"frame payload never admitted",
    )
    assert response.status == 409
    expected = "grant_stopped" if end == "stop" else "grant_expired"
    assert (await response.json())["error"]["code"] == expected
    assert control._grants[run.run_id].frame is None
    stream = await run.client.get(f"/v1/runs/{run.run_id}/events", headers=run.phone.headers)
    assert expected in await asyncio.wait_for(stream.text(), 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("hosted", [True], indirect=True)
@pytest.mark.parametrize(("target_editor", "permission"), [
    ("editor", "ask"), ("editor", "window"), ("editor", "view"), ("editor", "deny"), ("editor", "stop"),
    ("notepad", "ask"), ("notepad", "window"), ("notepad", "view"), ("notepad", "deny-save"), ("notepad", "stop-before-save"),
])
async def test_assisted_windows_run_applies_the_selected_permission(hosted, monkeypatch, target_editor, permission):
    from model_tools import get_tool_definitions
    from troika_product.computer_agent import TOOLSET, WINDOWS_TOOL
    from troika_product.computer_openrouter_vision import OpenRouterVision

    test_exe = os.environ.get("TROIKA_WINDOWS_LAB_TEST_EXE")
    if os.name != "nt" or not test_exe:
        pytest.skip("requires Windows Graphics Capture test build")
    executable = Path(test_exe).with_name("TroikaComputerUseEditor.exe")
    if not executable.is_file() or not executable.with_name("TroikaWindowCapture.dll").is_file():
        pytest.skip("requires Windows Graphics Capture test build")
    monkeypatch.setattr(hosted.adapter, "_create_agent", APIServerAdapter._create_agent.__get__(hosted.adapter))
    text = "Тройка проверяет итог."
    goal = "Введи строку и сохрани: " + text
    frame_count = 0
    requested = []
    observed = []

    def respond(request):
        nonlocal frame_count
        assert request.url == "https://openrouter.ai/api/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "fixture/vision:free"
        if not payload.get("tools"):
            frame_count += 1
            parts = payload["messages"][1]["content"]
            encoded = parts[1]["image_url"]["url"].split(",", 1)[1]
            with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as image:
                assert image.width >= 380 and image.height >= 100
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
                "content": "В тестовом редакторе видно пустое поле ввода и кнопку сохранения. " * 12,
            }}]})
        assert frame_count == 1 and b"data:image/png" not in request.content
        assert [item["function"]["name"] for item in payload["tools"]] == [WINDOWS_TOOL]
        user = [m["content"] for m in payload["messages"] if m["role"] == "user"]
        assert user[0][0]["text"] == goal
        description = json.loads(user[0][1]["text"])["описание_кадра"]
        assert len(description) <= 600 and description.endswith("…")
        receipts = [m for m in payload["messages"] if m["role"] == "tool"]
        action = {"action": "inspect"}
        if receipts:
            result = json.loads(receipts[-1]["content"])
            observed.append(result)
            receipt = result.get("receipt", {})
            if result.get("can_write"):
                action = {"action": "write", "inspect_action_id": receipt["action_id"], "text": text}
            elif result.get("can_save"):
                action = {"action": "save", "inspect_action_id": receipt["action_id"]}
            elif receipt.get("status") != "applied":
                action = None
        if action is None:
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "Готово."}}]})
        requested.append(action["action"])
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{
            "id": f"call_assisted_{len(requested)}", "type": "function",
            "function": {"name": WINDOWS_TOOL, "arguments": json.dumps(action)},
        }]}}]})

    monkeypatch.setattr(OpenRouterVision, "_client", staticmethod(
        lambda timeout: httpx.Client(timeout=timeout, transport=httpx.MockTransport(respond))
    ))
    started = await hosted.client.post("/v1/runs", headers=hosted.phone.headers,
                                       json={"input": goal, "computer_windows_assisted": True})
    assert started.status == 202, await started.text()
    assert WINDOWS_TOOL not in [item["function"]["name"] for item in get_tool_definitions(
        enabled_toolsets=[TOOLSET], quiet_mode=True,
    )]
    run = SimpleNamespace(**{**vars(hosted), "run_id": (await started.json())["run_id"]})
    route = "computer-windows-assisted"
    grant = await operation(run, run.phone, "request", 201, route=route, target_device_id=run.pc.id, ttl_seconds=90)
    assert grant["mode"] == "windows_assisted_lab" and grant["permission_mode"] == "ask"
    grant_id = grant["grant_id"]
    early = await operation(run, run.pc, "approve_frame", 409, route=route, grant_id=grant_id, vision_provider="openrouter")
    assert early["error"]["code"] == "grant_pending" and not requested and frame_count == 0
    verify_mode = "--verify-notepad-assisted" if target_editor == "notepad" else "--verify-assisted"
    child = await asyncio.create_subprocess_exec(
        str(executable), verify_mode, str(run.client.make_url("/")), run.run_id, grant_id, text, permission,
        env={**os.environ, "TROIKA_COMPUTER_TEST_DEVICE_TOKEN": run.pc.token},
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        response = await run.client.get(f"/v1/runs/{run.run_id}/events", headers=run.phone.headers)
        stream = await asyncio.wait_for(response.text(), 40)
        assert await asyncio.wait_for(child.wait(), 10) == 0
        assert frame_count == 1 and "data:image/png" not in stream
        event = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")][-1]
        if permission in {"ask", "window"}:
            assert requested == ["inspect", "write", "inspect", "save"]
            assert event["event"] == "run.completed" and "проверил его содержимое" in event["output"]
        elif permission == "view":
            assert requested == [] and event["event"] == "run.completed"
            assert "пустое поле ввода" in event["output"] and len(event["output"]) <= 600
        else:
            expected_actions = ["inspect", "write"]
            if permission in {"deny-save", "stop-before-save"}:
                expected_actions += ["inspect", "save"]
            assert requested == expected_actions and "проверил его содержимое" not in stream
            if permission in {"deny", "deny-save"}:
                assert observed[-1]["receipt"]["status"] == "denied"
            else:
                assert event["event"] == "run.failed" and event["error_code"] == "grant_stopped"
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()


@pytest.mark.asyncio
@pytest.mark.parametrize("hosted", [True], indirect=True)
@pytest.mark.parametrize("scenario", ["run", "mixed", "click", "hidden", "view", "deny", "stop"])
async def test_browser_run_uses_only_the_approved_device(hosted, monkeypatch, scenario):
    from copy import deepcopy
    from scripts.troika_browser_run import BrowserRunClient
    from troika_product.computer_control import ComputerControlError
    from troika_product.computer_openrouter_vision import OpenRouterVision
    from troika_product.computer_windows_browser import TOOL

    monkeypatch.setattr(hosted.adapter, "_create_agent", APIServerAdapter._create_agent.__get__(hosted.adapter))
    goal = "Открой обзор, прокрути, открой сведения и вернись в обзор."
    commands = [{"action": "inspect"}]
    if scenario == "mixed":
        commands = [{"app": "notepad", "action": action} for action in ("inspect", "open", "write", "save")]
        commands[2]["text"] = "Пробный текст"
        commands.extend([
            {"app": "browser", "action": "inspect"}, {"app": "browser", "action": "open", "page": "overview"},
            {"app": "browser", "action": "scroll", "direction": "down"},
        ])
    elif scenario == "view":
        commands.append({"action": "scroll", "direction": "down"})
    elif scenario in ("click", "hidden"):
        commands.extend([{"action": "open", "page": "overview"}, {"action": "click", "link_id": 2}])
    else:
        commands.extend([
            {"action": "open", "page": "overview"}, {"action": "scroll", "direction": "down"},
            {"action": "open", "page": "details"}, {"action": "switch", "page": "overview"},
        ])
    calls, observed = [], []

    def respond(request):
        assert request.url == "https://openrouter.ai/api/v1/chat/completions"
        assert b"PRIVATE_BROWSER_HEADING" not in request.content
        assert b"INTERNAL_FRAGMENT" not in request.content
        data = json.loads(request.content)
        assert data["model"] == "fixture/browser:free"
        assert [tool["function"]["name"] for tool in data["tools"]] == [TOOL]
        receipts = [json.loads(msg["content"]) for msg in data["messages"] if msg["role"] == "tool"]
        if receipts:
            observed.append(receipts[-1])
        if len(calls) == len(commands):
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "Готово."}}]})
        command = commands[len(calls)]
        calls.append(command["action"])
        return httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{
            "id": f"browser_{len(calls)}", "type": "function",
            "function": {"name": TOOL, "arguments": json.dumps(command)},
        }]}}]})

    monkeypatch.setattr(OpenRouterVision, "_client", staticmethod(
        lambda timeout: httpx.Client(timeout=timeout, transport=httpx.MockTransport(respond))
    ))

    class Browser:
        targets = {"overview": "fixture", "details": "fixture"}

        def __init__(self):
            self.active = None
            self.positions = {}
            self.actions = []
            self.fragment = None
            self.apps = ["browser", "notepad"] if scenario == "mixed" else ["browser"]
            self.editor = {"open": False, "can_write": False, "can_save": False, "saved": False}

        def notepad(self, command, expires):
            action = command["action"]
            if action == "open":
                self.editor.update(open=True, can_write=True)
            elif action == "write":
                assert command["text"] == "Пробный текст" and self.editor["can_write"]
                self.editor.update(can_write=False, can_save=True)
            elif action == "save":
                assert self.editor["can_save"]
                self.editor.update(can_save=False, saved=True)
            if action != "inspect":
                self.actions.append("notepad " + action)
            return {"action": action, "view": deepcopy(self.editor)}

        def inspect(self):
            view = {"page": self.active, "open_pages": list(self.positions)}
            if self.active is not None:
                view.update(y=self.positions[self.active], max_y=640, window=123,
                            headings=["PRIVATE_BROWSER_HEADING"] if scenario != "click" else ["Overview"],
                            fragment=self.fragment, at_section=self.fragment is not None,
                            links=[] if self.fragment else [{"id": 2, "label": "Delivery", "fragment": "INTERNAL_FRAGMENT"}])
            return deepcopy(view)

        def step(self, command, approve, *, expires=None):
            action = command["action"]
            if action != "inspect" and not approve(command):
                return {"error": "denied"}
            if action == "open":
                self.active = command["page"]
                self.positions[self.active] = 0
            elif action == "switch":
                self.active = command["page"]
            elif action == "scroll":
                self.positions[self.active] = 640
            elif action == "click":
                self.fragment = "INTERNAL_FRAGMENT"
                self.positions[self.active] = 640
            self.actions.append(action)
            return {"action": action, "view": self.inspect()}

    option = "computer_use" if scenario == "mixed" else "computer_windows_browser"
    start = await hosted.client.post("/v1/runs", headers=hosted.phone.headers,
                                     json={"input": goal, option: True})
    assert start.status == 202, await start.text()
    run = SimpleNamespace(**{**vars(hosted), "run_id": (await start.json())["run_id"]})
    route = "computer-windows-browser"
    grant = await operation(run, run.phone, "request", 201, route=route, target_device_id=run.pc.id, ttl_seconds=90)
    grant_id = grant["grant_id"]
    assert grant["app"] == "browser" and not calls
    await operation(run, run.other, "review", 404, route=route, grant_id=grant_id)
    await operation(run, run.phone, "take", 404, route=route, grant_id=grant_id)
    assert not calls
    browser = Browser()
    asking, release = threading.Event(), threading.Event()

    def approve(command, _deadline):
        if command["action"] == "click":
            assert command == {"app": "browser", "action": "click", "link_id": 2, "label": "Delivery"}
        if scenario == "stop":
            asking.set()
            assert release.wait(25)
        return scenario != "deny"

    def device_run():
        import time

        device = BrowserRunClient(str(run.client.make_url("/")), run.run_id, grant_id, run.pc.token)
        try:
            assert device.review() == "pending"
            permission = "view" if scenario == "view" else "run" if scenario in ("run", "mixed") else "ask"
            return device.run(browser, approve, permission, scenario == "click", time.monotonic() + 90)
        finally:
            device.close()

    worker = asyncio.create_task(asyncio.to_thread(device_run))
    try:
        if scenario == "stop":
            assert await asyncio.to_thread(asking.wait, 20)
            await operation(run, run.phone, "stop", route=route, grant_id=grant_id)
            release.set()
        response = await run.client.get(f"/v1/runs/{run.run_id}/events", headers=run.phone.headers)
        stream = await asyncio.wait_for(response.text(), 35)
        event = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")][-1]
        assert "PRIVATE_BROWSER_HEADING" not in stream
        if scenario == "stop":
            with pytest.raises(ComputerControlError, match="grant_stopped"):
                await asyncio.wait_for(worker, 10)
            assert browser.actions == ["inspect"] and event["event"] == "run.failed"
        else:
            await asyncio.wait_for(worker, 10)
            assert event["event"] == "run.completed"
            if scenario == "run":
                assert browser.actions == ["inspect", "open", "scroll", "open", "switch"]
                assert browser.inspect()["y"] == 640 and "переключение окна" in event["output"]
            elif scenario == "mixed":
                assert browser.actions == ["notepad open", "notepad write", "notepad save", "inspect", "open", "scroll"]
                assert browser.editor["saved"] and browser.inspect()["y"] == 640
                assert "Блокнот сохранил" in event["output"] and "прокрутку" in event["output"]
            elif scenario == "click":
                assert browser.actions == ["inspect", "open", "click"]
                assert observed[-2]["can_click"] == [{"id": 2, "label": "Delivery"}]
                assert observed[-1]["view"]["at_section"] and "переход по ссылке" in event["output"]
                assert "Delivery" not in stream
            elif scenario == "hidden":
                assert browser.actions == ["inspect", "open"] and observed[-1]["error"] == "stale_state"
            elif scenario == "view":
                assert browser.actions == ["open", "inspect"] and observed[-1]["error"] == "action_denied"
            else:
                assert browser.actions == ["inspect"] and "отклонено" in event["output"]
        assert run.adapter._ensure_session_db().get_messages(run.run_id) == []
    finally:
        release.set()
        if not worker.done():
            await operation(run, run.phone, "stop", route=route, grant_id=grant_id)
            await asyncio.gather(worker, return_exceptions=True)


async def request_grant(hosted, target, ttl=60):
    return await operation(hosted, hosted.phone, "request", 201, target_device_id=target.id, ttl_seconds=ttl)


async def pending_requests(hosted, device):
    response = await hosted.client.get("/v1/computer-dry-run/requests", headers=device.headers)
    assert response.status == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    return (await response.json())["requests"]


def command(grant, sequence, action="inspect", **fields):
    return {"grant_id": grant["grant_id"], "action_id": uuid4().hex,
            "sequence": sequence, "action": action, **fields}


@pytest.mark.asyncio
async def test_device_bound_consent_and_deduplicated_simulation(hosted):
    grant = await request_grant(hosted, hosted.pc)
    assert grant["status"] == "pending"
    assert await pending_requests(hosted, hosted.pc) == [{"run_id": hosted.run_id, **grant}]
    for wrong_device in (hosted.phone, hosted.spare, hosted.other):
        assert await pending_requests(hosted, wrong_device) == []
    inspect = command(grant, 1)
    pending = await operation(hosted, hosted.phone, "action", 409, **inspect)
    assert pending["error"]["code"] == "grant_pending"
    for wrong_device in (hosted.phone, hosted.spare, hosted.other):
        await operation(hosted, wrong_device, "consent", 404, grant_id=grant["grant_id"], allow=True)
    reviewed = await operation(hosted, hosted.pc, "review", grant_id=grant["grant_id"])
    assert reviewed == grant
    hosted.now[0] += 5
    consent = await operation(hosted, hosted.pc, "consent", grant_id=grant["grant_id"], allow=True)
    assert consent["status"] == "active" and consent["expires_in_seconds"] == 55
    assert await pending_requests(hosted, hosted.pc) == []
    replacement_token = hosted.registry.issue_device_token(hosted.pc.id)
    replacement = SimpleNamespace(headers={"Authorization": "Bearer " + replacement_token})
    await operation(hosted, replacement, "stop", 404, grant_id=grant["grant_id"])
    await operation(hosted, hosted.pc, "action", 404, **inspect)
    results = await asyncio.gather(*(operation(hosted, hosted.phone, "action", **inspect) for _ in range(2)))
    assert results[0] == results[1]
    obs = results[0]["observation"]
    assert results[0]["receipt"]["status"] == "simulated"
    assert not results[0]["receipt"]["verified"]
    assert "observation" not in results[0]["receipt"]
    click = command(grant, 2, "click", observation_id=obs["id"], element_id="preview")
    result = await operation(hosted, hosted.phone, "action", **click)
    assert result == await operation(hosted, hosted.phone, "action", **click)
    assert "observation" not in result
    assert "observation" not in await operation(hosted, hosted.phone, "action", **inspect)
    conflict = await operation(hosted, hosted.phone, "action", 409, **{**click, "sequence": 3})
    assert conflict["error"]["code"] == "action_conflict"
    stale = await operation(hosted, hosted.phone, "action", 409, **{**click, "sequence": 3, "action_id": uuid4().hex})
    assert stale["error"]["code"] == "stale_state"

    hosted.ended.set()
    response = await hosted.client.get(f"/v1/runs/{hosted.run_id}/events", headers=hosted.phone.headers)
    stream = await asyncio.wait_for(response.text(), 5)
    with sqlite3.connect(hosted.registry.database_path) as database:
        dump = "\n".join(database.iterdump())
    for private in (obs["id"], obs["elements"][0]["label"]):
        assert private not in stream and private not in dump
    stopped = await operation(hosted, hosted.phone, "action", 409, **click)
    assert stopped["error"]["code"] == "grant_stopped"


@pytest.mark.asyncio
@pytest.mark.parametrize("end", ["expired", "stopped", "run_stop", "denied", "revoked", "token_revoked"])
async def test_terminal_grants_reject_new_and_repeated_actions(hosted, end):
    grant = await request_grant(hosted, hosted.pc, ttl=20)
    await operation(hosted, hosted.pc, "consent", grant_id=grant["grant_id"], allow=end != "denied")
    action = command(grant, 1)
    if end != "denied":
        await operation(hosted, hosted.phone, "action", **action)
    if end == "expired":
        hosted.now[0] += 20
    elif end == "stopped":
        stopped = await operation(hosted, hosted.pc, "stop", grant_id=grant["grant_id"])
        assert stopped["status"] == "stopped"
    elif end == "run_stop":
        stopped = await hosted.client.post(f"/v1/runs/{hosted.run_id}/stop", headers=hosted.phone.headers)
        assert stopped.status == 200
    elif end == "revoked":
        revoked = await hosted.client.delete(f"/v1/account/devices/{hosted.pc.id}", headers=hosted.phone.headers)
        assert revoked.status == 200
    elif end == "token_revoked":
        assert hosted.registry.revoke_token(hosted.pc.token)
    reason = {"run_stop": "stopped", "token_revoked": "revoked"}.get(end, end)
    blocked = await operation(hosted, hosted.phone, "action", 409, **action)
    assert blocked["error"]["code"] == "grant_" + reason
    fresh = command(grant, 2)
    await operation(hosted, hosted.phone, "action", 404 if end == "expired" else 409, **fresh)


@pytest.mark.asyncio
async def test_rejects_foreign_targets_invalid_payloads_and_stale_observations(hosted):
    await operation(hosted, hosted.other, "request", 404, target_device_id=hosted.other.id, ttl_seconds=60)
    await operation(hosted, hosted.phone, "request", 404, target_device_id=hosted.other.id, ttl_seconds=60)
    await operation(hosted, hosted.phone, "request", 400, target_device_id=hosted.spare.id, ttl_seconds=True)
    await operation(hosted, hosted.phone, "request", 400, target_device_id=hosted.spare.id, ttl_seconds=121)
    grant = await request_grant(hosted, hosted.spare)
    assert grant["platform"] == "android"
    await operation(hosted, hosted.spare, "consent", grant_id=grant["grant_id"], allow=True)
    inspect = command(grant, 1)
    await operation(hosted, hosted.phone, "action", 400, **{**inspect, "version": 2})
    await operation(hosted, hosted.phone, "action", 400, **{**inspect, "text": "private sentinel"})
    await operation(hosted, hosted.phone, "action", 400, **{**inspect, "action": "screenshot"})
    await operation(hosted, hosted.phone, "action", 409, **{**inspect, "sequence": 2})
    result = await operation(hosted, hosted.phone, "action", **inspect)
    hosted.now[0] += 15
    click = command(grant, 2, "click", observation_id=result["observation"]["id"], element_id="preview")
    stale = await operation(hosted, hosted.phone, "action", 409, **click)
    assert stale["error"]["code"] == "stale_state"

    url = f"/v1/runs/{hosted.run_id}/computer-dry-run/action"
    oversized = await hosted.client.post(url, headers=hosted.phone.headers, data=b" " * 4097)
    assert oversized.status == 413
    duplicated = await hosted.client.post(url, headers=hosted.phone.headers, data=b'{"version":1,"version":2}')
    assert duplicated.status == 400


async def start_model_run(hosted):
    response = await hosted.client.post(
        "/v1/runs", headers=hosted.phone.headers,
        json={"input": "Нажми пробную кнопку", "computer_dry_run": True,
              "conversation_history": [{"role": "user", "content": "PRIVATE_OLD_HISTORY"}]},
    )
    assert response.status == 202, await response.text()
    return SimpleNamespace(**{**vars(hosted), "run_id": (await response.json())["run_id"]})


@pytest.mark.asyncio
async def test_model_run_denial_finishes_without_creating_an_agent(hosted, monkeypatch):
    def unexpected(**_):
        pytest.fail("The device declined consent")

    monkeypatch.setattr(hosted.adapter, "_create_agent", unexpected)
    run = await start_model_run(hosted)
    grant = await request_grant(run, run.pc)
    await operation(run, run.pc, "consent", grant_id=grant["grant_id"], allow=False)
    response = await run.client.get(f"/v1/runs/{run.run_id}/events", headers=run.phone.headers)
    assert "grant_denied" in await asyncio.wait_for(response.text(), 8)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "stopped", "stale"])
async def test_hermes_selects_simulated_actions_without_receiving_the_observation(hosted, monkeypatch, outcome):
    from model_tools import get_tool_definitions
    from openai.types.chat import ChatCompletion
    from run_agent import AIAgent
    from troika_product.computer_agent import TOOL, TOOLSET

    monkeypatch.setattr(hosted.adapter, "_create_agent", APIServerAdapter._create_agent.__get__(hosted.adapter))
    monkeypatch.setattr("gateway.run._resolve_runtime_agent_kwargs", lambda: {
        "api_key": "synthetic-test-key", "base_url": "https://openrouter.ai/api/v1",
        "provider": "openrouter", "api_mode": "chat_completions",
    })
    monkeypatch.setattr("gateway.run._resolve_gateway_model", lambda: "fixture/test-model")
    monkeypatch.setattr("gateway.run._load_gateway_config", lambda: {})
    monkeypatch.setattr("gateway.run.GatewayRunner._load_reasoning_config", lambda: None)
    monkeypatch.setattr("agent.agent_init.fetch_model_metadata", lambda: {})
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda: {})
    assert get_tool_definitions(enabled_toolsets=[TOOLSET], quiet_mode=True) == []
    deciding_click = threading.Event()
    release_click = threading.Event()
    receipts = []
    provider_payloads = []
    observation_ids = []
    control = hosted.adapter._computer_dry_run
    claim = "Я нажала кнопку на настоящем устройстве."

    def fake_provider(agent, payload, **_):
        provider_payloads.append(json.dumps(payload, ensure_ascii=False))
        assert [tool["function"]["name"] for tool in agent.tools] == [TOOL]
        step = len(provider_payloads)
        tool_call = None
        if step == 1:
            tool_call = {"action": "inspect"}
        else:
            latest = json.loads([m for m in payload["messages"] if m["role"] == "tool"][-1]["content"])
            receipts.append(latest)
            if step == 2:
                assert latest["ok"] is True, latest
                with control._lock:
                    observation_ids.append(control._grants[run.run_id].observation.id)
                tool_call = {"action": "click", "inspect_action_id": latest["receipt"]["action_id"]}
                deciding_click.set()
                assert release_click.wait(10)
        message = {"role": "assistant", "content": claim}
        if tool_call is not None:
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"call_{step}", "type": "function",
                 "function": {"name": TOOL, "arguments": json.dumps(tool_call)}},
            ]}
        return ChatCompletion.model_validate({
            "id": f"fixture_{step}", "object": "chat.completion", "created": 0, "model": "fixture/test-model",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if tool_call else "stop", "message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
        })

    monkeypatch.setattr(AIAgent, "_interruptible_api_call", fake_provider)
    monkeypatch.setattr(AIAgent, "_interruptible_streaming_api_call", fake_provider)
    run = await start_model_run(hosted)
    grant = await request_grant(run, run.pc)
    try:
        await operation(run, run.spare, "consent", 404, grant_id=grant["grant_id"], allow=True)
        assert provider_payloads == []
        await operation(run, run.pc, "consent", grant_id=grant["grant_id"], allow=True)
        assert await asyncio.to_thread(deciding_click.wait, 20)
        if outcome == "stopped":
            await operation(run, run.pc, "stop", grant_id=grant["grant_id"])
        elif outcome == "stale":
            run.now[0] += 15
        release_click.set()
        response = await run.client.get(f"/v1/runs/{run.run_id}/events", headers=run.phone.headers)
        raw_stream = await asyncio.wait_for(response.text(), 12)
        events = [json.loads(line[6:]) for line in raw_stream.splitlines() if line.startswith("data: ")]
        stream = json.dumps(events, ensure_ascii=False)
        assert events[-1]["event"] == "run.completed"
        assert claim not in stream
        assert receipts[0]["can_click_preview"] is True
        assert receipts[0]["receipt"]["verified"] is False
        if outcome != "success":
            error = "grant_stopped" if outcome == "stopped" else "stale_state"
            assert receipts[1] == {"ok": False, "error": error}
            assert "Нажатие в симуляции не подтверждено." in stream
        else:
            assert receipts[1]["receipt"]["action"] == "click"
            assert "Нажатие тестовой кнопки выполнено в симуляции." in stream
        assert hosted.adapter._ensure_session_db().get_messages(run.run_id) == []
        for private in [*observation_ids, "Synthetic preview button", "PRIVATE_OLD_HISTORY", grant["grant_id"]]:
            assert all(private not in item for item in [stream, *provider_payloads])
        assert get_tool_definitions(enabled_toolsets=[TOOLSET], quiet_mode=True) == []
    finally:
        release_click.set()


@pytest.mark.asyncio
@pytest.mark.parametrize("target_mode", ["protocol", "legacy", "server_stop", "native", "external"])
async def test_windows_run_receives_only_device_confirmed_actions(hosted, monkeypatch, target_mode):
    from openai.types.chat import ChatCompletion
    from run_agent import AIAgent
    from troika_product.computer_agent import WINDOWS_TOOL

    executable = os.environ.get("TROIKA_WINDOWS_LAB_TEST_EXE", "")
    if target_mode in ("native", "external"):
        if os.name != "nt" or not executable:
            pytest.skip("requires the Windows Computer Use test build")
        if target_mode == "external":
            executable = str(Path(executable).with_name("TroikaComputerUseEditor.exe"))
        if not Path(executable).is_file():
            pytest.skip("requires the Windows Computer Use test executable")
    monkeypatch.setattr(hosted.adapter, "_create_agent", APIServerAdapter._create_agent.__get__(hosted.adapter))
    monkeypatch.setattr("gateway.run._resolve_runtime_agent_kwargs", lambda: {
        "api_key": "synthetic-test-key", "base_url": "https://openrouter.ai/api/v1",
        "provider": "openrouter", "api_mode": "chat_completions",
    })
    monkeypatch.setattr("gateway.run._resolve_gateway_model", lambda: "fixture/test-model")
    monkeypatch.setattr("gateway.run._load_gateway_config", lambda: {})
    monkeypatch.setattr("gateway.run.GatewayRunner._load_reasoning_config", lambda: None)
    monkeypatch.setattr("agent.agent_init.fetch_model_metadata", lambda: {})
    monkeypatch.setattr("agent.models_dev.fetch_models_dev", lambda: {})
    payloads = []
    receipts = []
    dumps = []
    expected_text = '  Проверка «Тройки» — 😀 \\ $  '
    inspect_action_id = None

    def fake_provider(agent, payload, **_):
        nonlocal inspect_action_id
        assert [tool["function"]["name"] for tool in agent.tools] == [WINDOWS_TOOL]
        payloads.append(json.dumps(payload, ensure_ascii=False))
        step = len(payloads)
        if step > 2:
            dumps.append(agent._dump_api_request_debug(payload, reason="windows_lab_privacy"))
        args = None
        if step == 1:
            args = {"action": "inspect"}
        else:
            receipt = json.loads([m for m in payload["messages"] if m["role"] == "tool"][-1]["content"])
            receipts.append(receipt)
            if receipt.get("can_write"):
                assert receipt["text_input"] is (target_mode != "legacy")
                inspect_action_id = receipt["receipt"]["action_id"]
                args = {"action": "write", "inspect_action_id": inspect_action_id}
                if receipt["text_input"]:
                    args["text"] = "строка\nновая строка" if target_mode == "protocol" else expected_text
            elif receipt.get("error") == "invalid_text" and target_mode == "protocol":
                args = {"action": "write", "inspect_action_id": inspect_action_id, "text": expected_text}
            elif receipt.get("can_save"):
                args = {"action": "save", "inspect_action_id": receipt["receipt"]["action_id"]}
            elif receipt.get("receipt", {}).get("status") == "applied":
                args = {"action": "inspect"}
        message = {"role": "assistant", "content": "Заявление модели не используется для подтверждения."}
        if args is not None:
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": f"call_{step}", "type": "function",
                 "function": {"name": WINDOWS_TOOL, "arguments": json.dumps(args)}},
            ]}
        return ChatCompletion.model_validate({
            "id": f"windows_fixture_{step}", "object": "chat.completion", "created": 0, "model": "fixture/test-model",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if args else "stop", "message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110},
        })

    monkeypatch.setattr(AIAgent, "_interruptible_api_call", fake_provider)
    monkeypatch.setattr(AIAgent, "_interruptible_streaming_api_call", fake_provider)
    start = await hosted.client.post("/v1/runs", headers=hosted.phone.headers,
                                     json={"input": "Заполни и сохрани тестовый редактор",
                                           "computer_windows_lab": True})
    assert start.status == 202, await start.text()
    run = SimpleNamespace(**{**vars(hosted), "run_id": (await start.json())["run_id"]})

    async def windows(device, name, http_status=200, **data):
        return await operation(run, device, name, http_status, route="computer-windows-lab", **data)

    await windows(run.phone, "request", 404, target_device_id=run.spare.id, ttl_seconds=60)
    await operation(run, run.phone, "request", 404, target_device_id=run.pc.id, ttl_seconds=60)
    grant = await windows(run.phone, "request", 201, target_device_id=run.pc.id, ttl_seconds=60)
    grant_id = grant["grant_id"]
    assert grant["mode"] == "windows_lab" and payloads == []
    await windows(run.spare, "consent", 404, grant_id=grant_id, allow=True)
    await windows(run.pc, "consent", 400, grant_id=grant_id, allow=True, text_input="true")
    await windows(run.pc, "take", 409, grant_id=grant_id)
    if target_mode in ("native", "external"):
        option = "--verify-run" if target_mode == "external" else "--windows-run-endpoint"
        child = await asyncio.create_subprocess_exec(
            executable, option, str(run.client.make_url("/")), run.run_id, grant_id, expected_text,
            env={**os.environ, "TROIKA_COMPUTER_TEST_DEVICE_TOKEN": run.pc.token},
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            assert await asyncio.wait_for(child.wait(), 30) == 0
        finally:
            if child.returncode is None:
                child.kill()
                await child.wait()
    else:
        options = {} if target_mode == "legacy" else {"text_input": True}
        consent = await windows(run.pc, "consent", grant_id=grant_id, allow=True, **options)
        assert consent["text_input"] is (target_mode != "legacy")
        await windows(run.spare, "take", 404, grant_id=grant_id)

        async def take():
            while True:
                reply = await windows(run.pc, "take", grant_id=grant_id)
                if reply["command"] is not None:
                    return reply["command"]
                await asyncio.sleep(0.03)

        previous = None
        steps = [("inspect", "observed", {"can_write": True, "can_save": False}),
                 ("write", "applied", {}),
                 ("inspect", "observed", {"can_write": False, "can_save": True}),
                 ("save", "verified", {})]
        for sequence, (action, status, flags) in enumerate(steps, 1):
            delivered = await asyncio.wait_for(take(), 15)
            assert delivered["sequence"] == sequence and delivered["action"] == action
            assert (await windows(run.pc, "take", grant_id=grant_id))["command"] is None
            if action == "inspect":
                previous = delivered["id"]
            else:
                assert delivered["inspect_action_id"] == previous
            if action == "write" and target_mode != "legacy":
                assert delivered["text"] == expected_text
            else:
                assert "text" not in delivered
            result = {"grant_id": grant_id, "command_id": delivered["id"], "status": status, **flags}
            if target_mode == "server_stop" and action == "write":
                await windows(run.phone, "stop", grant_id=grant_id)
                await windows(run.pc, "report", 409, **result)
                break
            await windows(run.pc, "report", 400, **result, path="PRIVATE_WINDOW_TEST_PATH")
            assert (await windows(run.pc, "report", **result))["accepted"]

    response = await run.client.get(f"/v1/runs/{run.run_id}/events", headers=run.phone.headers)
    stream = await asyncio.wait_for(response.text(), 12)
    events = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith("data: ")]
    assert events[-1]["event"] == "run.completed"
    if target_mode == "server_stop":
        assert receipts[-1] == {"ok": False, "error": "grant_stopped"}
        assert "Ввод не подтверждён." in events[-1]["output"]
    else:
        assert receipts[-1]["receipt"]["verified"] is True
        assert "проверил его содержимое" in events[-1]["output"]
    if target_mode == "protocol":
        assert {"ok": False, "error": "invalid_text"} in receipts
    assert dumps and all(path is None for path in dumps)
    assert hosted.adapter._ensure_session_db().get_messages(run.run_id) == []
    assert expected_text not in json.dumps(events, ensure_ascii=False)
    assert expected_text not in json.dumps(receipts, ensure_ascii=False)
    for private in (grant_id, "PRIVATE_WINDOW_TEST_PATH", "Пробная запись Тройки."):
        assert all(private not in text for text in [stream, *payloads])


@pytest.mark.parametrize("text", ["", None, "\0", "\u2028", "\ud800", "x" * 513, "😀" * 257])
def test_windows_editor_rejects_text_outside_single_line_utf16_limit(text):
    from troika_product.computer_windows_lab import _valid_editor_text

    assert not _valid_editor_text(text)
    assert _valid_editor_text("😀" * 256)
