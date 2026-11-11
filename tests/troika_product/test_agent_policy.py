"""Product gateway loops and finite agent runs preserve account boundaries."""

import asyncio
import json
import threading
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from agent.provider_metering import ProviderCallBlocked, current_provider_guard
from agent.tool_guardrails import ToolCallGuardrailController
from troika_product.access import AccessRegistry
from troika_product.agent_policy import AgentDeadline, guardrail_call, install_agent_policy
from troika_product.own_provider import OwnCredentials, OwnProviderRuntime
from troika_product.resource_runtime import ResourceRuntime


@pytest.fixture
def clock(monkeypatch):
    now = [100.0]
    timers = []

    class Timer:
        def __init__(self, seconds, callback):
            self.seconds = seconds
            self.callback = callback
            self.cancelled = False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr("troika_product.agent_policy.time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr("troika_product.agent_policy.threading.Timer", Timer)
    return now, timers


@pytest.fixture
def account(tmp_path):
    registry = AccessRegistry(tmp_path / "accounts.db")
    user = registry.create_user("agent-policy@example.invalid", plan="free")
    device = registry.create_device(user, name="fixture", platform="android")
    principal = registry.authenticate(registry.issue_device_token(device))
    return registry, principal


def routed(tool, arguments):
    return {"tool": tool, "arguments": arguments}


def controller(config=None):
    agent = SimpleNamespace(_tool_guardrails=ToolCallGuardrailController())
    install_agent_policy(agent, config or {})
    return agent._tool_guardrails


def test_product_gateway_failures_belong_to_the_actual_tool():
    guard = controller()
    search = routed("web_search", {"query": "fixture"})
    for _ in range(5):
        guard.after_call("troika_tool_call", search, '{"ok":false}', failed=True)
    blocked = guard.before_call("troika_tool_call", search)
    assert blocked.code == "repeated_exact_failure_block"
    assert blocked.tool_name == "web_search"
    assert guard.before_call("troika_tool_call", routed("web_extract", {"url": "fixture"})).allows_execution
    assert guard.before_call("troika_tool_call", routed("web_search", {"query": "changed"})).allows_execution


def test_product_read_repeats_stop_but_successful_mutations_do_not():
    guard = controller()
    read = routed("troika_assistant", {"action": "memory_list"})
    write = routed("troika_assistant", {"action": "memory_add", "content": "fixture"})
    for _ in range(5):
        guard.after_call("troika_tool_call", read, '{"ok":true,"result":[]}', failed=False)
        guard.after_call("troika_tool_call", write, '{"ok":true}', failed=False)
    assert guard.before_call("troika_tool_call", read).code == "idempotent_no_progress_block"
    assert guard.before_call("troika_tool_call", write).allows_execution


def test_rediscovery_loop_is_bounded_and_explicit_product_override_preserved():
    for enabled in (True, False):
        guard = controller({"product_tool_loop_guardrails_enabled": enabled})
        for _ in range(5):
            guard.after_call("troika_tool_search", {"capability": "documents"}, '{"tools":[]}', failed=False)
        assert guard.before_call("troika_tool_search", {"capability": "documents"}).allows_execution is not enabled
    assert ToolCallGuardrailController().config.hard_stop_enabled is False


def test_routed_json_object_and_object_arguments_have_the_same_signature():
    guard = controller()
    obj = routed("web_search", {"query": "fixture"})
    encoded = routed("web_search", json.dumps({"query": "fixture"}))
    assert guard.before_call("troika_tool_call", obj).signature == guard.before_call("troika_tool_call", encoded).signature


@pytest.mark.parametrize("arguments", ['not json', '[1,2]', '{broken', '{"query":"' + "x" * 1048576 + '"}'],
                         ids=["plain-text", "array", "broken-json", "oversized-object"])
def test_invalid_or_oversized_gateway_json_keeps_the_outer_identity(arguments):
    name, result = guardrail_call("troika_tool_call", routed("web_search", arguments))
    assert name == "troika_tool_call"
    assert result["arguments"] == arguments


def test_unknown_or_forbidden_names_are_not_reclassified_as_safe_reads():
    name, _ = guardrail_call("troika_tool_call", routed("terminal", {"command": "fixture"}))
    assert name == "troika_tool_call"
    name, _ = guardrail_call("troika_tool_call", routed("troika_assistant", {"action": "memory_delete"}))
    assert name == "troika_assistant"


def test_resolving_a_gateway_never_authorizes_or_executes_it(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Telemetry resolution must not execute a handler")
    monkeypatch.setattr("troika_product.capabilities.session_identity", forbidden)
    assert guardrail_call("troika_tool_call", routed("web_search", {"query": "fixture"}))[0] == "web_search"


def test_gateway_outcomes_use_the_execution_envelope_not_words_in_result_text():
    guard = controller()
    failed_call = routed("troika_assistant", {"action": "memory_add", "content": "fixture"})
    successful_call = routed("troika_assistant", {"action": "task_add", "title": "fixture"})
    for _ in range(5):
        guard.after_call("troika_tool_call", failed_call, '{"ok":false,"result":{"success":false}}', failed=False)
        guard.after_call("troika_tool_call", successful_call,
                         json.dumps({"ok": True, "result": {"content": 'example code: "error": false'}}),
                         failed=True)
    assert guard.before_call("troika_tool_call", failed_call).code == "repeated_exact_failure_block"
    assert guard.before_call("troika_tool_call", successful_call).allows_execution


def test_product_halt_is_understandable_without_exposing_internal_tool_names():
    from run_agent import AIAgent

    agent = SimpleNamespace(_tool_guardrails=controller())
    call = routed("web_search", {"query": "fixture"})
    for _ in range(5):
        agent._tool_guardrails.after_call("troika_tool_call", call, '{"ok":false}', failed=False)
    decision = agent._tool_guardrails.before_call("troika_tool_call", call)
    response = AIAgent._toolguard_controlled_halt_response(agent, decision)
    assert "остановила" in response and "не подтверждено" in response
    assert "web_search" not in response and "guardrail" not in response


@pytest.mark.parametrize("seconds", [0, -1, 86401, True, 1.5, "30"])
def test_deadline_rejects_unbounded_or_ambiguous_settings(seconds):
    with pytest.raises(ValueError, match="agent timeout"):
        AgentDeadline(seconds)


def test_deadline_starts_on_binding_and_cannot_be_extended_by_rebinding(clock):
    now, timers = clock
    calls = []
    deadline = AgentDeadline(30)
    now[0] += 4000
    deadline.check()
    assert timers == []
    deadline.bind(lambda: calls.append("first"))
    now[0] += 20
    deadline.bind(lambda: calls.append("second"))
    assert len(timers) == 1
    now[0] += 10
    with pytest.raises(ProviderCallBlocked) as error:
        deadline.check()
    assert error.value.code == "resource_run_deadline_exceeded"
    assert calls == ["first", "second"]
    assert timers[0].cancelled


def test_closed_deadline_suppresses_a_late_timer_callback(clock):
    now, timers = clock
    calls = []
    deadline = AgentDeadline(30)
    deadline.bind(lambda: calls.append("late"))
    deadline.close()
    now[0] += 100
    timers[0].callback()
    deadline.check()
    assert calls == [] and timers[0].cancelled


def test_deadline_callback_can_coordinate_with_another_thread_reading_deadline(clock):
    now, timers = clock
    deadline = AgentDeadline(30)
    observed = threading.Event()

    def read_deadline():
        try:
            deadline.check()
        except ProviderCallBlocked:
            observed.set()

    def interrupt():
        reader = threading.Thread(target=read_deadline, daemon=True)
        reader.start()
        assert observed.wait(2), "Interrupt callbacks must not hold the deadline state lock"
        reader.join(2)
        deadline.close()

    deadline.bind(interrupt)
    now[0] += 30
    timers[0].callback()
    assert observed.is_set()


@pytest.mark.parametrize("personal", [False, True])
def test_expired_agent_blocks_tools_payloads_and_models_without_releasing_sent_holds(account, clock, personal):
    registry, principal = account
    now, timers = clock
    kwargs = {"run_key": "finite-agent", "config": {"product_agent_timeout_seconds": 30}}
    if personal:
        runtime = OwnProviderRuntime(registry, principal, **kwargs,
            credentials=OwnCredentials("openrouter", "fixture/model", "personal-fixture-key-1234"))
    else:
        runtime = ResourceRuntime(registry, principal, **kwargs)
    calls = []
    runtime.start()
    try:
        runtime.bind_agent_deadline(SimpleNamespace(interrupt=lambda: calls.append("stopped")))
        hold = runtime.ledger.reserve(principal, operation_key="sent", run_key="finite-agent",
            kind="llm", tokens=12, pricing_version="fixture")
        runtime.ledger.mark_dispatched(principal, hold.id)
        before = runtime.ledger.summary(principal)["reserved"]
        now[0] += 30
        timers[0].callback()
        assert runtime.stopped and calls == ["stopped"]
        for operation in (
            lambda: runtime.begin_tool("troika_assistant", {"action": "memory_add"}),
            lambda: runtime.prepare_payload({}, client=None),
            lambda: runtime.begin_call({}, provider="openrouter", base_url="https://openrouter.ai/api/v1"),
        ):
            with pytest.raises(ProviderCallBlocked) as error:
                operation()
            assert error.value.code == "resource_run_deadline_exceeded"
        assert runtime.ledger.summary(principal)["reserved"] == before
    finally:
        runtime.finish()
    assert runtime.ledger.summary(principal)["reserved"] == before


def test_user_stop_is_not_later_reclassified_as_a_deadline(account, clock):
    registry, principal = account
    now, timers = clock
    runtime = ResourceRuntime(registry, principal, run_key="user-stop", config={"product_agent_timeout_seconds": 30})
    runtime.bind_agent_deadline(SimpleNamespace(interrupt=lambda: pytest.fail("Explicit Stop owns interruption")))
    runtime.block_pending_calls()
    now[0] += 100
    timers[0].callback()
    runtime.check_deadline()
    with pytest.raises(ProviderCallBlocked) as error:
        runtime.begin_tool("troika_assistant", {"action": "memory_list"})
    assert error.value.code == "resource_run_stopped"
    runtime.finish()


def test_background_development_without_bound_agent_keeps_its_existing_deadline(account, clock):
    registry, principal = account
    now, timers = clock
    runtime = ResourceRuntime(registry, principal, run_key="background", config={"product_agent_timeout_seconds": 30})
    runtime.start()
    try:
        now[0] += 10000
        runtime.check_deadline()
        assert not runtime.stopped and timers == []
    finally:
        runtime.finish()


def test_api_scope_rejects_a_returned_result_after_deadline_and_cleans_up(tmp_path, clock, monkeypatch):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    now, timers = clock
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True,
        "product_auth_db": str(tmp_path / "scope.db"),
        "product_resource_enabled": True,
        "product_agent_timeout_seconds": 30,
    }))
    registry = adapter._access_registry
    user = registry.create_user("scope@example.invalid", plan="free")
    device = registry.create_device(user, name="fixture", platform="android")
    principal = registry.authenticate(registry.issue_device_token(device))
    calls = []

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def interrupt(self):
            calls.append("stopped")

    monkeypatch.setattr("run_agent.AIAgent", FakeAgent)
    monkeypatch.setattr("gateway.run._resolve_runtime_agent_kwargs", lambda: {})
    monkeypatch.setattr("gateway.run._resolve_gateway_model", lambda: "fixture/model")
    monkeypatch.setattr("gateway.run._load_gateway_config", lambda: {})
    monkeypatch.setattr("gateway.run.GatewayRunner._load_reasoning_config", staticmethod(lambda: None))
    monkeypatch.setattr("gateway.run.GatewayRunner._load_fallback_model", staticmethod(lambda: None))
    monkeypatch.setattr("hermes_cli.tools_config._get_platform_tools", lambda *_: set())
    monkeypatch.setattr(adapter, "_ensure_session_db", lambda: None)
    with pytest.raises(ProviderCallBlocked) as error:
        with adapter._resource_call_scope(principal, "scope-deadline"):
            runtime = current_provider_guard()
            agent = adapter._create_agent(current_user_message="Найди сведения о тестовом проекте")
            assert agent._tool_guardrails.config.hard_stop_enabled
            assert len(timers) == 1
            now[0] += 30
    assert error.value.code == "resource_run_deadline_exceeded"
    assert calls == ["stopped"] and timers[0].cancelled
    assert adapter._active_resource_guards == {}
    assert current_provider_guard() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["chat", "runs"])
