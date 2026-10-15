"""Derived context retains originals, account scope and metered provider calls."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from agent.provider_metering import ProviderCallBlocked, provider_metering_scope, wrap_provider_client
from troika_product.access import AccessRegistry
from troika_product.memory import MemoryStore
from troika_product.persona import current_persona_marker, load_troika_persona, original_persona
from troika_product.working_context import WorkingContext, purge_owner, token_count


def identity(registry, email):
    user = registry.create_user(email)
    device = registry.create_device(user, name="Fixture", platform="android")
    token = registry.issue_device_token(device)
    return token, registry.authenticate(token)


@pytest.fixture
def scoped(tmp_path):
    registry = AccessRegistry(tmp_path / "accounts.db")
    token, principal = identity(registry, "first@example.com")
    guard = SimpleNamespace(principal=principal, stopped=False, ledger=SimpleNamespace(registry=registry))
    guard.context = WorkingContext(guard, enabled=True)
    with provider_metering_scope(guard):
        yield registry, token, guard
    purge_owner(principal.user_id)


def payload():
    messages = [{"role": "system", "content": "Fixed product identity"}]
    for i in range(18):
        messages.extend([{"role": "user", "content": f"Goal {i}: preserve exact reference REF-{i}-98271. " + "Historical task details. " * 90},
                         {"role": "assistant", "content": f"Confirmed decision {i}. " + "Detailed source response. " * 60}])
    messages.append({"role": "user", "content": "Continue the task; keep REF-2-98271."})
    return {"model": "openrouter/free", "messages": messages, "tools": [
        {"type": "function", "function": {"name": "troika_tool_search"}},
        {"type": "function", "function": {"name": "troika_tool_call"}},
    ]}


def sdk_client():
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


def test_index_reduces_sdk_context_without_extra_calls_or_mutating_originals(scoped):
    _, _, guard = scoped
    before = payload()
    original = deepcopy(before)
    client, calls = sdk_client()
    derived = guard.context.prepare(before, client=client)
    assert before == original
    assert derived["messages"][0] == before["messages"][0]
    assert derived["messages"][-1] == before["messages"][-1]
    assert token_count(derived["messages"]) < token_count(before["messages"])
    assert not calls and guard.context.stats["summary_calls"] == 0
    assert guard.context.stats["index_builds"] == 1
    matches = guard.context.retrieve({"action": "history_search", "query": "REF-2-98271"})
    index = next(m["index"] for m in matches["matches"] if m["role"] == "user")
    page = guard.context.retrieve({"action": "history_read", "index": index})
    assert "REF-2-98271" in page["text"]
    second = WorkingContext(guard, enabled=True)
    second.prepare(before, client=client)
    assert not calls and second.stats["cache_hits"] == 1
    changed = deepcopy(before)
    changed["messages"][1]["content"] += "Correction: use REF-NEW-61832."
    second.prepare(changed, client=client)
    assert not calls and second.stats["index_builds"] == 1


def test_partial_and_omitted_index_entries_can_be_read_in_full(scoped):
    _, _, guard = scoped
    before = payload()
    for i in range(100):
        before["messages"].insert(-1, {"role": "user", "content": f"Source {i}: " + "Exact old details. " * 60})
    client, calls = sdk_client()
    result = guard.context.prepare(before, client=client)
    index_text = result["messages"][1]["content"]
    index = json.loads(index_text.splitlines()[1])["summary"]
    assert index["omitted_user_entries"] > 0 and any(i["partial"] for i in index["items"])
    assert "not a complete retelling" in index_text and not calls
    found = guard.context.retrieve({"action": "history_search", "query": "Source 75:"})
    item = next(m for m in found["matches"] if "Source 75:" in m["preview"])
    original = guard.context.retrieve({"action": "history_read", "index": item["index"]})
    assert original["text"] == before["messages"][item["index"]]["content"]


def test_original_pages_and_persona_remain_available(scoped):
    _, _, guard = scoped
    long_text = "Exact original text " * 800
    guard.context.messages = [{"role": "user", "content": long_text}]
    pages = []
    offset = 0
    while offset is not None:
        page = guard.context.retrieve({"action": "history_read", "index": 1, "offset": offset})
        pages.append(page["text"])
        offset = page["next"]
    assert "".join(pages) == long_text
    assert original_persona().startswith("# Тройка — кто ты")
    assert "## Характер и общение" in original_persona()
    assert current_persona_marker() in load_troika_persona()
    assert token_count(load_troika_persona()) < token_count(original_persona())


def test_completed_large_tool_turn_is_retrievable_and_current_turn_stays_whole(scoped):
    _, _, guard = scoped
    raw = payload()
    raw["messages"].extend([
        {"role": "assistant", "content": None, "tool_calls": [{"id": "past", "type": "function", "function": {"name": "troika_tool_call", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "past", "content": "Exact completed source. " * 5000},
        {"role": "assistant", "content": "Verified conclusion: EXACT-287-619."},
        {"role": "user", "content": "Repeat the verified conclusion."},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "current", "type": "function", "function": {"name": "troika_tool_call", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "current", "content": "Exact current result."},
    ])
    client, calls = sdk_client()
    result = guard.context.prepare(raw, client=client)
    assert result["messages"][-3:] == raw["messages"][-3:]
    assert token_count(result["messages"]) < guard.context.threshold
    assert "Verified conclusion: EXACT-287-619." in result["messages"][1]["content"]
    source_index = next(i for i, m in enumerate(raw["messages"]) if m.get("tool_call_id") == "past")
    page = guard.context.retrieve({"action": "history_read", "index": source_index})
    assert page["text"] == raw["messages"][source_index]["content"][:4000]
    assert page["next"] == 4000 and not calls


def test_single_completed_large_turn_can_be_reduced_on_next_request(scoped):
    _, _, guard = scoped
    raw = payload()
    raw["messages"] = [raw["messages"][0],
                       {"role": "user", "content": "Original large material. " * 7000},
                       {"role": "assistant", "content": "Confirmed reference EXACT-419-632."},
                       {"role": "user", "content": "Continue from the confirmed reference."}]
    client, calls = sdk_client()
    result = guard.context.prepare(raw, client=client)
    assert result["messages"][-1] == raw["messages"][-1]
    assert "EXACT-419-632" in result["messages"][1]["content"]
    assert token_count(result["messages"]) < guard.context.threshold and not calls


def test_revocation_stop_and_foreign_scope_refuse_read(scoped):
    registry, token, guard = scoped
    guard.context.messages = [{"role": "user", "content": "PRIVATE ORIGINAL"}]
    with provider_metering_scope(None):
        with pytest.raises(ProviderCallBlocked):
            guard.context.retrieve({"action": "history_read", "index": 1})
    guard.stopped = True
    with pytest.raises(ProviderCallBlocked):
        guard.context.retrieve({"action": "history_read", "index": 1})
    guard.stopped = False
    registry.revoke_token(token)
    with pytest.raises(PermissionError):
        guard.context.retrieve({"action": "history_read", "index": 1})


def test_unrelated_memory_is_not_in_greeting_but_original_can_be_retrieved(scoped):
    registry, _, guard = scoped
    store = MemoryStore(registry.database_path)
    fact = store.create_memory(guard.principal, title="Размер проекта", content="Точный размер — 287 файлов.")
    preference = store.create_memory(guard.principal, kind="preference", title="Стиль", content="Короткие ответы.")
    _, second = identity(registry, "other@example.com")
    foreign = store.create_memory(second, title="Размер проекта", content="OTHER PRIVATE FACT")
    before = [m.to_dict() for m in store.list_memories(guard.principal)]
    greeting = store.assistant_context(guard.principal, query="Привет", compact=True)
    assert fact.content not in greeting and preference.content in greeting
    relevant = store.assistant_context(guard.principal, query="Какой размер проекта?", compact=True)
    assert fact.content in relevant and "OTHER PRIVATE FACT" not in relevant
    matches = guard.context.retrieve({"action": "memory_search", "query": "размер проекта"})
    assert fact.id in [m["id"] for m in matches["matches"]]
    assert guard.context.retrieve({"action": "memory_read", "memory_id": fact.id})["content"] == fact.content
    with pytest.raises(ValueError):
        guard.context.retrieve({"action": "memory_read", "memory_id": foreign.id})
    assert [m.to_dict() for m in store.list_memories(guard.principal)] == before


def test_metering_reserves_the_derived_payload_and_settles_one_sdk_call(scoped):
    _, _, guard = scoped
    sdk, calls = sdk_client()
    sdk.max_retries = 0
    sdk.base_url = "https://openrouter.ai/api/v1"
    billed = []
    class Lease:
        def succeeded(self, response):
            billed.append("settled")
        def failed(self, error):
            raise error
    guard.prepare_payload = lambda data, client: guard.context.prepare(data, client=client)
    reserved = []
    def begin(data, **kw):
        reserved.append(deepcopy(data))
        return Lease(), data
    guard.begin_call = begin
    client = wrap_provider_client(sdk, provider="openrouter")
    raw = payload()
    client.chat.completions.create(**raw)
    assert len(billed) == len(calls) == len(reserved) == 1
    assert reserved[0] == calls[0]
    assert token_count(calls[-1]["messages"]) < token_count(raw["messages"])


def test_disabled_and_multimodal_payloads_are_untouched(scoped):
    _, _, guard = scoped
    client, calls = sdk_client()
    raw = payload()
    guard.context.enabled = False
    assert guard.context.prepare(raw, client=client) is raw
    guard.context.enabled = True
    client._async_mode = True
    assert guard.context.prepare(raw, client=client) is raw
    client._async_mode = False
    raw["messages"][-1]["content"] = [{"type": "image_url", "image_url": {"url": "fixture"}}]
    assert guard.context.prepare(raw, client=client) is raw
    assert not calls


def test_disabled_reader_keeps_all_history_in_model_request(scoped):
    registry, _, guard = scoped
    from troika_product.capabilities import CapabilityStore
    CapabilityStore(registry).update(guard.principal, {"assistant": False})
    raw = payload()
    client, calls = sdk_client()
    assert guard.context.prepare(raw, client=client) is raw
    assert guard.context.stats["index_builds"] == 0 and not calls


@pytest.mark.parametrize("compact", [True, False])
def test_gateway_passes_full_stored_history_to_compact_scope(tmp_path, monkeypatch, compact):
    import asyncio
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from hermes_state import SessionDB

    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True, "product_auth_db": str(tmp_path / "accounts.db"),
        "product_compact_context_enabled": compact,
    }))
    registry = adapter._access_registry
    token, principal = identity(registry, "history@example.com")
    sid = registry.account_home_session_id(principal)
    db = SessionDB(tmp_path / "sessions.db")
    db.create_session(sid, source="api_server", model="free")
    for i in range(40):
        db.append_message(sid, "user", content=f"Original fact {i}")
        db.append_message(sid, "assistant", content=f"Answer {i}")
    original = db.get_messages_as_conversation(sid)
    adapter._session_db = db
    captured = {}
    async def run(**kwargs):
        captured.update(kwargs)
        return {"final_response": "ok", "messages": [], "session_id": sid}, {}
    monkeypatch.setattr(adapter, "_run_agent", run)
    class Request(dict):
        headers = {"Authorization": "Bearer " + token, "X-Hermes-Session-Id": sid}
        remote, transport, method, path_qs = "127.0.0.1", None, "POST", "/v1/chat/completions"
        async def json(self):
            return {"messages": [{"role": "user", "content": "Recall the first fact"}], "stream": False}
    response = asyncio.run(adapter._handle_chat_completions(Request()))
    assert response.status == 200
    assert any(m["content"] == "Original fact 0" for m in captured["conversation_history"]) is compact
    assert db.get_messages_as_conversation(sid) == original
    db.close()


def test_original_reader_is_discovered_without_widening_initial_model_tools(scoped):
    registry, _, guard = scoped
    from gateway.session_context import clear_session_override, get_session_overrides, set_session_override
    from model_tools import get_tool_definitions
    from troika_product.capabilities import ROUTER_TOOLSET, discover, execute
    old = get_session_overrides()
    values = {"TROIKA_PRODUCT_MODE": "1", "TROIKA_PRODUCT_ACCESS_DB": str(registry.database_path),
              "TROIKA_PRODUCT_USER_ID": guard.principal.user_id,
              "TROIKA_PRODUCT_DEVICE_ID": guard.principal.device_id,
              "TROIKA_PRODUCT_TOKEN_ID": guard.principal.token_id}
    for key, value in values.items():
        set_session_override(key, value)
    try:
        guard.context.messages = [{"role": "user", "content": "Exact original fixture"}]
        definitions = get_tool_definitions(enabled_toolsets=[ROUTER_TOOLSET], quiet_mode=True)
        assert {d["function"]["name"] for d in definitions} == {"troika_tool_search", "troika_tool_call"}
        result = json.loads(discover({"capability": "assistant", "tool": "troika_context"}))
        assert result["ok"] and result["tools"][0]["name"] == "troika_context"
        result = json.loads(execute({"tool": "troika_context", "arguments": {"action": "history_read", "index": 1}}))
        assert result["ok"] and result["result"]["result"]["text"] == "Exact original fixture"
        again = get_tool_definitions(enabled_toolsets=[ROUTER_TOOLSET], quiet_mode=True)
        assert {d["function"]["name"] for d in again} == {"troika_tool_search", "troika_tool_call"}
    finally:
        for key in values:
            if key in old:
                set_session_override(key, old[key])
            else:
                clear_session_override(key)


def test_rotated_archive_indexes_and_cache_stay_with_their_originals(scoped):
    _, _, guard = scoped
    client, _ = sdk_client()
    guard.context.archive_messages = [{"role": "user", "content": "Earlier session REF-ARCHIVE-A."}]
    derived = guard.context.prepare(payload(), client=client)
    summary = json.loads(derived["messages"][1]["content"].splitlines()[1])
    assert summary["original_range"][0] == 2
    for item in summary["summary"]["items"]:
        page = guard.context.retrieve({"action": "history_read", "index": item["index"]})
        assert page["text"].startswith(item["excerpt"])
    guard.context.archive_messages = [{"role": "user", "content": "Different session REF-ARCHIVE-B."}]
    guard.context.prepare(payload(), client=client)
    assert guard.context.stats["cache_hits"] == 0
    assert "REF-ARCHIVE-B" in guard.context.retrieve({"action": "history_read", "index": 1})["text"]


def test_social_turn_rejects_forced_router_actions(scoped, monkeypatch):
    registry, _, guard = scoped
    from gateway.session_context import clear_session_override, set_session_override
    from troika_product.capabilities import discover, execute
    guard.context.conversation_only = True
    values = {"TROIKA_PRODUCT_MODE": "1", "TROIKA_PRODUCT_ACCESS_DB": str(registry.database_path),
              "TROIKA_PRODUCT_USER_ID": guard.principal.user_id,
              "TROIKA_PRODUCT_DEVICE_ID": guard.principal.device_id,
              "TROIKA_PRODUCT_TOKEN_ID": guard.principal.token_id}
    for key, value in values.items():
        set_session_override(key, value)
    try:
        calls = []
        monkeypatch.setattr("model_tools.handle_function_call", lambda *a, **kw: calls.append(a))
        assert json.loads(discover({"capability": "development"}))["error"] == "no_action_requested"
        assert json.loads(execute({"tool": "troika_create_project", "arguments": {}}))["error"] == "no_action_requested"
        assert not calls
    finally:
        for key in values:
            clear_session_override(key)
