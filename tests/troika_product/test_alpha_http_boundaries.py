"""Exercise alpha account and Stop boundaries over real loopback HTTP.

The worker in the Stop scenario is scripted. Authentication, SQLite stores,
resource scopes, cancellation, and SSE handlers are the real implementations.
No installed client or model provider is involved.
"""

import asyncio
import ipaddress
import json
import socket
import threading
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from agent.provider_metering import ProviderCallBlocked, current_provider_guard
from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from hermes_state import SessionDB


@pytest.fixture
def offline(monkeypatch):
    """Allow only loopback sockets; fail before any external DNS or connect."""
    original_dns = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def check(host):
        if host == "localhost":
            return
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = False
        if not allowed:
            pytest.fail("Unexpected external network access")

    def dns(host, *args, **kwargs):
        check(host)
        return original_dns(host, *args, **kwargs)

    def connect(sock, address):
        check(address[0])
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check(address[0])
        return original_connect_ex(sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)


def make_adapter(directory):
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True,
        "product_auth_db": str(directory / "access.db"),
        "product_artifact_root": str(directory / "artifacts"),
        "product_workspace_root": str(directory / "workspaces"),
        "product_resource_enabled": True,
        "product_quotas_enabled": False,
        "product_voice_enabled": False,
        "product_retention_enabled": False,
        "product_compact_context_enabled": True,
    }))
    adapter._session_db = SessionDB(directory / "state.db")
    return adapter


def app_for(adapter):
    app = web.Application()
    app.router.add_post("/v1/auth/register", adapter._handle_product_register)
    app.router.add_post("/v1/auth/login", adapter._handle_product_login)
    app.router.add_post("/v1/auth/refresh", adapter._handle_product_refresh)
    app.router.add_post("/v1/auth/logout-all", adapter._handle_product_logout_all)
    app.router.add_get("/v1/sessions/{session_id}/messages", adapter._handle_get_session_messages)
    app.router.add_post("/v1/runs", adapter._handle_runs)
    app.router.add_get("/v1/runs/{run_id}", adapter._handle_get_run)
    app.router.add_get("/v1/runs/{run_id}/events", adapter._handle_run_events)
    app.router.add_post("/v1/runs/{run_id}/stop", adapter._handle_stop_run)
    return app


def headers(pair):
    return {"Authorization": "Bearer " + pair["access_token"]}


async def register(client, email):
    response = await client.post("/v1/auth/register", json={
        "email": email, "password": "synthetic-password-123",
        "platform": "android", "device_name": "Synthetic phone",
    })
    assert response.status == 201
    assert response.headers["Cache-Control"] == "no-store"
    return await response.json()


@pytest.mark.asyncio
async def test_two_device_history_survives_restart_and_logout_is_owner_scoped(tmp_path, offline):
    adapter = make_adapter(tmp_path)
    try:
        async with TestClient(TestServer(app_for(adapter), host="127.0.0.1")) as client:
            phone = await register(client, "alpha-owner@example.invalid")
            foreign = await register(client, "alpha-other@example.invalid")
            response = await client.post("/v1/auth/login", json={
                "email": "alpha-owner@example.invalid", "password": "wrong-password",
                "platform": "windows", "device_name": "Synthetic PC",
            })
            assert response.status == 401
            response = await client.post("/v1/auth/login", json={
                "email": "alpha-owner@example.invalid", "password": "synthetic-password-123",
                "platform": "windows", "device_name": "Synthetic PC",
            })
            assert response.status == 200
            pc = await response.json()
            assert pc["home_session_id"] == phone["home_session_id"]
            assert pc["access_token"] != phone["access_token"]
            principal = adapter._access_registry.authenticate(phone["access_token"])
            home = phone["home_session_id"]
            assert adapter._access_registry.claim_session(principal, home)
            # Seed synthetic history through the real store. Model execution is
            # covered separately; this scenario tests account transport/storage.
            adapter._session_db.create_session(home, "api_server")
            adapter._session_db.append_message(home, "user", "Synthetic question")
            adapter._session_db.append_message(home, "assistant", "Synthetic answer")
            path = "/v1/sessions/" + home + "/messages"
            for identity in (phone, pc):
                response = await client.get(path, headers=headers(identity))
                assert response.status == 200
                assert [m["content"] for m in (await response.json())["messages"]] == [
                    "Synthetic question", "Synthetic answer"]
            assert (await client.get(path, headers=headers(foreign))).status == 403
            assert (await client.get(path)).status == 401
    finally:
        adapter._session_db.close()

    restarted = make_adapter(tmp_path)
    try:
        async with TestClient(TestServer(app_for(restarted), host="127.0.0.1")) as client:
            response = await client.get(path, headers=headers(pc))
            assert response.status == 200
            assert (await response.json())["count"] == 2
            response = await client.post("/v1/auth/refresh", json={"refresh_token": pc["refresh_token"]})
            assert response.status == 200
            rotated = await response.json()
            assert (await client.post("/v1/auth/refresh", json={"refresh_token": pc["refresh_token"]})).status == 401
            assert (await client.get(path, headers=headers(rotated))).status == 200
            response = await client.post("/v1/auth/logout-all", headers=headers(phone))
            assert response.status == 200
            for identity in (phone, rotated):
                assert (await client.get(path, headers=headers(identity))).status == 401
            foreign_principal = restarted._access_registry.authenticate(foreign["access_token"])
            assert foreign_principal is not None
    finally:
        restarted._session_db.close()


