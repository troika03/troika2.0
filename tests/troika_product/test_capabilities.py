"""Behaviour checks for owner preferences and deferred product dispatch."""

import asyncio
import json

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter, _safe_product_action_result
from gateway.session_context import clear_session_override, get_session_overrides, set_session_override
from troika_product import capabilities as cap
from troika_product.access import AccessRegistry
from troika_product.completion import CompletionEvidence
from troika_product.web_sources import session_source_metadata, web_source_activity


def identity(registry, email):
    user = registry.create_user(email)
    device = registry.create_device(user, name="Test", platform="windows")
    token = registry.issue_device_token(device)
    return token, registry.authenticate(token)


@pytest.fixture
def owner(tmp_path):
    previous = get_session_overrides()
    registry = AccessRegistry(tmp_path / "access.db")
    token, principal = identity(registry, "one@example.com")
    values = {
        "TROIKA_PRODUCT_MODE": "1", "TROIKA_PRODUCT_ACCESS_DB": str(registry.database_path),
        "TROIKA_PRODUCT_USER_ID": principal.user_id,
        "TROIKA_PRODUCT_DEVICE_ID": principal.device_id,
        "TROIKA_PRODUCT_TOKEN_ID": principal.token_id,
        "TROIKA_PRODUCT_ARTIFACTS_AVAILABLE": "1",
        "TROIKA_PRODUCT_WORKSPACE_AVAILABLE": "1",
    }
    for key, value in values.items():
        set_session_override(key, value)
    yield registry, token, principal
    for key in values:
        if key in previous:
            set_session_override(key, previous[key])
        else:
            clear_session_override(key)


def test_preferences_merge_per_owner_and_survive_another_device(owner):
    registry, _, first = owner
    _, second = identity(registry, "two@example.com")
    store = cap.CapabilityStore(registry)
    assert all(store.preferences(first).values())
    store.update(first, {"web": False})
    result = store.update(first, {"documents": False})
    assert result["web"] is False and result["documents"] is False
    assert store.preferences(second)["web"] is True
    device = registry.create_device(first.user_id, name="Phone", platform="android")
    same_owner = registry.authenticate(registry.issue_device_token(device))
    assert store.preferences(same_owner) == result


@pytest.mark.parametrize("patch", [None, {}, {"web": "false"}, {"terminal": True},
                                       {"user_id": "other"}, {"web": 0}])
def test_preferences_reject_invalid_patches_without_changing_state(owner, patch):
    registry, _, principal = owner
    store = cap.CapabilityStore(registry)
    with pytest.raises(ValueError):
        store.update(principal, patch)
    assert store.preferences(principal)["web"] is True


def test_revoked_identity_cannot_discover_or_execute(owner):
    registry, token, principal = owner
    registry.revoke_token(token)
    with pytest.raises(PermissionError):
        cap.CapabilityStore(registry).update(principal, {"web": False})
    assert json.loads(cap.discover({"capability": "web"}))["error"] == "product_identity_required"
    assert json.loads(cap.execute({"tool": "web_search", "arguments": {}}))["error"] == "product_identity_required"


def test_preferences_are_exported_and_deleted_with_account(owner):
    registry, _, principal = owner
    cap.CapabilityStore(registry).update(principal, {"web": False})
    exported = registry.export_account_rows(principal)
    assert json.loads(exported["capability_preferences"][0]["preferences_json"])["web"] is False
    registry.prepare_account_deletion(principal)
    registry.finalize_account_deletion(principal.user_id)
    with registry._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM troika_capability_preferences").fetchone()[0] == 0


def schema(name):
    return {"name": name, "description": "Example", "parameters": {
        "type": "object", "properties": {"query": {"type": "string"}},
        "required": ["query"], "additionalProperties": False,
    }}


def test_discovery_loads_only_requested_tools_without_execution(owner, monkeypatch):
    monkeypatch.setattr(cap, "available_schemas", lambda: {
        "web_search": schema("web_search"), "troika_create_docx": schema("troika_create_docx"),
    })
    result = json.loads(cap.discover({"capability": "web", "tool": "web_search"}))
    assert result["call_via"] == cap.CALL_TOOL
    assert [tool["name"] for tool in result["tools"]] == ["web_search"]
    assert json.loads(cap.discover({"capability": "web", "tool": "troika_create_docx"}))["ok"] is False


