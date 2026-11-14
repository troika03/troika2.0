"""Account service connections: encrypted storage, sign-in and approvals."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from gateway.session_context import clear_session_override, get_session_overrides, set_session_override
from troika_product import capabilities as cap
from troika_product import extensions as ext
from troika_product import mcp_connector
from troika_product import service_connections as sc

TOKEN_SERVICE = next(item["id"] for item in ext._directory() if item.get("connect") == "token")
OAUTH_SERVICE = next(item["id"] for item in ext._directory() if item.get("connect") == "oauth")


def identity(registry, email):
    user = registry.create_user(email)
    device = registry.create_device(user, name="Test", platform="android")
    token = registry.issue_device_token(device)
    return token, registry.authenticate(token)


class Request(dict):
    def __init__(self, token, body=None, method=None, match=None, query=None):
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.method = method or ("PATCH" if body is not None else "GET")
        self.body = body
        self.remote = "127.0.0.1"
        self.transport = None
        self.path_qs = "/v1/account/services"
        self.match_info = match or {}
        self.query = query or {}

    async def json(self):
        return self.body


@pytest.fixture
def adapter(tmp_path, monkeypatch):
    monkeypatch.delenv("TROIKA_PRODUCT_SERVICE_KEY", raising=False)
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True, "product_auth_db": str(tmp_path / "access.db"),
        "product_artifact_root": str(tmp_path / "files"),
        "product_workspace_root": str(tmp_path / "workspace"),
    }))
    monkeypatch.setattr("troika_product.capability_api.available_schemas", lambda: {})
    yield adapter
    sc.configure(None, "", "")


def enable(adapter, public_url="https://api.troika.example"):
    return sc.configure(adapter._product_artifact_db, Fernet.generate_key().decode(), public_url)


def run(coro):
    return asyncio.run(coro)


def test_services_stay_unavailable_without_key_and_public_url(adapter):
    token, _ = identity(adapter._access_registry, "one@example.com")
    response = run(adapter._handle_product_extensions(Request(token)))
    services = [item for item in json.loads(response.text)["mcp"] if item.get("connect") in {"oauth", "token"}]
    assert services and all(not item["connectable"] and item["reason"] for item in services)
    response = run(adapter._handle_service_connect(Request(token, {"token": "x" * 20}, "POST", {"server_id": TOKEN_SERVICE})))
    assert response.status == 503
    # Only an HTTPS public URL enables OAuth callbacks.
    assert not sc.configure(adapter._product_artifact_db, Fernet.generate_key().decode(), "http://x").redirect_uri


def test_token_is_verified_encrypted_owner_scoped_and_removed(adapter, monkeypatch):
    registry = adapter._access_registry
    first, owner = identity(registry, "one@example.com")
    second, _ = identity(registry, "two@example.com")
    current = enable(adapter)
    seen = []

    async def probe(entry, auth=None, headers=None):
        seen.append(headers)
        if headers["Authorization"] != "Bearer good-personal-token":
            raise RuntimeError("401")
        return []
    monkeypatch.setattr(mcp_connector, "probe_async", probe)
    connect = lambda token, body: run(adapter._handle_service_connect(
        Request(token, body, "POST", {"server_id": TOKEN_SERVICE})))
    assert connect(first, {"token": "bad token"}).status == 400
    assert connect(first, {"token": "rejected-token-value"}).status == 400
    assert connect(first, {"token": "good-personal-token"}).status == 200
    assert seen[-1] == {"Authorization": "Bearer good-personal-token"}
    # Stored only encrypted.
    with registry._connect() as connection:
        raw = connection.execute("SELECT secret FROM troika_service_connections").fetchone()["secret"]
    assert b"good-personal-token" not in bytes(raw)
    assert current.store.load(owner.user_id, TOKEN_SERVICE) == ("token", {"token": "good-personal-token"})
    response = run(adapter._handle_product_extensions(Request(first)))
    assert next(item for item in json.loads(response.text)["mcp"] if item["id"] == TOKEN_SERVICE)["connected"]
    response = run(adapter._handle_product_extensions(Request(second)))
    assert not next(item for item in json.loads(response.text)["mcp"] if item["id"] == TOKEN_SERVICE)["connected"]
    # Connecting through the preference patch is refused; disconnecting works.
    assert run(adapter._handle_product_extensions(Request(first, {"mcp": {TOKEN_SERVICE: True}}))).status == 403
    assert run(adapter._handle_product_extensions(Request(first, {"mcp": {TOKEN_SERVICE: False}}))).status == 200
    assert current.store.load(owner.user_id, TOKEN_SERVICE) is None
    # Export lists names only; account deletion removes the rows.
    connect(first, {"token": "good-personal-token"})
    exported = registry.export_account_rows(owner)
    assert [row["server_id"] for row in exported["service_connections"]] == [TOKEN_SERVICE]
    assert "good-personal-token" not in json.dumps(exported, default=str)
    registry.prepare_account_deletion(owner)
    registry.finalize_account_deletion(owner.user_id)
    with registry._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM troika_service_connections").fetchone()[0] == 0


def test_oauth_flow_binds_state_to_one_owner_and_saves_only_on_success(adapter, monkeypatch):
    registry = adapter._access_registry
    first, owner = identity(registry, "one@example.com")
    second, _ = identity(registry, "two@example.com")
    current = enable(adapter)

    def provider(storage, url, redirect=None, callback=None):
        return SimpleNamespace(storage=storage, redirect=redirect, callback=callback)
    monkeypatch.setattr(sc, "_oauth_provider", provider)

    async def fake_list_tools(entry, auth):
        await auth.redirect("https://auth.service.example/authorize?client_id=c&state=expected-state")
        code, state = await auth.callback()
        assert code == "the-code" and state == "expected-state"
        from mcp.shared.auth import OAuthToken
        await auth.storage.set_tokens(OAuthToken(access_token="access", token_type="Bearer",
                                                 refresh_token="refresh", expires_in=3600))
        return []

    async def scenario():
        entry = ext.service_mcp(OAUTH_SERVICE)
        flow, url = await sc.start_oauth(entry, owner.user_id, fake_list_tools)
        assert url.startswith("https://auth.service.example/")
        assert current.store.load(owner.user_id, OAUTH_SERVICE) is None
        assert sc.flow_status(flow, owner.user_id) == "waiting"
        assert sc.flow_status(flow, "someone-else") is None
        assert not sc.complete_oauth("forged-state", "the-code", None)
        assert sc.complete_oauth("expected-state", "the-code", None)
        assert not sc.complete_oauth("expected-state", "the-code", None)  # single use
        for _ in range(50):
            if sc.flow_status(flow, owner.user_id) != "waiting":
                break
            await asyncio.sleep(0.01)
        return flow
    flow = run(scenario())
    assert sc.flow_status(flow, owner.user_id) == "connected"
    kind, secret = current.store.load(owner.user_id, OAUTH_SERVICE)
    assert kind == "oauth" and secret["tokens"]["refresh_token"] == "refresh" and secret["expires_at"]
    assert ext.connected_services(owner.user_id) == {OAUTH_SERVICE}
    assert run(adapter._handle_service_flow(Request(second, None, "GET", {"flow_id": flow}))).text == '{"status": "expired"}'


def test_callback_page_reports_unknown_state_without_account_header(adapter):
    enable(adapter)
    response = run(adapter._handle_service_callback(Request(None, None, "GET", {}, {"state": "nope", "code": "x"})))
    assert response.status == 400 and "Вернитесь в Тройку" in response.text


@pytest.fixture
def owner(adapter):
    registry = adapter._access_registry
    _, principal = identity(registry, "owner@example.com")
    previous = get_session_overrides()
    values = {
        "TROIKA_PRODUCT_MODE": "1", "TROIKA_PRODUCT_ACCESS_DB": str(registry.database_path),
        "TROIKA_PRODUCT_USER_ID": principal.user_id, "TROIKA_PRODUCT_DEVICE_ID": principal.device_id,
        "TROIKA_PRODUCT_TOKEN_ID": principal.token_id,
    }
    for key, value in values.items():
        set_session_override(key, value)
    yield registry, principal
    for key in values:
        if key in previous:
            set_session_override(key, previous[key])
        else:
            clear_session_override(key)


def test_service_writes_need_approval_and_reads_do_not(adapter, owner, monkeypatch):
    registry, principal = owner
    current = enable(adapter)
    current.store.save(principal.user_id, TOKEN_SERVICE, "token", {"token": "good-personal-token"})
    calls, approvals = [], []
    schema = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
    monkeypatch.setattr(mcp_connector, "list_tools", lambda entry, user_id=None: [
        {"name": mcp_connector.routed_name(entry["id"], "get_issue"), "parameters": schema, "read_only": True},
        {"name": mcp_connector.routed_name(entry["id"], "create_issue"), "parameters": schema, "read_only": False},
    ])

    def call_tool(entry, tool, arguments, user_id=None):
        calls.append((tool, user_id))
        return {"server": entry["id"], "tool": tool, "is_error": False, "content": "done", "truncated": False}
    monkeypatch.setattr(mcp_connector, "call_tool", call_tool)
    decision = {"approved": False}

    def approve(action, description):
        approvals.append((action, description))
        return decision
    monkeypatch.setattr("tools.approval.request_gateway_approval", approve)
    read = mcp_connector.routed_name(TOKEN_SERVICE, "get_issue")
    write = mcp_connector.routed_name(TOKEN_SERVICE, "create_issue")
    assert '"ok": true' in cap.execute({"tool": read, "arguments": {"title": "x"}})
    assert approvals == []
    assert "approval_denied" in cap.execute({"tool": write, "arguments": {"title": "Bug"}})
    assert calls == [("get_issue", principal.user_id)]
    assert approvals[0][0] == "mcp.write" and "create_issue" in approvals[0][1]
    decision["approved"] = True
    assert '"ok": true' in cap.execute({"tool": write, "arguments": {"title": "Bug"}})
    assert calls[-1] == ("create_issue", principal.user_id)
    # A disconnected service is unreachable even with a remembered schema.
    current.store.delete(principal.user_id, TOKEN_SERVICE)
    assert "mcp_not_connected" in cap.execute({"tool": read, "arguments": {"title": "x"}})


def test_expired_connection_asks_owner_to_reconnect(adapter, owner, monkeypatch):
    registry, principal = owner
    current = enable(adapter)
    current.store.save(principal.user_id, TOKEN_SERVICE, "token", {"token": "old"})

    def expired(entry, user_id=None):
        raise mcp_connector.MCPAuthRequired("401")
    monkeypatch.setattr(mcp_connector, "list_tools", expired)
    result = json.loads(cap.discover({"capability": "mcp", "tool": TOKEN_SERVICE}))
    assert result["error"] == "service_sign_in_required"
    listing = json.loads(cap.discover({"capability": "mcp"}))
    assert [item["id"] for item in listing["servers"]] == [TOKEN_SERVICE]


def test_small_model_naming_mistakes_still_reach_the_connected_service(adapter, owner, monkeypatch):
    registry, principal = owner
    current = enable(adapter)
    current.store.save(principal.user_id, TOKEN_SERVICE, "token", {"token": "good-personal-token"})
    schema = {"type": "object", "properties": {"q": {"type": "string"}}}
    many = [{"name": mcp_connector.routed_name(TOKEN_SERVICE, f"tool_{index}"), "description": "Example " * 40,
             "parameters": schema, "read_only": True} for index in range(ext.MAX_FULL_SCHEMAS + 5)]
    monkeypatch.setattr(mcp_connector, "list_tools", lambda entry, user_id=None: many)
    title = ext.service_mcp(TOKEN_SERVICE)["title"]
    # The service name used as the capability is routed to MCP discovery.
    for capability in (TOKEN_SERVICE, title, f"mcp:{TOKEN_SERVICE}", f"{TOKEN_SERVICE}_mcp"):
        result = json.loads(cap.discover({"capability": capability}))
        assert result["ok"] and result["server"] == TOKEN_SERVICE, capability
    # Many tools: compact names first, one full schema on request.
    monkeypatch.setitem(ext.service_mcp(TOKEN_SERVICE), "core_tools", ["tool_1", "tool_2"])
    monkeypatch.setitem(ext.service_mcp(TOKEN_SERVICE), "usage", "Call tool_1 first.")
    listing = json.loads(cap.discover({"capability": "mcp", "tool": title}))
    assert [tool["name"].split("/")[1] for tool in listing["tools"]] == ["tool_1", "tool_2"]
    assert len(listing["other_tool_names"]) == len(many) - 2 and listing["usage"] == "Call tool_1 first."
    assert all(len(item["description"]) <= 140 for item in listing["other_tool_names"])
    servers = json.loads(cap.discover({"capability": "mcp"}))["servers"]
    assert servers[0]["usage"] == "Call tool_1 first."
    single = json.loads(cap.discover({"capability": "mcp", "tool": f"{TOKEN_SERVICE}/tool_3"}))
    assert [tool["name"] for tool in single["tools"]] == [many[3]["name"]]
    assert json.loads(cap.discover({"capability": "mcp", "tool": f"{TOKEN_SERVICE}/nope"}))["error"] == "tool_unavailable"
    # Unknown names explain how to proceed instead of a bare refusal.
    unknown = json.loads(cap.discover({"capability": "repositories"}))
    assert unknown["error"] == "unknown_capability" and "mcp" in unknown["hint"]
    guessed = json.loads(cap.execute({"tool": "github_list_repos", "arguments": {}}))
    assert guessed["error"] == "tool_not_allowed" and "troika_tool_search" in guessed["hint"]
