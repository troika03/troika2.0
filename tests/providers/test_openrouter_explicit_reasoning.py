"""Explicit OpenRouter settings reach the SDK without changing omitted defaults."""

import json

import httpx
from openai import OpenAI
import pytest

from agent.transports.chat_completions import ChatCompletionsTransport
from providers import get_provider_profile


@pytest.mark.parametrize("supports_reasoning", [False, True])
@pytest.mark.parametrize("configured", [
    {"enabled": False},
    {"effort": "low"},
    {"enabled": True, "effort": "high", "exclude": True},
])
def test_explicit_reasoning_does_not_depend_on_capability_heuristic(supports_reasoning, configured):
    profile = get_provider_profile("openrouter")
    extra, _ = profile.build_api_kwargs_extras(
        model="fixture/unrecognized-route", supports_reasoning=supports_reasoning,
        reasoning_config=configured,
    )
    assert extra["reasoning"] == configured
    assert extra["reasoning"] is not configured
    extra["reasoning"]["exclude"] = "changed downstream"
    assert configured.get("exclude") != "changed downstream"


@pytest.mark.parametrize("supports_reasoning", [False, True])
def test_omitted_reasoning_retains_capability_gated_defaults(supports_reasoning):
    profile = get_provider_profile("openrouter")
    extra, _ = profile.build_api_kwargs_extras(
        model="fixture/unrecognized-route", supports_reasoning=supports_reasoning,
        reasoning_config=None,
    )
    expected = {"reasoning": {"enabled": True, "effort": "medium"}} if supports_reasoning else {}
    assert extra == expected


@pytest.mark.parametrize("configured", [{"enabled": False}, {"effort": "low"}])
def test_transport_and_sdk_send_explicit_reasoning_on_final_json_wire(configured):
    payloads = []

    def respond(request):
        payload = json.loads(request.content)
        payloads.append(payload)
        return httpx.Response(200, json={
            "id": "fixture-completion", "object": "chat.completion", "created": 0,
            "model": payload["model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "fixture"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    kwargs = ChatCompletionsTransport().build_kwargs(
        model="fixture/unrecognized-route", messages=[{"role": "user", "content": "synthetic"}],
        tools=None, provider_profile=get_provider_profile("openrouter"),
        supports_reasoning=False, reasoning_config=configured,
    )
    with httpx.Client(transport=httpx.MockTransport(respond)) as http_client:
        with OpenAI(api_key="fixture-key", base_url="https://openrouter.ai/api/v1",
                    http_client=http_client, max_retries=0) as client:
            client.chat.completions.create(**kwargs)
    assert len(payloads) == 1
    assert payloads[0]["reasoning"] == configured
    assert "extra_body" not in payloads[0]


def test_explicit_reasoning_keeps_provider_preferences_and_grok_cache_header():
    kwargs = ChatCompletionsTransport().build_kwargs(
        model="x-ai/grok-fixture", messages=[{"role": "user", "content": "synthetic"}],
        tools=None, provider_profile=get_provider_profile("openrouter"),
        supports_reasoning=False, reasoning_config={"enabled": False},
        session_id="fixture-session", provider_preferences={"sort": "latency"},
    )
    assert kwargs["extra_body"] == {"provider": {"sort": "latency"}, "reasoning": {"enabled": False}}
    assert kwargs["extra_headers"] == {"x-grok-conv-id": "fixture-session"}


def test_explicit_request_overrides_still_have_final_precedence():
    kwargs = ChatCompletionsTransport().build_kwargs(
        model="fixture/unrecognized-route", messages=[{"role": "user", "content": "synthetic"}],
        tools=None, provider_profile=get_provider_profile("openrouter"),
        supports_reasoning=False, reasoning_config={"enabled": False},
        request_overrides={"extra_body": {"reasoning": {"effort": "high"}}},
    )
    assert kwargs["extra_body"]["reasoning"] == {"effort": "high"}
