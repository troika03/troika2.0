"""Provider-boundary tests: real ledger, fake network, full usage receipts."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from agent.provider_metering import (
    ProviderCallBlocked,
    current_provider_guard,
    metered_client_resolver,
    provider_context_target,
    provider_metering_scope,
    require_metered_api_mode,
    wrap_provider_client,
)
from troika_product.access import AccessRegistry
from troika_product.llm_metering import LLMMeter, ModelPrice, PriceCatalogue
from troika_product.resource_ledger import ResourceLedger
from troika_product.subscription_policy import TokenPrices, TokenUsage


MODEL = "test/full-context"
PRICES = TokenPrices(
    "test-v1", Decimal("20.7"), Decimal("64.86"), Decimal("2.208"), Decimal("20.7")
)
PAYLOAD = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "Привет"}],
    "max_tokens": 1000,
}


def test_vision_uses_confirmed_image_bound_and_actual_prompt_receipt(meter):
    meter.catalogue = PriceCatalogue({
        ("openrouter", MODEL): ModelPrice(PRICES, vision_input_tokens=128000)
    })
    sdk = Client(response(prompt=130000, output=500))
    with provider_metering_scope(meter):
        wrap_provider_client(sdk).chat.completions.create(**{
            **PAYLOAD,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Опиши разрешённый снимок"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64,AAAA"},
                        },
                    ],
                }
            ],
        })
    actual_cost, charged = PRICES.quote(TokenUsage(130000, 500))
    assert meter.ledger.summary(meter.principal)["spent"] == charged
    assert len(sdk.calls) == 1
    receipt = meter.ledger.export_rows(meter.principal)["operations"][0]
    assert receipt["reserved_tokens"] > charged
    assert json.loads(receipt["usage_json"])["service_usage"]["cost_rub"] == str(
        actual_cost
    )


def test_development_json_schema_is_metered_without_allowing_provider_routing(meter):
    sdk = Client()
    formatting = {"type": "json_schema", "json_schema": {
        "name": "project", "strict": True,
        "schema": {"type": "object", "properties": {"content": {"type": "string"}},
                   "required": ["content"], "additionalProperties": False}}}
    with provider_metering_scope(meter):
        wrap_provider_client(sdk).chat.completions.create(
            **PAYLOAD, extra_body={"response_format": formatting})
    assert sdk.calls[0]["extra_body"]["response_format"] == formatting
    assert meter.ledger.summary(meter.principal)["spent"] > 0


def test_confirmed_free_bill_preserves_incompatible_reasoning_counters(meter):
    meter.catalogue = PriceCatalogue({("openrouter", MODEL): ModelPrice(TokenPrices(
        "free-v1", Decimal(0), Decimal(0), Decimal(0), Decimal(0)))})
    reply = response(output=45, reasoning=48)
    reply.usage.cost = 0
    invoke(meter, Client(reply))
    summary = meter.ledger.summary(meter.principal)
    assert summary["spent"] == summary["reserved"] == 0
    details = summary["recent_operations"][0]["usage"]["service_usage"]
    assert details["reported_completion_tokens"] == 45
    assert details["reported_reasoning_tokens"] == 48
    assert details["tokens_upper_bound"] == 1
    assert summary["recent_operations"][0]["usage"]["tokens"]["output_tokens"] == 93


@pytest.mark.parametrize("cached,reasoning", [(7000, 200), (0, 501)])
def test_company_free_model_debits_full_native_input_and_output_once(meter, cached, reasoning):
    meter.catalogue = PriceCatalogue({("openrouter", MODEL): ModelPrice(TokenPrices(
        "raw-free-v1", Decimal(0), Decimal(0), Decimal(0), Decimal(0)), debit_mode="model_tokens")})
    reply = response(cached=cached, reasoning=reasoning)
    reply.usage.cost = 0
    invoke(meter, Client(reply))
    balance = meter.ledger.summary(meter.principal)
    assert balance["spent"] == 7500
    assert balance["reserved"] == 0
    assert balance["recent_operations"][0]["usage"]["service_usage"]["cost_rub"] == "0"


def response(prompt=7000, output=500, cached=0, reasoning=0):
    return SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=output,
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
        )
    )


class Client:
    def __init__(self, reply=None, *, max_retries=0):
        self.max_retries = max_retries
        self.base_url = "https://openrouter.ai/api/v1"
        self.calls = []
        self.reply = reply if reply is not None else response()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


class AsyncClient(Client):
    async def create(self, **kwargs):
        return super().create(**kwargs)


class Stream:
    def __init__(self, chunks, error=None):
        self.chunks, self.error = chunks, error
        self.closed = False

    def __iter__(self):
        yield from self.chunks
        if self.error:
            raise self.error

    def close(self):
        self.closed = True


class AsyncStream(Stream):
    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.error:
            raise self.error

    async def close(self):
        super().close()


@pytest.fixture
def meter(tmp_path):
    registry = AccessRegistry(tmp_path / "access.db")
    owner = registry.create_user("meter@example.com", plan="free")
    device = registry.create_device(owner, name="phone", platform="android")
    principal = registry.authenticate(registry.issue_device_token(device))
    return LLMMeter(
        ResourceLedger(registry),
        principal,
        run_key="trusted-run",
        catalogue=PriceCatalogue({("openrouter", MODEL): ModelPrice(PRICES)}),
    )


def summary(meter):
    return meter.ledger.summary(meter.principal)


def operations(meter):
    return meter.ledger.export_rows(meter.principal)["operations"]


def invoke(meter, client=None, **changes):
    client = client or Client()
    with provider_metering_scope(meter):
        wrapped = wrap_provider_client(client, provider="openrouter")
        return wrapped.chat.completions.create(**{**PAYLOAD, **changes})


def test_greeting_debits_full_provider_context_and_reasoning_once(meter):
    invoke(meter, Client(response(reasoning=200)))
    assert summary(meter)["spent"] == 5911
    assert summary(meter)["remaining"] == 500_000 - 5911
    assert summary(meter)["reserved"] == 0
    receipt = operations(meter)[0]
    assert json.loads(receipt["usage_json"])["tokens"] == {
        "input_tokens": 7000,
        "output_tokens": 500,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": 200,
    }
    assert "Привет" not in json.dumps(receipt, ensure_ascii=False)


def test_cached_full_context_uses_lower_price(meter):
    invoke(meter, Client(response(cached=7000)))
    assert summary(meter)["spent"] == 1597


def test_cache_aliases_and_cache_write_remain_disjoint(meter):
    raw = {
        "prompt_tokens": 7000,
        "completion_tokens": 500,
        "prompt_tokens_details": {},
        "cache_read_input_tokens": 3000,
        "cache_creation_input_tokens": 2000,
    }
    invoke(meter, Client({"usage": raw}))
    usage = json.loads(operations(meter)[0]["usage_json"])["tokens"]
    assert (
        usage["input_tokens"],
        usage["cache_read_tokens"],
        usage["cache_write_tokens"],
    ) == (2000, 3000, 2000)


def test_main_and_auxiliary_calls_share_run_and_account_budget(meter):
    invoke(meter)
    invoke(meter)
    assert summary(meter)["spent"] == 2 * 5911
    assert len(operations(meter)) == 2


def test_estimate_includes_tools_memory_history_and_full_utf8(meter):
    client = Client(response(prompt=40_000))
    messages = [{"role": "system", "content": "память" * 10_000}, *PAYLOAD["messages"]]
    invoke(
        meter,
        client,
        messages=messages,
        tools=[
            {
                "type": "function",
                "function": {"name": "example", "description": "описание" * 5000},
            }
        ],
    )
    assert operations(meter)[0]["reserved_tokens"] > 50_000
    assert summary(meter)["reserved"] == 0


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"model": "unknown"}, "resource_price_unavailable"),
        ({"max_tokens": -1}, "resource_output_unbounded"),
        ({"max_tokens": True}, "resource_output_unbounded"),
        ({"max_tokens": 100_000}, "resource_output_unbounded"),
        ({"max_completion_tokens": 100}, "resource_output_unbounded"),
        ({"n": 2}, "resource_output_unbounded"),
        ({"n": True}, "resource_output_unbounded"),
        ({"messages": None}, "unmetered_provider_route"),
        (
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": "fake"}],
                    }
                ]
            },
            "unmetered_provider_route",
        ),
        ({"modalities": ["text", "audio"]}, "unmetered_provider_route"),
        ({"extra_body": {"max_tokens": 100_000}}, "unmetered_provider_route"),
        ({"extra_body": {"models": ["other"]}}, "unmetered_provider_route"),
        ({"extra_body": {"plugins": [{"id": "web"}]}}, "unmetered_provider_route"),
    ],
)
def test_invalid_or_unpriced_requests_never_reach_network(meter, changes, code):
    client = Client()
    with pytest.raises(ProviderCallBlocked) as error:
        invoke(meter, client, **changes)
    assert error.value.code == code
    assert not client.calls
    assert not operations(meter)


def test_missing_output_limit_is_bounded_before_dispatch(meter):
    client = Client()
    invoke(meter, client, max_tokens=None)
    assert client.calls[0]["max_tokens"] == 8192


def test_premium_model_is_denied_for_free_before_dispatch(meter):
    meter.catalogue = PriceCatalogue({
        ("openrouter", MODEL): ModelPrice(PRICES, premium=True)
    })
    client = Client()
    with pytest.raises(ProviderCallBlocked) as error:
        invoke(meter, client)
    assert error.value.code == "subscription_feature_not_available"
    assert not client.calls


def test_exhausted_account_cannot_start_network_call(meter):
    meter.ledger.reserve(
        meter.principal,
        operation_key="other",
        run_key="other",
        kind="llm",
        tokens=500_000,
        pricing_version="test-v1",
    )
    client = Client()
    with pytest.raises(ProviderCallBlocked) as error:
        invoke(meter, client)
    assert error.value.code == "monthly_resource_exhausted"
    assert not client.calls


@pytest.mark.parametrize(
    "reply",
    [
        SimpleNamespace(usage=None),
        response(prompt=-1),
        response(cached=8000),
        response(reasoning=501),
        response(output=1001),
        response(prompt=200_000),
        response(prompt=True),
        ConnectionError("fake connection loss"),
    ],
)
def test_unknown_or_excessive_usage_retains_hold_and_stops_retries(meter, reply):
    client = Client(reply)
    with pytest.raises(ProviderCallBlocked):
        invoke(meter, client)
    with pytest.raises(ProviderCallBlocked):
        invoke(meter, client)
    assert len(client.calls) == 1
    assert len(operations(meter)) == 1
    assert summary(meter)["reserved"] > 0
    assert summary(meter)["spent"] == 0


def test_stream_requests_final_usage_and_debits_once(meter):
    final = response()
    client = Client(Stream([SimpleNamespace(usage=None), final, final]))
    with provider_metering_scope(meter):
        stream = wrap_provider_client(client).chat.completions.create(
            **PAYLOAD, stream=True
        )
        assert summary(meter)["reserved"] > 0
        assert len(list(stream)) == 3
    assert client.calls[0]["stream_options"] == {"include_usage": True}
    assert summary(meter)["spent"] == 5911
    assert summary(meter)["reserved"] == 0


@pytest.mark.parametrize("error", [None, ConnectionError("fake stream loss")])
def test_stream_without_final_usage_is_not_free_and_cannot_retry(meter, error):
    client = Client(Stream([SimpleNamespace(usage=None)], error))
    with provider_metering_scope(meter):
        wrapped = wrap_provider_client(client)
        with pytest.raises(ProviderCallBlocked):
            list(wrapped.chat.completions.create(**PAYLOAD, stream=True))
        with pytest.raises(ProviderCallBlocked):
            wrapped.chat.completions.create(**PAYLOAD)
    assert len(client.calls) == 1
    assert summary(meter)["reserved"] > 0


def test_closing_stream_early_preserves_unknown_hold(meter):
    original = Stream([response()])
    with provider_metering_scope(meter):
        stream = wrap_provider_client(Client(original)).chat.completions.create(
            **PAYLOAD, stream=True
        )
        stream.close()
    assert original.closed
    assert summary(meter)["reserved"] > 0
    assert summary(meter)["spent"] == 0


def test_async_response_and_stream_use_same_ledger(meter):
    async def work():
        with provider_metering_scope(meter):
            await wrap_provider_client(
                AsyncClient(), async_mode=True
            ).chat.completions.create(**PAYLOAD)
            client = AsyncClient(AsyncStream([response()]))
            stream = await wrap_provider_client(
                client, async_mode=True
            ).chat.completions.create(**PAYLOAD, stream=True)
            assert len([chunk async for chunk in stream]) == 1

    asyncio.run(work())
    assert summary(meter)["spent"] == 2 * 5911


def test_sdk_retries_and_scope_leaks_are_blocked(meter):
    client = Client(max_retries=2)
    with provider_metering_scope(meter), pytest.raises(ProviderCallBlocked):
        wrap_provider_client(client)
    assert not client.calls
    client = Client()
    with provider_metering_scope(meter):
        wrapped = wrap_provider_client(client)
    with pytest.raises(ProviderCallBlocked) as error:
        wrapped.chat.completions.create(**PAYLOAD)
    assert error.value.code == "resource_scope_changed"
    assert current_provider_guard() is None
    assert not client.calls


def test_unguarded_runtime_returns_original_client(meter):
    client = Client(max_retries=2)
    assert wrap_provider_client(client) is client
    with provider_metering_scope(meter):
        with provider_metering_scope(None):
            assert wrap_provider_client(client) is client
        assert current_provider_guard() is meter
    assert current_provider_guard() is None


@pytest.mark.parametrize(
    "mode", ["codex_responses", "anthropic_messages", "bedrock_converse"]
)
def test_native_modes_require_separate_adapter(meter, mode):
    require_metered_api_mode(mode)
    with provider_metering_scope(meter), pytest.raises(ProviderCallBlocked):
        require_metered_api_mode(mode)


def test_other_api_endpoints_and_native_auxiliary_adapters_are_blocked(meter):
    with provider_metering_scope(meter):
        client = wrap_provider_client(Client())
        with pytest.raises(ProviderCallBlocked):
            client.responses

        @metered_client_resolver
        def native():
            return Client(), MODEL

        with pytest.raises(ProviderCallBlocked):
            native()


def test_revoked_principal_cannot_dispatch(meter):
    meter.ledger.registry.revoke_device(meter.principal, meter.principal.device_id)
    client = Client()
    with pytest.raises(ProviderCallBlocked) as error:
        invoke(meter, client)
    assert error.value.code == "resource_access_revoked"
    assert not client.calls


def test_price_config_is_trusted_versioned_and_strict():
    row = {
        "version": "server-v1",
        "input_rub": "20.7",
        "output_rub": "64.86",
        "cache_read_rub": "2.208",
        "cache_write_rub": "20.7",
    }
    catalogue = PriceCatalogue.from_config({MODEL: row})
    assert catalogue.entries[("openrouter", MODEL)].prices == PRICES.__class__(
        "server-v1",
        Decimal("20.7"),
        Decimal("64.86"),
        Decimal("2.208"),
        Decimal("20.7"),
    )
    with pytest.raises(ValueError):
        PriceCatalogue.from_config({MODEL: {**row, "input_rub": "NaN"}})
    with pytest.raises(ValueError):
        PriceCatalogue.from_config({MODEL: {**row, "premium": "false"}})


def test_auxiliary_sdk_factory_disables_hidden_retries_only_in_scope(
    meter, monkeypatch
):
    import agent.auxiliary_client as auxiliary

    class SDK(Client):
        def __init__(self, *args, **kwargs):
            super().__init__(max_retries=kwargs.get("max_retries", 2))

    monkeypatch.setattr(auxiliary, "_OPENAI_CLS_CACHE", SDK)
    assert auxiliary.OpenAI().max_retries == 2
    with provider_metering_scope(meter):
        auxiliary.OpenAI().chat.completions.create(**PAYLOAD)
    assert summary(meter)["spent"] == 5911


def test_background_worker_keeps_original_account_scope(meter):
    client = Client()
    with provider_metering_scope(meter):
        target = provider_context_target(
            lambda: wrap_provider_client(client).chat.completions.create(**PAYLOAD)
        )
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(target).result(timeout=5)
    assert summary(meter)["spent"] == 5911
    assert current_provider_guard() is None


def test_guarded_auxiliary_provider_router_returns_metered_client(meter, monkeypatch):
    import agent.auxiliary_client as auxiliary

    class SDK(Client):
        def __init__(self, *args, **kwargs):
            super().__init__(max_retries=kwargs.get("max_retries", 2))

    monkeypatch.setattr(auxiliary, "_OPENAI_CLS_CACHE", SDK)
    with provider_metering_scope(meter):
        client, model = auxiliary.resolve_provider_client(
            provider="openrouter",
            model=MODEL,
            explicit_base_url="https://openrouter.ai/api/v1",
            explicit_api_key="fake-key",
        )
        assert model == MODEL
        client.chat.completions.create(**PAYLOAD)
    assert summary(meter)["spent"] == 5911


def test_auxiliary_cache_is_per_run_and_never_reuses_another_owner(meter, monkeypatch):
    import agent.auxiliary_client as auxiliary

    created = []

    class SDK(Client):
        def __init__(self, *args, **kwargs):
            super().__init__(max_retries=kwargs.get("max_retries", 2))
            created.append(self)

    monkeypatch.setattr(auxiliary, "_OPENAI_CLS_CACHE", SDK)
    monkeypatch.setattr(auxiliary, "_client_cache", {})
    kwargs = {
        "provider": "openrouter",
        "model": MODEL,
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "fake-key",
    }
    legacy, _ = auxiliary._get_cached_client(**kwargs)
    with provider_metering_scope(meter):
        first, _ = auxiliary._get_cached_client(**kwargs)
        assert auxiliary._get_cached_client(**kwargs)[0] is first
        first.chat.completions.create(**PAYLOAD)
    registry = meter.ledger.registry
    owner = registry.create_user("second-meter@example.com", plan="free")
    device = registry.create_device(owner, name="pc", platform="windows")
    principal = registry.authenticate(registry.issue_device_token(device))
    second_meter = LLMMeter(
        meter.ledger, principal, run_key="other-run", catalogue=meter.catalogue
    )
    with provider_metering_scope(second_meter):
        second, _ = auxiliary._get_cached_client(**kwargs)
        assert second is not first
        second.chat.completions.create(**PAYLOAD)
    assert auxiliary._get_cached_client(**kwargs)[0] is legacy
    assert len(created) == 3
    assert not legacy.calls
    assert summary(meter)["spent"] == summary(second_meter)["spent"] == 5911
