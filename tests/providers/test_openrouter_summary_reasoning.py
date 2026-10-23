"""Offline final-wire checks for ordinary and iteration-limit summary calls."""

from decimal import Decimal
import json
from types import SimpleNamespace

import httpx
from openai import OpenAI
import pytest

from agent.chat_completion_helpers import handle_max_iterations
from agent.lmstudio_reasoning import resolve_lmstudio_effort
from agent.provider_metering import provider_metering_scope, wrap_provider_client
from agent.transports.chat_completions import ChatCompletionsTransport
from providers import get_provider_profile
from troika_product.access import AccessRegistry
from troika_product.llm_metering import LLMMeter, ModelPrice, PriceCatalogue
from troika_product.resource_ledger import ResourceLedger
from troika_product.subscription_policy import TokenPrices


MODEL = "openrouter/free"
MESSAGES = [{"role": "user", "content": "Синтетическая проверка сводки."}]
PREFERENCES = {"only": ["fixture-provider"], "ignore": ["ignored-provider"],
               "order": ["fixture-provider"], "sort": "latency"}


def bare_agent(client, configured, *, supports=False, preferences=False):
    """Skip AIAgent initialization and its optional external metadata lookups."""
    transport = ChatCompletionsTransport()
    return SimpleNamespace(
        model=MODEL, provider="openrouter", base_url="https://openrouter.ai/api/v1",
        _base_url_lower="https://openrouter.ai/api/v1", api_mode="chat_completions",
        reasoning_config=configured, max_tokens=128, max_iterations=2,
        _cached_system_prompt="Synthetic public system.", ephemeral_system_prompt=None,
        prefill_messages=[], session_id="synthetic-session", openrouter_min_coding_score=None,
        providers_allowed=PREFERENCES["only"] if preferences else [],
        providers_ignored=PREFERENCES["ignore"] if preferences else [],
        providers_order=PREFERENCES["order"] if preferences else [],
        provider_sort=PREFERENCES["sort"] if preferences else None,
        _should_sanitize_tool_calls=lambda: False,
        _copy_reasoning_content_for_api=lambda source, target: None,
        _sanitize_api_messages=lambda messages: messages,
        _drop_thinking_only_and_merge_users=lambda messages: messages,
        _supports_reasoning_extra_body=lambda: supports,
        _is_openrouter_url=lambda: True,
        _max_tokens_param=lambda count: {"max_tokens": count},
        _get_transport=lambda: transport,
        _ensure_primary_openai_client=lambda **kwargs: client,
        _interruptible_api_call=lambda kwargs: client.chat.completions.create(**kwargs),
    )