def test_development_instructions_arrive_on_discovery_not_every_greeting(owner, monkeypatch):
    from troika_product.development import DEVELOPMENT_GUIDANCE
    from troika_product.persona import load_troika_persona

    monkeypatch.setattr(cap, "available_schemas", lambda: {
        "troika_create_project": schema("troika_create_project"),
    })
    # Ordinary conversation keeps the original identity and discovery route,
    # while the complete instructions remain available before a project call.
    persona = load_troika_persona()
    assert "Ты — **Тройка**" in persona
    assert "capability development" in persona
    assert DEVELOPMENT_GUIDANCE.strip() not in persona
    result = json.loads(cap.discover({"capability": "development"}))
    assert result["ok"] is True
    assert result["skill"] == DEVELOPMENT_GUIDANCE
    assert result["tools"][0]["name"] == "troika_create_project"


def test_disabling_a_capability_blocks_discovery_and_old_schema_execution(owner, monkeypatch):
    registry, _, principal = owner
    monkeypatch.setattr(cap, "available_schemas", lambda: {"web_search": schema("web_search")})
    assert json.loads(cap.discover({"capability": "web"}))["ok"] is True
    cap.CapabilityStore(registry).update(principal, {"web": False})
    assert json.loads(cap.discover({"capability": "web"}))["error"] == "capability_disabled"
    assert json.loads(cap.execute({"tool": "web_search", "arguments": {"query": "hi"}}))["error"] == "capability_disabled"


@pytest.mark.parametrize("tool", ["terminal", "execute_code", "find_tool", "delegate_task",
                                "troika_tool_call", "android_tap", "pc_run"])
def test_gateway_cannot_widen_product_allowlist(owner, tool):
    assert json.loads(cap.execute({"tool": tool, "arguments": {}}))["error"] == "tool_not_allowed"


def test_dispatch_validates_schema_and_preserves_external_data_boundary(owner, monkeypatch):
    from model_tools import registry
    entry = registry.get_entry("web_search")
    calls = []
    monkeypatch.setattr(cap, "available_schemas", lambda: {"web_search": schema("web_search")})
    def handler(args, **kwargs):
        calls.append(args)
        return json.dumps({"success": True, "data": {"web": [
            {"url": "https://example.com/report", "title": "Source"}
        ]}})
    monkeypatch.setattr(entry, "handler", handler)
    assert json.loads(cap.execute({"tool": "web_search", "arguments": {"query": 12}}))["ok"] is False
    assert calls == []
    args = {"tool": "web_search", "arguments": {"query": "hi"}}
    raw = cap.execute(args)
    assert raw.startswith('<untrusted_tool_result source="web_search">')
    assert calls == [{"query": "hi"}]
    activity = web_source_activity(cap.CALL_TOOL, args=args, result=raw)
    assert activity["sources"][0]["url"] == "https://example.com/report"
    rows = [
        {"role": "user", "content": "search"},
        {"role": "assistant", "tool_calls": [{"id": "one", "function": {
            "name": cap.CALL_TOOL, "arguments": json.dumps(args)}}]},
        {"role": "tool", "tool_call_id": "one", "tool_name": cap.CALL_TOOL, "content": raw},
        {"role": "assistant", "content": "result"},
    ]
    assert session_source_metadata(rows)[3]["sources"] == activity["sources"]


def test_document_receipts_and_delivery_metadata_survive_routing():
    args = {"tool": "troika_create_docx", "arguments": {"filename": "report.docx"}}
    payload = {"ok": True, "artifact": {"id": "one", "filename": "report.docx", "storage": "device"}}
    raw = json.dumps({"ok": True, "routed_tool": "troika_create_docx", "result": payload})
    evidence = CompletionEvidence()
    evidence.record(cap.CALL_TOOL, json.dumps(args), raw)
    assert evidence.device_file_pending
    assert "report.docx" in evidence.filenames
    assert _safe_product_action_result(cap.CALL_TOOL, raw)["artifact"]["id"] == "one"
    # Discovery, mismatch and a failed dispatch cannot prove creation.
    empty = CompletionEvidence()
    empty.record(cap.SEARCH_TOOL, {}, raw)
    empty.record(cap.CALL_TOOL, {"tool": "web_search", "arguments": {}}, raw)
    empty.record(cap.CALL_TOOL, args, json.dumps({"ok": False, "error": "tool_unavailable"}))
    empty.record(cap.CALL_TOOL, args, json.dumps({
        "ok": False, "routed_tool": "troika_create_docx", "result": payload,
    }))
    assert not any(receipt[2] for receipt in empty.receipts.values())
    assert not empty.device_file_pending


