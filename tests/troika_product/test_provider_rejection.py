"""Release model holds only for verified pre-response provider refusals."""

import asyncio
import json

import httpx
from openai import APIStatusError
import pytest

from agent.provider_metering import ProviderCallBlocked, provider_metering_scope, wrap_provider_client
from tests.troika_product.test_llm_metering import (
    AsyncClient, Client, Stream, invoke, meter, operations, response, summary, PAYLOAD,
)


def rejected(status=402, body=None, host="openrouter.ai"):
    return APIStatusError("provider refusal", response=httpx.Response(
        status, json=body if body is not None else {"error": {"code": status, "message": "fixture"}},
        request=httpx.Request("POST", f"https://{host}/api/v1/chat/completions")), body=body)


def test_confirmed_credit_refusal_returns_reserve_and_allows_next_model(meter):
    with pytest.raises(APIStatusError):
        invoke(meter, Client(rejected()))
    receipt = operations(meter)[0]
    assert receipt["state"] == "settled" and receipt["charged_tokens"] == 0
    assert json.loads(receipt["usage_json"])["successful"] is False
    assert summary(meter)["reserved"] == 0 and not meter.stopped
    invoke(meter, Client(response()))
    assert summary(meter)["spent"] > 0


def test_async_credit_refusal_preserves_original_exception(meter):
    async def run():
        with provider_metering_scope(meter):
            await wrap_provider_client(AsyncClient(rejected()), async_mode=True).chat.completions.create(**PAYLOAD)
    with pytest.raises(APIStatusError):
        asyncio.run(run())
    assert summary(meter)["reserved"] == 0 and not meter.stopped


def test_verified_free_rate_limit_releases_hold_for_next_model(meter):
    from decimal import Decimal
    from tests.troika_product.test_llm_metering import MODEL
    from troika_product.llm_metering import ModelPrice, PriceCatalogue
    from troika_product.subscription_policy import TokenPrices

    prices = TokenPrices("test-free", *(Decimal(0) for _ in range(4)))
    meter.catalogue = PriceCatalogue({("openrouter", MODEL): ModelPrice(prices, debit_mode="model_tokens")})
    with pytest.raises(APIStatusError):
        invoke(meter, Client(rejected(429)))
    assert summary(meter)["reserved"] == 0 and not meter.stopped


@pytest.mark.parametrize("error", [
    rejected(500), rejected(429), rejected(401),
    rejected(host="api.openai.com"),
    rejected(body={"error": {"code": 402}, "usage": {"total_tokens": 1}}),
    rejected(body={"message": "payment required"}),
    TimeoutError("unknown response"),
])
def test_other_failures_remain_unknown_and_never_allow_fallback(meter, error):
    with pytest.raises(ProviderCallBlocked):
        invoke(meter, Client(error))
    assert summary(meter)["reserved"] > 0 and meter.stopped


def test_in_stream_credit_error_cannot_release_a_started_generation(meter):
    with pytest.raises(ProviderCallBlocked):
        with provider_metering_scope(meter):
            stream = wrap_provider_client(Client(Stream([{"choices": []}], error=rejected()))).chat.completions.create(**PAYLOAD, stream=True)
            list(stream)
    assert summary(meter)["reserved"] > 0 and meter.stopped
