"""Exercise the main runtime worker threads and both hosted execution paths."""

import asyncio
import threading
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from agent.provider_metering import (
    ProviderCallBlocked,
    current_provider_guard,
    provider_metering_scope,
    wrap_provider_client,
)
from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from troika_product.access import AccessRegistry
from troika_product.llm_metering import LLMMeter, ModelPrice, PriceCatalogue
from troika_product.resource_ledger import ResourceLedger
from troika_product.subscription_policy import TokenPrices


MODEL = "test/runtime"
PAYLOAD = {
    "model": MODEL,
    "messages": [{"role": "user", "content": "test"}],
    "max_tokens": 1000,
}


def usage():
    return SimpleNamespace(prompt_tokens=7000, completion_tokens=500)


def full_response():
    return SimpleNamespace(
        model=MODEL,
        usage=usage(),
        id="fake-completion",
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    role="assistant",
                    content="test answer",
                    tool_calls=None,
                    reasoning_content=None,
                    reasoning=None,
                ),
            )
        ],
    )


def chunk(text=None, *, final=False):
    return SimpleNamespace(
        model=MODEL,
        usage=usage() if final else None,
        choices=[]
        if final
        else [
            SimpleNamespace(
                index=0,
                finish_reason="stop",
                delta=SimpleNamespace(
                    content=text,
                    tool_calls=None,
                    reasoning_content=None,
                    reasoning=None,
                ),
            )
        ],
    )


@pytest.fixture
def meter(tmp_path):
    registry = AccessRegistry(tmp_path / "account.db")
    owner = registry.create_user("runtime@example.com", plan="free")
    device = registry.create_device(owner, name="phone", platform="android")
    principal = registry.authenticate(registry.issue_device_token(device))
    prices = TokenPrices("runtime-v1", *[Decimal("30")] * 4)
    return LLMMeter(
        ResourceLedger(registry),
        principal,
        run_key="server-run",
        catalogue=PriceCatalogue({("openrouter", MODEL): ModelPrice(prices)}),
    )


def client(reply):
    sdk = MagicMock()
    sdk.max_retries = 0
    sdk.base_url = "https://openrouter.ai/api/v1"
    sdk.chat.completions.create.return_value = reply
    return sdk


def agent(monkeypatch, sdk):
    from run_agent import AIAgent

    # The primary mock follows the same request factory boundary as real SDKs.
    monkeypatch.setattr(AIAgent, "_ensure_primary_openai_client", lambda *a, **k: sdk)
    monkeypatch.setattr("agent.agent_init.fetch_model_metadata", lambda: {})
    result = AIAgent(
        api_key="fake-test-key",
        base_url=sdk.base_url,
        provider="openrouter",
        model=MODEL,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
        enabled_toolsets=[],
    )
    result.api_mode = "chat_completions"
    return result


def test_main_nonstream_worker_inherits_account_guard(meter, monkeypatch):
    sdk = client(full_response())
    runtime = agent(monkeypatch, sdk)
    with provider_metering_scope(meter):
        result = runtime._interruptible_api_call(PAYLOAD)
    assert result.choices[0].message.content == "test answer"
    assert sdk.chat.completions.create.call_count == 1
    assert meter.ledger.summary(meter.principal)["spent"] == 7500


def test_main_stream_worker_inherits_guard_and_reads_usage(meter, monkeypatch):
    sdk = client(iter([chunk("test answer"), chunk(final=True)]))
    runtime = agent(monkeypatch, sdk)
    with provider_metering_scope(meter):
        result = runtime._interruptible_streaming_api_call(PAYLOAD)
    assert result.choices[0].message.content == "test answer"
    assert meter.ledger.summary(meter.principal)["spent"] == 7500


def test_iteration_limit_summary_uses_same_guard(meter, monkeypatch):
    sdk = client(full_response())
    runtime = agent(monkeypatch, sdk)
    with provider_metering_scope(meter):
        result = runtime._handle_max_iterations(list(PAYLOAD["messages"]), 1)
    assert result == "test answer"
    assert sdk.chat.completions.create.call_count == 1
    assert meter.ledger.summary(meter.principal)["spent"] == 7500