def test_deferred_schemas_reduce_request_footprint_without_deleting_tools(owner):
    from model_tools import registry
    import tiktoken
    encoding = tiktoken.get_encoding("cl100k_base")
    full = [{"type": "function", "function": registry.get_schema(tool)}
            for item in cap.CAPABILITIES if item.id != "screen"
            for tool in item.tools if registry.get_schema(tool) is not None]
    small = [{"type": "function", "function": cap.SEARCH_SCHEMA},
             {"type": "function", "function": cap.CALL_SCHEMA}]
    before = len(encoding.encode(json.dumps(full, ensure_ascii=False)))
    after = len(encoding.encode(json.dumps(small, ensure_ascii=False)))
    assert after < before / 3
    # Only aggregate counters, never prompt text or account content.
    print(f"Product schema estimate (cl100k_base): full={before}, deferred={after}")


def test_tool_progress_retains_underlying_name_and_args():
    observed = []
    callback = cap.wrap_progress(lambda *args, **kwargs: observed.append((args, kwargs)))
    args = {"tool": "web_extract", "arguments": {"urls": ["https://example.com"]}}
    callback("tool.started", cap.CALL_TOOL, "", args)
    assert observed[0][0][1] == "web_extract"
    assert observed[0][0][3] == args["arguments"]


def test_product_gateway_plugin_loads_and_schemas_remain_stable(owner):
    from model_tools import get_tool_definitions
    before = get_tool_definitions(enabled_toolsets=[cap.ROUTER_TOOLSET], quiet_mode=True)
    assert {tool["function"]["name"] for tool in before} == {cap.SEARCH_TOOL, cap.CALL_TOOL}
    registry, _, principal = owner
    cap.CapabilityStore(registry).update(principal, {"web": False})
    after = get_tool_definitions(enabled_toolsets=[cap.ROUTER_TOOLSET], quiet_mode=True)
    assert before == after
    assert len(json.dumps(before)) < 2400  # Budget for gateway, not entire tool catalogue.


def test_every_reviewed_product_tool_remains_in_the_catalogue():
    from toolsets import resolve_toolset
    assert set(resolve_toolset("troika-product")) <= set(cap.TOOL_CAPABILITY)
    assert not set(cap.TOOL_CAPABILITY).intersection(cap.FORBIDDEN_PRODUCT_TOOLS)


class Request(dict):
    def __init__(self, token, body=None):
        self.headers = {"Authorization": f"Bearer {token}"}
        self.method = "PATCH" if body is not None else "GET"
        self.body = body
        self.remote = "127.0.0.1"
        self.transport = None
        self.path_qs = "/v1/account/capabilities"
    async def json(self):
        return self.body


def test_catalogue_api_checks_auth_and_keeps_owner_patch_isolated(tmp_path, monkeypatch):
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True, "product_auth_db": str(tmp_path / "access.db"),
        "product_artifact_root": str(tmp_path / "files"),
        "product_workspace_root": str(tmp_path / "workspace"),
    }))
    registry = adapter._access_registry
    first, _ = identity(registry, "one@example.com")
    second, _ = identity(registry, "two@example.com")
    monkeypatch.setattr("troika_product.capability_api.available_schemas",
                        lambda: {"web_search": schema("web_search")})
    response = asyncio.run(adapter._handle_product_capabilities(Request(first, {"enabled": {"web": False}})))
    assert response.status == 200
    assert response.headers["Cache-Control"] == "no-store"
    result = json.loads(response.text)
    assert next(item for item in result["capabilities"] if item["id"] == "web")["enabled"] is False
    response = asyncio.run(adapter._handle_product_capabilities(Request(second)))
    assert next(item for item in json.loads(response.text)["capabilities"] if item["id"] == "web")["enabled"] is True
    response = asyncio.run(adapter._handle_product_capabilities(Request(first, {"enabled": None})))
    assert response.status == 400
    response = asyncio.run(adapter._handle_product_capabilities(Request("invalid")))
    assert response.status == 401
    assert get_session_overrides().get("TROIKA_PRODUCT_USER_ID", "") == ""