@pytest.mark.asyncio
async def test_stop_blocks_late_worker_calls_and_new_run_gets_fresh_scope(tmp_path, monkeypatch, offline):
    adapter = make_adapter(tmp_path)
    ready, interrupted, finished = threading.Event(), threading.Event(), threading.Event()
    guards, blocked_codes = [], []

    def create(**kwargs):
        guard = current_provider_guard()
        assert guard is not None
        guards.append(guard)
        index = len(guards)

        def run(**kwargs):
            if index == 1:
                ready.set()
                try:
                    assert interrupted.wait(timeout=5)
                    for call in (
                        lambda: guard.begin_tool("troika_assistant", {"action": "task_add"}),
                        lambda: guard.begin_call({"model": "unused"}, provider="openrouter", base_url="https://openrouter.ai/api/v1"),
                    ):
                        with pytest.raises(ProviderCallBlocked) as denied:
                            call()
                        blocked_codes.append(denied.value.code)
                finally:
                    finished.set()
                return {"final_response": "Late worker result", "completed": True}
            assert not guard.stopped
            return {"final_response": "Synthetic fresh answer", "completed": True}

        return SimpleNamespace(run_conversation=run, interrupt=lambda *args: interrupted.set())

    monkeypatch.setattr(adapter, "_create_agent", create)
    try:
        async with TestClient(TestServer(app_for(adapter), host="127.0.0.1")) as client:
            owner = await register(client, "stop-owner@example.invalid")
            foreign = await register(client, "stop-other@example.invalid")
            response = await client.post("/v1/runs", headers=headers(owner), json={"input": "Synthetic task"})
            assert response.status == 202
            run_id = (await response.json())["run_id"]
            assert await asyncio.to_thread(ready.wait, 5)
            path = "/v1/runs/" + run_id
            assert (await client.post(path + "/stop", headers=headers(foreign))).status == 404
            assert not interrupted.is_set()
            response = await client.post(path + "/stop", headers=headers(owner))
            assert response.status == 200
            assert await asyncio.to_thread(finished.wait, 5)
            assert blocked_codes == ["resource_run_stopped", "resource_run_stopped"]
            response = await client.get(path + "/events", headers=headers(owner))
            events = [json.loads(line[6:]) for line in (await response.text()).splitlines() if line.startswith("data: ")]
            assert any(event["event"] == "run.cancelled" for event in events)
            assert not any(event["event"] == "run.completed" for event in events)
            assert (await (await client.get(path, headers=headers(owner))).json())["status"] == "cancelled"
            # The cancelled asyncio task cannot preempt the executor thread.
            # Wait for its real resource-scope cleanup before starting again.
            async def cleanup_finished():
                while run_id in adapter._active_resource_guards:
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(cleanup_finished(), timeout=5)
            response = await client.post("/v1/runs", headers=headers(owner), json={"input": "Synthetic new question"})
            assert response.status == 202
            fresh_id = (await response.json())["run_id"]
            assert fresh_id != run_id
            response = await client.get("/v1/runs/" + fresh_id + "/events", headers=headers(owner))
            assert "run.completed" in await response.text()
            assert len(guards) == 2 and guards[0] is not guards[1]
            assert not adapter._active_run_tasks and not adapter._active_resource_guards
    finally:
        interrupted.set()
        adapter._session_db.close()
