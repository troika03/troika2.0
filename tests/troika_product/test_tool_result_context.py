"""Large results retain byte-exact originals, receipts and tenant guards."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from agent.provider_metering import ProviderCallBlocked, provider_metering_scope
from troika_product.access import AccessRegistry
from troika_product.capabilities import CapabilityStore
from troika_product.working_context import WorkingContext, token_count


@pytest.fixture
def scope(tmp_path):
    registry = AccessRegistry(tmp_path / "accounts.db")
    user = registry.create_user("results@example.invalid")
    device = registry.create_device(user, name="fixture", platform="android")
    token = registry.issue_device_token(device)
    guard = SimpleNamespace(principal=registry.authenticate(token), stopped=False, ledger=SimpleNamespace(registry=registry))
    guard.context = WorkingContext(guard, enabled=True)
    with provider_metering_scope(guard):
        yield registry, token, guard


def request():
    result = {"ok": False, "status": "partial", "error": "Second source timed out",
              "sources": [{"url": "https://example.invalid/source", "status": "read"}],
              "receipt": {"saved": False, "sha256": "f" * 64}, "exact": 123456789.125,
              "text": "Original source paragraph. " * 4000 + "HIDDEN-EXACT-7829"}
    return {"model": "fixture", "messages": [
        {"role": "system", "content": "fixed identity"}, {"role": "user", "content": "Read the source"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call-fixture", "function": {"name": "troika_tool_call", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call-fixture", "content": json.dumps(result)}],
        "tools": [{"function": {"name": name}} for name in ("troika_tool_search", "troika_tool_call")]}


def read_all(context, index):
    parts, offset = [], 0
    while offset is not None:
        page = context.retrieve({"action": "history_read", "index": index, "offset": offset})
        parts.append(page["text"])
        offset = page["next"]
    return "".join(parts)


def test_large_current_result_is_projected_and_original_is_repeatably_readable(scope):
    _, _, guard = scope
    raw = request(); before = deepcopy(raw)
    output = guard.context.prepare(raw, client=SimpleNamespace())
    reference = json.loads(output["messages"][-1]["content"])
    assert reference["kind"] == "tool_result_reference" and reference["partial"]
    assert token_count(output["messages"]) < token_count(raw["messages"]) * .1
    evidence = reference["evidence"]
    assert {"path": "/error", "value": "Second source timed out"} in evidence
    assert {"path": "/exact", "value": "123456789.125", "type": "json_number"} in evidence
    assert {"path": "/receipt/saved", "value": False} in evidence
    assert "https://example.invalid/source" in json.dumps(evidence)
    index = reference["read"]["arguments"]["index"]
    assert read_all(guard.context, index) == read_all(guard.context, index) == raw["messages"][-1]["content"]
    assert raw == before
    found = guard.context.retrieve({"action": "history_search", "query": "HIDDEN-EXACT-7829"})["matches"][0]
    assert found["offset"] > 4000 and "HIDDEN-EXACT-7829" in found["preview"]
    assert "HIDDEN-EXACT-7829" in guard.context.retrieve({"action": "history_read", "index": index, "offset": found["offset"]})["text"]
    raw["messages"].extend([{"role": "assistant", "content": "Partial source read"}, {"role": "user", "content": "Continue"}])
    guard.context.prepare(raw, client=SimpleNamespace())
    assert "HIDDEN-EXACT-7829" in read_all(guard.context, index)


def test_archive_offsets_survive_continuation(scope):
    _, _, guard = scope
    guard.context.archive_messages = [{"role": "user", "content": "older archive"}]
    raw = request()
    output = guard.context.prepare(raw, client=SimpleNamespace())
    index = json.loads(output["messages"][-1]["content"])["read"]["arguments"]["index"]
    assert index == 4
    assert read_all(guard.context, index) == raw["messages"][-1]["content"]


def test_discovery_and_large_evidence_keep_complete_results(scope):
    _, _, guard = scope
    raw = request()
    raw["messages"][-2]["tool_calls"][0]["function"]["name"] = "troika_tool_search"
    assert guard.context.prepare(raw, client=SimpleNamespace())["messages"][-1] == raw["messages"][-1]
    raw = request()
    raw["messages"][-1]["content"] = json.dumps({"error": "Critical error. " * 4000})
    assert guard.context.prepare(raw, client=SimpleNamespace())["messages"][-1] == raw["messages"][-1]


def test_stop_revoke_foreign_account_and_disabled_reader(scope):
    registry, token, guard = scope
    raw = request()
    guard.context.prepare(raw, client=SimpleNamespace())
    with provider_metering_scope(SimpleNamespace(principal=guard.principal)):
        with pytest.raises(ProviderCallBlocked):
            read_all(guard.context, 3)
    guard.stopped = True
    with pytest.raises(ProviderCallBlocked):
        read_all(guard.context, 3)
    guard.stopped = False
    CapabilityStore(registry).update(guard.principal, {"assistant": False})
    assert guard.context.prepare(raw, client=SimpleNamespace()) is raw
    registry.revoke_token(token)
    with pytest.raises(PermissionError):
        read_all(guard.context, 3)


def test_decimal_literals_are_exact_and_ambiguous_json_is_not_reinterpreted(scope):
    _, _, guard = scope
    raw = request()
    source = '{"amount":0.12345678901234567890123456789,"exponent":1.234567890123456789e-40,"body":"' + 'Original prose. ' * 2000 + '"}'
    raw["messages"][-1]["content"] = source
    output = guard.context.prepare(raw, client=SimpleNamespace())
    evidence = json.loads(output["messages"][-1]["content"])["evidence"]
    assert {"path": "/amount", "value": "0.12345678901234567890123456789", "type": "json_number"} in evidence
    assert {"path": "/exponent", "value": "1.234567890123456789e-40", "type": "json_number"} in evidence
    raw["messages"][-1]["content"] = source[:-1] + ',"amount":2}'
    assert guard.context.prepare(raw, client=SimpleNamespace())["messages"][-1] == raw["messages"][-1]


def test_paged_originals_are_never_projected_into_another_reference(scope):
    _, _, guard = scope
    raw = request()
    raw["messages"][-2]["tool_calls"][0]["function"]["arguments"] = json.dumps({
        "tool": "troika_context", "arguments": {"action": "history_read", "index": 1}})
    raw["messages"][-1]["content"] = json.dumps({"text": '\\"' * 4000, "next": 4000})
    assert len(raw["messages"][-1]["content"]) > 8000
    assert guard.context.prepare(raw, client=SimpleNamespace())["messages"][-1] == raw["messages"][-1]