def response(payload, content="Синтетическая сводка.", *, usage=True):
    result = {"id": "synthetic-completion", "object": "chat.completion", "created": 0,
              "model": payload["model"], "choices": [{"index": 0,
                  "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}]}
    if usage:
        result["usage"] = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12, "cost": 0}
    return httpx.Response(200, json=result)


@pytest.mark.parametrize("configured", [{"enabled": False}, {"effort": "low"}])
@pytest.mark.parametrize("retry_empty_summary", [False, True])
def test_explicit_reasoning_matches_normal_and_every_summary_wire_request(configured, retry_empty_summary):
    wire = []
    original = dict(configured)

    def handler(request):
        payload = json.loads(request.content)
        wire.append(payload)
        content = "" if retry_empty_summary and len(wire) == 2 else "Синтетическая сводка."
        return response(payload, content)

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http_client:
        with OpenAI(api_key="synthetic-key", base_url="https://openrouter.ai/api/v1",
                    http_client=http_client, max_retries=0) as client:
            agent = bare_agent(client, configured, preferences=True)
            normal = ChatCompletionsTransport().build_kwargs(
                model=MODEL, messages=MESSAGES, tools=None, max_tokens=128,
                provider_profile=get_provider_profile("openrouter"), supports_reasoning=False,
                reasoning_config=configured, provider_preferences=PREFERENCES,
            )
            client.chat.completions.create(**normal)
            result = handle_max_iterations(agent, [dict(message) for message in MESSAGES], 2)
    assert result == "Синтетическая сводка."
    assert len(wire) == (3 if retry_empty_summary else 2)
    assert wire[0]["reasoning"] == configured
    assert all(payload["provider"] == PREFERENCES for payload in wire)
    assert all("tools" not in payload for payload in wire[1:])
    assert configured == original
    assert [payload.get("reasoning") for payload in wire[1:]] == [configured] * (len(wire) - 1)


@pytest.mark.parametrize("supports", [False, True])
def test_omitted_summary_reasoning_keeps_existing_capability_defaults(supports):
    wire = []

    def handler(request):
        payload = json.loads(request.content)
        wire.append(payload)
        return response(payload)

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http_client:
        with OpenAI(api_key="synthetic-key", base_url="https://openrouter.ai/api/v1",
                    http_client=http_client, max_retries=0) as client:
            result = handle_max_iterations(bare_agent(client, None, supports=supports),
                                           [dict(message) for message in MESSAGES], 2)
    assert result == "Синтетическая сводка." and len(wire) == 1
    expected = {"enabled": True, "effort": "medium"} if supports else None
    assert wire[0].get("reasoning") == expected


@pytest.mark.parametrize("provider", ["openai", "fixture-unknown-provider"])
@pytest.mark.parametrize("supports", [False, True])
def test_other_providers_keep_legacy_explicit_reasoning_gate(provider, supports):
    wire = []
    configured = {"enabled": False}

    def handler(request):
        payload = json.loads(request.content)
        wire.append(payload)
        return response(payload)

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http_client:
        with OpenAI(api_key="synthetic-key", base_url="https://fixture.invalid/v1",
                    http_client=http_client, max_retries=0) as client:
            agent = bare_agent(client, configured, supports=supports)
            agent.provider = provider
            agent.base_url = agent._base_url_lower = "https://fixture.invalid/v1"
            agent._is_openrouter_url = lambda: False
            result = handle_max_iterations(agent, [dict(message) for message in MESSAGES], 2)
    assert result == "Синтетическая сводка." and len(wire) == 1
    assert wire[0].get("reasoning") == (configured if supports else None)
    assert "reasoning_effort" not in wire[0] and "provider" not in wire[0]


@pytest.mark.parametrize("configured, expected", [
    ({"enabled": False}, "none"), ({"effort": "low"}, "low"), ({"effort": "high"}, None),
])
def test_lmstudio_summary_and_retry_keep_top_level_effort_and_capability_clamping(configured, expected):
    wire = []
    options = ["off", "low"]

    def handler(request):
        payload = json.loads(request.content)
        wire.append(payload)
        return response(payload, "" if len(wire) == 2 else "Синтетическая сводка.")

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http_client:
        with OpenAI(api_key="synthetic-key", base_url="https://fixture.invalid/v1",
                    http_client=http_client, max_retries=0) as client:
            normal = ChatCompletionsTransport().build_kwargs(
                model="fixture-local-model", messages=MESSAGES, tools=None,
                is_lmstudio=True, supports_reasoning=True, reasoning_config=configured,
                lmstudio_reasoning_options=options,
            )
            client.chat.completions.create(**normal)
            agent = bare_agent(client, configured, supports=True)
            agent.provider, agent.model = "lmstudio", "fixture-local-model"
            agent.base_url = agent._base_url_lower = "https://fixture.invalid/v1"
            agent._is_openrouter_url = lambda: False
            agent._resolve_lmstudio_summary_reasoning_effort = lambda: resolve_lmstudio_effort(configured, options)
            result = handle_max_iterations(agent, [dict(message) for message in MESSAGES], 2)
    assert result == "Синтетическая сводка." and len(wire) == 3
    assert [payload.get("reasoning_effort") for payload in wire] == [expected] * 3
    assert all("reasoning" not in payload and "provider" not in payload for payload in wire)


@pytest.fixture
def meter(tmp_path):
    registry = AccessRegistry(tmp_path / "summary-access.db")
    owner = registry.create_user("summary@example.invalid", plan="free")
    device = registry.create_device(owner, name="Synthetic", platform="test")
    principal = registry.authenticate(registry.issue_device_token(device))
    prices = TokenPrices("summary-fixture-v1", *(Decimal(0),) * 4)
    return LLMMeter(ResourceLedger(registry), principal, run_key="synthetic-summary-run",
                    catalogue=PriceCatalogue({("openrouter", MODEL): ModelPrice(prices, debit_mode="model_tokens")}))


def test_summary_empty_response_retry_preserves_separate_metered_receipts(meter):
    wire = []

    def handler(request):
        payload = json.loads(request.content)
        wire.append(payload)
        return response(payload, "" if len(wire) == 1 else "Синтетическая сводка.")

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http_client:
        with OpenAI(api_key="synthetic-key", base_url="https://openrouter.ai/api/v1",
                    http_client=http_client, max_retries=0) as client:
            with provider_metering_scope(meter):
                guarded = wrap_provider_client(client, provider="openrouter")
                result = handle_max_iterations(bare_agent(guarded, {"enabled": False}),
                                               [dict(message) for message in MESSAGES], 2)
    assert result == "Синтетическая сводка." and len(wire) == 2
    balance = meter.ledger.summary(meter.principal)
    assert balance["spent"] == 24 and balance["reserved"] == 0
    assert len(meter.ledger.export_rows(meter.principal)["operations"]) == 2


def test_summary_missing_usage_still_holds_reservation_and_stops_before_retry(meter):
    wire = []

    def handler(request):
        payload = json.loads(request.content)
        wire.append(payload)
        return response(payload, "", usage=False)

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http_client:
        with OpenAI(api_key="synthetic-key", base_url="https://openrouter.ai/api/v1",
                    http_client=http_client, max_retries=0) as client:
            with provider_metering_scope(meter):
                guarded = wrap_provider_client(client, provider="openrouter")
                result = handle_max_iterations(bare_agent(guarded, {"enabled": False}),
                                               [dict(message) for message in MESSAGES], 2)
    assert "couldn't summarize" in result and len(wire) == 1 and meter.stopped
    balance = meter.ledger.summary(meter.principal)
    assert balance["spent"] == 0 and balance["reserved"] > 0


def test_summary_provider_preferences_remain_blocked_by_product_cost_guard(meter):
    wire = []

    def handler(request):
        wire.append(json.loads(request.content))
        return response(wire[-1])

    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http_client:
        with OpenAI(api_key="synthetic-key", base_url="https://openrouter.ai/api/v1",
                    http_client=http_client, max_retries=0) as client:
            with provider_metering_scope(meter):
                guarded = wrap_provider_client(client, provider="openrouter")
                result = handle_max_iterations(bare_agent(guarded, {"enabled": False}, preferences=True),
                                               [dict(message) for message in MESSAGES], 2)
    assert "couldn't summarize" in result and wire == []
    assert meter.ledger.summary(meter.principal)["spent"] == 0


@pytest.fixture(autouse=True)
def isolate_summary_diagnostics_and_block_external_network(monkeypatch):
    """Keep diagnostic tokenizer downloads outside these wire/metering checks."""
    import socket
    from troika_product import token_diagnostics

    # Billing reserves use request bytes and settle against provider receipts.
    # This local diagnostic estimate is unrelated to those accounting checks.
    monkeypatch.setattr(token_diagnostics, "token_count", lambda text: (len(text) + 3) // 4)

    def reject_network(*args, **kwargs):
        pytest.fail("external_network_forbidden_in_summary_test", pytrace=False)

    monkeypatch.setattr(socket, "getaddrinfo", reject_network)
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