def test_main_stream_does_not_convert_missing_usage_into_success(meter, monkeypatch):
    sdk = client(iter([chunk("partial answer")]))
    runtime = agent(monkeypatch, sdk)
    with provider_metering_scope(meter), pytest.raises(ProviderCallBlocked):
        runtime._interruptible_streaming_api_call(PAYLOAD)
    assert sdk.chat.completions.create.call_count == 1
    assert meter.ledger.summary(meter.principal)["reserved"] > 0


def test_watchdog_cannot_retry_while_sent_request_is_still_pending(meter, monkeypatch):
    release = threading.Event()
    finished = threading.Event()
    sdk = client(full_response())

    def wait_for_transport(**kwargs):
        release.wait(timeout=10)
        finished.set()
        raise ConnectionError("fake watchdog abort")

    sdk.chat.completions.create.side_effect = wait_for_transport
    runtime = agent(monkeypatch, sdk)
    monkeypatch.setattr(
        runtime, "_compute_non_stream_stale_timeout", lambda payload: 0.01
    )
    try:
        with provider_metering_scope(meter):
            with pytest.raises(ProviderCallBlocked) as error:
                runtime._interruptible_api_call(PAYLOAD)
            assert error.value.code == "resource_usage_unknown"
            with pytest.raises(ProviderCallBlocked):
                wrap_provider_client(sdk).chat.completions.create(**PAYLOAD)
        assert sdk.chat.completions.create.call_count == 1
        assert meter.ledger.summary(meter.principal)["reserved"] > 0
    finally:
        release.set()
        assert finished.wait(timeout=5)


@pytest.mark.parametrize("streaming", [False, True])
def test_conversation_refusal_cannot_retry_or_fallback(meter, monkeypatch, streaming):
    sdk = client(full_response())
    runtime = agent(monkeypatch, sdk)
    monkeypatch.setattr(runtime, "_try_activate_fallback", MagicMock())
    monkeypatch.setattr(
        runtime,
        "_interruptible_api_call",
        MagicMock(
            side_effect=ProviderCallBlocked(
                "monthly_resource_exhausted", "AI-ресурс исчерпан."
            )
        ),
    )
    monkeypatch.setattr(
        runtime, "_interruptible_streaming_api_call", runtime._interruptible_api_call
    )
    # Avoid a provider/model metadata probe: this test exercises the loop's
    # policy-exception path, not dynamic context-window discovery.
    runtime.context_compressor._context_probed = True
    monkeypatch.setattr(runtime, "_build_api_kwargs", lambda messages: PAYLOAD)
    runtime._disable_streaming = not streaming
    with provider_metering_scope(meter):
        result = runtime.run_conversation("test")
    assert result["completed"] is False
    assert result["error_code"] == "monthly_resource_exhausted"
    assert result["final_response"] == "AI-ресурс исчерпан."
    assert runtime._interruptible_api_call.call_count == 1
    runtime._try_activate_fallback.assert_not_called()


@pytest.fixture
def adapter(tmp_path):
    result = APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "product_auth_enabled": True,
                "product_auth_db": str(tmp_path / "access.db"),
                "product_artifact_root": str(tmp_path / "artifacts"),
                "product_workspace_root": str(tmp_path / "workspaces"),
                "product_resource_text_enabled": True,
                "product_resource_prices": {
                    MODEL: {
                        "version": "runtime-v1",
                        "input_rub": "30",
                        "output_rub": "30",
                        "cache_read_rub": "30",
                        "cache_write_rub": "30",
                    }
                },
            },
        )
    )
    registry = result._access_registry
    owner = registry.create_user("hosted@example.com", plan="free")
    device = registry.create_device(owner, name="phone", platform="android")
    principal = registry.authenticate(registry.issue_device_token(device))
    return result, principal


