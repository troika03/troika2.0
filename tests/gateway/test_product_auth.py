"""Product-auth integration checks for the OpenAI-compatible API server."""

import asyncio
import json

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from toolsets import resolve_toolset


class _Request(dict):
    """Minimal aiohttp request surface used by auth helper unit tests."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self.headers = {"Authorization": f"Bearer {token}"}
        self.remote = "127.0.0.1"
        self.transport = None
        self.method = "GET"
        self.path_qs = "/v1/chat/completions"


def _adapter_with_two_users(tmp_path):
    adapter = APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "product_auth_enabled": True,
                "product_auth_db": str(tmp_path / "access.db"),
                "key": "legacy-bootstrap-key",
            },
        )
    )
    registry = adapter._access_registry
    assert registry is not None
    first_user = registry.create_user("one@example.com")
    second_user = registry.create_user("two@example.com")
    first_token = registry.issue_device_token(
        registry.create_device(first_user, name="Pixel", platform="android")
    )
    second_token = registry.issue_device_token(
        registry.create_device(second_user, name="iPhone", platform="ios")
    )
    return adapter, first_token, second_token


def test_product_auth_ignores_legacy_server_key_and_derives_memory_scope(tmp_path) -> None:
    adapter, first_token, _ = _adapter_with_two_users(tmp_path)

    legacy_request = _Request("legacy-bootstrap-key")
    assert adapter._check_auth(legacy_request).status == 401

    request = _Request(first_token)
    assert adapter._check_auth(request) is None
    scope, error = adapter._parse_session_key_header(request)
    assert error is None
    assert scope is not None and scope.startswith("troika:usr_")


def test_product_session_owner_cannot_be_impersonated(tmp_path) -> None:
    adapter, first_token, second_token = _adapter_with_two_users(tmp_path)
    first = _Request(first_token)
    second = _Request(second_token)
    assert adapter._check_auth(first) is None
    assert adapter._check_auth(second) is None

    assert adapter._authorize_product_session(first, "private-session", claim=True) is None
    assert adapter._authorize_product_session(second, "private-session", claim=True).status == 403


def test_product_quota_and_run_status_are_isolated(tmp_path) -> None:
    adapter, first_token, second_token = _adapter_with_two_users(tmp_path)
    first = _Request(first_token)
    second = _Request(second_token)
    assert adapter._check_auth(first) is None
    assert adapter._check_auth(second) is None
    first_principal = first["troika_product_principal"]
    adapter._access_registry.set_entitlement(
        first_principal.user_id, plan="beta", daily_request_limit=1
    )

    assert adapter._consume_product_request_quota(first) is None
    assert first["troika_usage"].remaining == 0
    exhausted = adapter._consume_product_request_quota(first)
    assert exhausted is not None and exhausted.status == 429

    adapter._run_owners["run_private"] = (
        first_principal.user_id,
        first_principal.device_id,
    )
    assert adapter._authorize_product_run(first, "run_private") is None
    hidden = adapter._authorize_product_run(second, "run_private")
    assert hidden is not None and hidden.status == 404


def test_product_mode_hides_global_responses_api(tmp_path) -> None:
    adapter, first_token, _ = _adapter_with_two_users(tmp_path)
    request = _Request(first_token)
    assert adapter._check_auth(request) is None

    response = asyncio.run(adapter._handle_responses(request))
    assert response.status == 404


def test_product_capabilities_do_not_advertise_global_responses_api(tmp_path) -> None:
    adapter, first_token, _ = _adapter_with_two_users(tmp_path)
    request = _Request(first_token)
    response = asyncio.run(adapter._handle_capabilities(request))
    payload = json.loads(response.body)

    assert payload["features"]["responses_api"] is False
    assert "responses" not in payload["endpoints"]


def test_product_device_context_requires_explicit_consent(tmp_path) -> None:
    adapter, first_token, _ = _adapter_with_two_users(tmp_path)
    request = _Request(first_token)
    assert adapter._check_auth(request) is None
    assert not adapter._product_device_context_allowed(request)

    request.headers["X-Troika-Device-Context-Consent"] = "granted"
    assert adapter._product_device_context_allowed(request)


def test_product_toolset_cannot_control_server_or_user_devices() -> None:
    tools = resolve_toolset("troika-product")
    assert {"web_search", "vision_analyze", "image_generate"} <= set(tools)
    forbidden = {
        "terminal",
        "process",
        "read_file",
        "write_file",
        "pc_gui_control",
        "pc_see_screen",
        "android_open_app",
        "android_send_sms",
        "find_tool",
        "run_tool",
    }
    assert not forbidden.intersection(tools)


def test_product_mode_ignores_operator_toolset_override(tmp_path, monkeypatch) -> None:
    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("run_agent.AIAgent", FakeAgent)
    monkeypatch.setattr(
        "gateway.run._resolve_runtime_agent_kwargs", lambda: {"api_key": "test"}
    )
    monkeypatch.setattr("gateway.run._resolve_gateway_model", lambda: "test/model")
    monkeypatch.setattr(
        "gateway.run._load_gateway_config",
        lambda: {"platform_toolsets": {"api_server": ["terminal", "pc"]}},
    )
    monkeypatch.setattr(
        "gateway.run.GatewayRunner._load_reasoning_config", staticmethod(dict)
    )
    monkeypatch.setattr(
        "gateway.run.GatewayRunner._load_fallback_model", staticmethod(lambda: None)
    )
    adapter = APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "product_auth_enabled": True,
                "product_auth_db": str(tmp_path / "access.db"),
            },
        )
    )
    monkeypatch.setattr(adapter, "_ensure_session_db", lambda: None)

    adapter._create_agent()
    assert captured["enabled_toolsets"] == ["troika-product"]
