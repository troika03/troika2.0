"""Resolve context without sending Ollama probes to the OpenRouter origin."""

import json
from types import SimpleNamespace

import httpx
import pytest
import requests

from agent import model_metadata as metadata
from agent import models_dev


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(requests=[], status=404, body={}, lookups=[])

    def handler(request):
        state.requests.append(request)
        assert request.method == "POST" and request.url.path.endswith("/api/show")
        return httpx.Response(state.status, json=state.body)

    client = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(
        transport=transport, trust_env=False, **kwargs))
    monkeypatch.setattr(metadata, "get_cached_context_length", lambda *a, **kw: None)
    monkeypatch.setattr(metadata, "_resolve_endpoint_context_length", lambda *a, **kw: None)
    monkeypatch.setattr(metadata, "_query_local_context_length", lambda *a, **kw: None)
    monkeypatch.setattr(metadata, "fetch_model_metadata", lambda *a, **kw: {})

    def lookup(provider, model):
        state.lookups.append((provider, model))
        return 262144

    def forbidden(*args, **kwargs):
        pytest.fail("This context-resolution test must not use the network")

    monkeypatch.setattr(models_dev, "lookup_models_dev_context", lookup)
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    return state


@pytest.mark.parametrize("provider", ["openrouter", "", "custom"])
@pytest.mark.parametrize("base_url", [
    "https://openrouter.ai/api/v1", "https://OPENROUTER.AI:443/api/v1/",
])
def test_openrouter_origin_uses_catalogue_without_ollama_post_on_repeated_resolution(wire, provider, base_url):
    for _ in range(2):
        assert metadata.get_model_context_length(
            "openrouter/free", base_url=base_url, provider=provider, api_key="fixture-key",
        ) == 262144
    assert wire.lookups == [("openrouter", "openrouter/free")] * 2
    assert wire.requests == []


@pytest.mark.parametrize("provider, base_url", [
    ("ollama-cloud", "https://ollama.com/v1"),
    ("custom", "https://ollama.fixture.invalid/v1"),
    ("openrouter", "https://ollama.fixture.invalid/v1"),
    ("", "http://127.0.0.1:11434/v1"),
])
def test_hosted_and_custom_ollama_keep_authoritative_native_context(wire, provider, base_url):
    wire.status, wire.body = 200, {"model_info": {"fixture.context_length": 131072},
                                   "parameters": "num_ctx 32768"}
    assert metadata.get_model_context_length(
        "fixture:7b", base_url=base_url, provider=provider, api_key="fixture-key",
    ) == 131072
    assert len(wire.requests) == 1 and wire.lookups == []
    assert wire.requests[0].headers["authorization"] == "Bearer fixture-key"
    assert json.loads(wire.requests[0].read()) == {"name": "fixture:7b"}


@pytest.mark.parametrize("base_url", [
    "https://openrouter.ai.fixture.invalid/v1", "https://my-openrouter.ai/v1",
    "https://openrouter.ai@ollama.fixture.invalid/v1",
    "https://ollama.fixture.invalid/openrouter.ai/v1",
])
def test_lookalike_names_and_userinfo_do_not_disable_custom_ollama(wire, base_url):
    wire.status, wire.body = 200, {"model_info": {"fixture.context_length": 131072}}
    assert metadata.get_model_context_length("fixture:7b", base_url=base_url, provider="custom") == 131072
    assert len(wire.requests) == 1 and wire.lookups == []


def test_other_known_provider_probe_behavior_is_unchanged(wire):
    assert metadata.get_model_context_length(
        "fixture-model", base_url="https://api.openai.com/v1", provider="openai",
    ) == 262144
    assert len(wire.requests) == 1 and wire.lookups == [("openai", "fixture-model")]


def test_custom_ollama_recovers_after_an_unsuccessful_probe_without_negative_cache(wire):
    url = "https://ollama.fixture.invalid/v1"
    assert metadata.get_model_context_length("fixture:7b", base_url=url, provider="custom") == metadata.DEFAULT_FALLBACK_CONTEXT
    wire.status, wire.body = 200, {"model_info": {"fixture.context_length": 131072}}
    assert metadata.get_model_context_length("fixture:7b", base_url=url, provider="custom") == 131072
    assert len(wire.requests) == 2


@pytest.mark.parametrize("configured, cached, expected", [(65536, None, 65536), (None, 98304, 98304)])
def test_explicit_and_persistent_context_limits_still_take_precedence(wire, monkeypatch, configured, cached, expected):
    monkeypatch.setattr(metadata, "get_cached_context_length", lambda *a, **kw: cached)
    assert metadata.get_model_context_length(
        "openrouter/free", base_url="https://openrouter.ai/api/v1", provider="openrouter",
        config_context_length=configured,
    ) == expected
    assert wire.requests == [] and wire.lookups == []


@pytest.mark.parametrize("base_url", ["", None])
def test_omitted_url_does_not_add_a_native_probe(wire, base_url):
    assert metadata.get_model_context_length(
        "openrouter/free", base_url=base_url, provider="openrouter",
    ) == 262144
    assert wire.requests == []


def test_malformed_url_is_rejected_before_any_http_request(wire):
    with pytest.raises(ValueError):
        metadata.get_model_context_length(
            "openrouter/free", base_url="https://[malformed", provider="openrouter",
        )
    assert wire.requests == [] and wire.lookups == []