def test_hosted_chat_binds_guard_before_agent_creation_and_resets_it(
    adapter, monkeypatch
):
    hosted, principal = adapter
    seen = []
    sdk = client(full_response())

    def create(**kwargs):
        guard = current_provider_guard()
        assert guard.principal == principal
        seen.append(guard)
        wrapped = wrap_provider_client(sdk)

        class Runtime:
            def run_conversation(self, **kwargs):
                wrapped.chat.completions.create(**PAYLOAD)
                return {"final_response": "test answer", "completed": True}

        return Runtime()

    monkeypatch.setattr(hosted, "_create_agent", create)
    result, _ = asyncio.run(hosted._run_agent("test", [], product_principal=principal))
    assert result["completed"]
    assert len(seen) == 1
    assert seen[0].ledger.summary(principal)["spent"] == 7500
    assert current_provider_guard() is None


def test_default_flag_does_not_issue_resource_or_change_runtime(adapter, monkeypatch):
    hosted, principal = adapter
    hosted._product_resource_text_enabled = False
    sdk = client(full_response())

    def create(**kwargs):
        assert current_provider_guard() is None
        assert wrap_provider_client(sdk) is sdk
        return SimpleNamespace(run_conversation=lambda **kwargs: {"completed": True})

    monkeypatch.setattr(hosted, "_create_agent", create)
    asyncio.run(hosted._run_agent("test", [], product_principal=principal))
    assert (
        ResourceLedger(hosted._access_registry).export_rows(principal)["grants"] == []
    )


def test_guard_cannot_be_enabled_without_authenticated_principal(adapter):
    hosted, _ = adapter
    with pytest.raises(ProviderCallBlocked):
        asyncio.run(hosted._run_agent("test", []))
    assert current_provider_guard() is None


def test_operator_resource_controls_are_hidden_from_assistant_preferences():
    from hermes_cli.web_server import CONFIG_SCHEMA

    assert not any(key.startswith("platforms.") for key in CONFIG_SCHEMA)


def test_guard_cleanup_after_agent_error_does_not_leak_account(adapter, monkeypatch):
    hosted, principal = adapter

    def create(**kwargs):
        assert current_provider_guard().principal == principal
        raise RuntimeError("fake startup failure")

    monkeypatch.setattr(hosted, "_create_agent", create)
    with pytest.raises(RuntimeError):
        asyncio.run(hosted._run_agent("test", [], product_principal=principal))
    assert current_provider_guard() is None


@pytest.mark.asyncio
async def test_hosted_run_binds_server_run_id_and_ignores_body_resource_claims(
    adapter, monkeypatch
):
    hosted, principal = adapter
    sdk = client(full_response())
    seen = []

    def create(**kwargs):
        guard = current_provider_guard()
        assert guard.principal.user_id == principal.user_id
        seen.append(guard)
        wrapped = wrap_provider_client(sdk)

        def run(**kwargs):
            wrapped.chat.completions.create(**PAYLOAD)
            return {"final_response": "test answer", "completed": True}

        return SimpleNamespace(run_conversation=run)

    monkeypatch.setattr(hosted, "_create_agent", create)
    token = hosted._access_registry.issue_device_token(principal.device_id)
    app = web.Application()
    app.router.add_post("/v1/runs", hosted._handle_runs)
    async with TestClient(TestServer(app)) as http_client:
        started = await http_client.post(
            "/v1/runs",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "input": "test",
                "resource_tokens": 999_999_999,
                "user_id": "fake-other-owner",
                "run_id": "fake-run",
            },
        )
        assert started.status == 202
        run_id = (await started.json())["run_id"]
        assert run_id != "fake-run"
        await asyncio.wait_for(
            asyncio.gather(*list(hosted._background_tasks)), timeout=10
        )
    assert len(seen) == 1
    assert seen[0].run_key == run_id
    assert seen[0].ledger.summary(seen[0].principal)["spent"] == 7500
    assert hosted._run_statuses[run_id]["status"] == "completed"
    assert current_provider_guard() is None