async def test_expired_stream_keeps_narration_but_never_emits_success(tmp_path, clock, monkeypatch, endpoint):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    now, timers = clock
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True,
        "product_auth_db": str(tmp_path / "stream.db"),
        "product_artifact_root": str(tmp_path / "artifacts"),
        "product_workspace_root": str(tmp_path / "workspaces"),
        "product_quotas_enabled": False,
        "product_resource_enabled": True,
        "product_agent_timeout_seconds": 30,
    }))
    registry = adapter._access_registry
    user = registry.create_user("deadline@example.invalid", plan="free")
    token = registry.issue_device_token(registry.create_device(user, name="Phone", platform="android"))
    narration = "Подбираю пример. "
    claim = "Файл сохранён."
    interrupts = []

    def create(**options):
        callback = options["stream_delta_callback"]

        def run(**kwargs):
            callback(narration)
            callback(claim + " ")
            now[0] += 30
            return {"final_response": narration + claim, "completed": True}

        agent = SimpleNamespace(run_conversation=run, interrupt=lambda: interrupts.append(True))
        current_provider_guard().bind_agent_deadline(agent)
        return agent

    monkeypatch.setattr(adapter, "_create_agent", create)
    app = web.Application()
    app.router.add_post("/v1/chat/completions", adapter._handle_chat_completions)
    app.router.add_post("/v1/runs", adapter._handle_runs)
    app.router.add_get("/v1/runs/{run_id}/events", adapter._handle_run_events)
    headers = {"Authorization": "Bearer " + token}
    user_input = "Подготовь текстовый файл"
    async with TestClient(TestServer(app)) as client:
        if endpoint == "chat":
            response = await client.post("/v1/chat/completions", headers=headers, json={
                "messages": [{"role": "user", "content": user_input}], "stream": True,
            })
        else:
            started = await client.post("/v1/runs", headers=headers, json={"input": user_input})
            assert started.status == 202
            run_id = (await started.json())["run_id"]
            response = await client.get(f"/v1/runs/{run_id}/events", headers=headers)
        assert response.status == 200
        body = await asyncio.wait_for(response.text(), 5)

    payloads = [json.loads(line[6:]) for line in body.splitlines()
                if line.startswith("data: ") and line != "data: [DONE]"]
    if endpoint == "chat":
        deltas = [event["choices"][0]["delta"].get("content", "") for event in payloads]
        assert payloads[-1]["choices"][0]["finish_reason"] == "error"
        failure = payloads[-1]["hermes"]
    else:
        deltas = [event["delta"] for event in payloads if event.get("event") == "message.delta"]
        assert all(event.get("event") != "run.completed" for event in payloads)
        failure, = [event for event in payloads if event.get("event") == "run.failed"]
        assert adapter._run_statuses[run_id]["error_code"] == failure["error_code"]
    assert "".join(deltas) == narration
    assert failure["error_code"] == "resource_run_deadline_exceeded"
    assert interrupts == [True] and timers[0].cancelled
