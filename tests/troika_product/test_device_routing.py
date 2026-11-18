"""A model cannot move a phone task to a PC without a current user request."""

from types import SimpleNamespace
import json

import pytest

from troika_product.device_routing import control_arguments, requested_target, route_context

SCHEMA = {"name": "troika_device_control", "parameters": {
    "type": "object", "properties": {"action": {"type": "string"}, "device": {"type": "string"}},
    "required": ["action"], "additionalProperties": False,
}}


@pytest.mark.parametrize("message,target", [
    ("Открой Telegram и напиши черновик", "this"),
    ("С телефона открой и напиши текст", "this"),
    ("Открой на ПК и напиши текст", "pc"),
    ("С телефона открой на моём компьютере", "pc"),
    ("Управляй телефоном", "phone"),
    ("Открой на телефоне", "phone"),
    ('Напиши текст «открой на ПК»', "this"),
    ("Открой здесь, не на ПК", "this"),
    ("Open on my laptop", "pc"),
    ("Открой на телефоне и на ПК", "ambiguous"),
    (None, "this"),
])
def test_destination_comes_only_from_the_current_request(message, target):
    assert requested_target(message) == target


@pytest.mark.parametrize("origin,other", [("phone", "pc"), ("pc", "phone")])
def test_default_cannot_move_to_another_online_device(origin, other):
    args, error = control_arguments({"action": "look", "device": other}, {"origin": origin, "target": "this"})
    assert args is None and error["error"] == "device_target_mismatch"
    args, error = control_arguments({"action": "look", "device": origin}, {"origin": origin, "target": "this"})
    assert error is None and args["device"] == "this"


def test_explicit_cross_device_target_and_same_device_identity():
    args, error = control_arguments({"action": "look"}, {"origin": "phone", "target": "pc"})
    assert error is None and args["device"] == "pc"
    args, error = control_arguments({"action": "look", "device": "phone"}, {"origin": "phone", "target": "phone"})
    assert error is None and args["device"] == "this"


def test_ambiguous_target_cannot_execute():
    args, error = control_arguments({"action": "look"}, {"origin": "phone", "target": "ambiguous"})
    assert args is None and error["error"] == "device_target_ambiguous"


def test_origin_uses_authenticated_device_even_when_pc_is_listed_first():
    registry = SimpleNamespace(list_devices=lambda _: [
        SimpleNamespace(id="pc", platform="windows", status="active"),
        SimpleNamespace(id="phone", platform="android", status="active"),
    ])
    assert route_context(registry, SimpleNamespace(device_id="phone")) == {"origin": "phone", "target": "this"}


def test_gateway_rejects_wrong_target_before_dispatch(monkeypatch):
    from troika_product import capabilities as cap
    import model_tools

    principal = SimpleNamespace(device_id="phone")
    registry = SimpleNamespace(list_devices=lambda _: [SimpleNamespace(id="phone", platform="android", status="active")])
    monkeypatch.setattr(cap, "session_identity", lambda: (registry, principal))
    monkeypatch.setattr(cap.CapabilityStore, "preferences", lambda *_: {"control": True})
    monkeypatch.setattr(cap, "available_schemas", lambda: {"troika_device_control": SCHEMA})
    monkeypatch.setitem(cap.TOOL_CAPABILITY, "troika_device_control", "control")
    monkeypatch.setattr(model_tools, "handle_function_call", lambda *a, **k: pytest.fail("wrong device was dispatched"))
    result = json.loads(cap.execute({"tool": "troika_device_control", "arguments": {"action": "look", "device": "pc"}}))
    assert result["error"] == "device_target_mismatch"


def test_unavailable_screenshot_suggests_control_only_when_enabled(monkeypatch):
    from troika_product import capabilities as cap

    monkeypatch.setattr(cap, "session_identity", lambda: (None, None))
    prefs = {"screen": True, "control": True}
    monkeypatch.setattr(cap.CapabilityStore, "preferences", lambda *_: prefs)
    monkeypatch.setattr(cap, "available_schemas", lambda: {"troika_device_control": SCHEMA})
    monkeypatch.setitem(cap.TOOL_CAPABILITY, "troika_device_control", "control")
    assert "capability=control" in json.loads(cap.discover({"capability": "screen"}))["hint"]
    prefs["control"] = False
    assert "hint" not in json.loads(cap.discover({"capability": "screen"}))


def test_product_stops_repeated_failures_early_but_allows_corrected_arguments():
    from agent.tool_guardrails import ToolCallGuardrailController
    from troika_product.agent_policy import install_agent_policy

    agent = SimpleNamespace(_tool_guardrails=ToolCallGuardrailController())
    install_agent_policy(agent, {})
    guard = agent._tool_guardrails
    args = {"tool": "android_open_app", "arguments": {"app": "fixture"}}
    for _ in range(2):
        guard.after_call("troika_tool_call", args, '{"ok":false}', failed=True)
    assert not guard.before_call("troika_tool_call", args).allows_execution
    assert guard.before_call("troika_tool_call", {**args, "arguments": {"app": "corrected"}}).allows_execution
