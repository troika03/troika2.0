"""Exercise the dry run through authenticated Run, Stop, and device routes."""

import asyncio
import json
import sqlite3
import threading
from types import SimpleNamespace
from uuid import uuid4

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest
import pytest_asyncio

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from troika_product.computer_api import register_computer_dry_run_routes


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
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/v1/runs/example/computer-dry-run/request", json={"version": 1})
        assert response.status == 404
        assert (await client.get("/v1/computer-dry-run/requests")).status == 404


@pytest_asyncio.fixture
async def hosted(tmp_path, monkeypatch):
    adapter = adapter_for(tmp_path, product_computer_dry_run_enabled=True)
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


async def operation(hosted, device, name, status=200, **payload):
    response = await hosted.client.post(
        f"/v1/runs/{hosted.run_id}/computer-dry-run/{name}",
        headers=device.headers, json={"version": 1, **payload},
    )
    body = await response.json()
    assert response.status == status, body
    if status != 401:
        assert response.headers["Cache-Control"] == "private, no-store"
    return body


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
