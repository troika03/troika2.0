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


class _ApprovalRequest(_Request):
    def __init__(self, token: str, run_id: str, body: dict) -> None:
        super().__init__(token)
        self.match_info = {"run_id": run_id}
        self._body = body

    async def json(self) -> dict:
        return self._body


class _ArtifactRequest(_Request):
    def __init__(self, token: str, artifact_id: str = "") -> None:
        super().__init__(token)
        self.match_info = {"artifact_id": artifact_id}


class _ChatRequest(_Request):
    def __init__(self, token: str, body: dict) -> None:
        super().__init__(token)
        self._body = body
        self.path_qs = "/v1/chat/completions"

    async def json(self) -> dict:
        return self._body


def _adapter_with_two_users(tmp_path, *, quotas_enabled=False):
    adapter = APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "product_auth_enabled": True,
                "product_auth_db": str(tmp_path / "access.db"),
                "product_artifact_root": str(tmp_path / "artifacts"),
                "product_quotas_enabled": quotas_enabled,
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
    adapter, first_token, second_token = _adapter_with_two_users(
        tmp_path, quotas_enabled=True
    )
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


def test_product_requests_are_unmetered_while_quota_enforcement_is_disabled(
    tmp_path,
) -> None:
    adapter, first_token, _ = _adapter_with_two_users(tmp_path)
    request = _Request(first_token)
    assert adapter._check_auth(request) is None
    principal = request["troika_product_principal"]

    for _ in range(3):
        assert adapter._consume_product_request_quota(request) is None

    assert "troika_usage" not in request
    assert adapter._access_registry.daily_usage(principal.user_id) == 0


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
    assert payload["features"]["private_artifacts"] is True
    assert payload["features"]["product_quota_enforcement"] is False
    assert payload["features"]["screen_snapshot"] is False
    assert payload["features"]["screen_snapshot_external_vision"] is False
    assert "artifacts" in payload["endpoints"]


def test_product_artifact_api_is_owner_scoped(tmp_path) -> None:
    adapter, first_token, second_token = _adapter_with_two_users(tmp_path)
    first = _ArtifactRequest(first_token)
    second = _ArtifactRequest(second_token)
    assert adapter._check_auth(first) is None
    assert adapter._check_auth(second) is None
    first_principal = first["troika_product_principal"]
    artifact = adapter._artifact_store.create(
        user_id=first_principal.user_id,
        device_id=first_principal.device_id,
        filename="Личный отчёт",
        kind="pdf",
        data=b"%PDF-private",
    )

    listed = asyncio.run(adapter._handle_list_artifacts(_ArtifactRequest(first_token)))
    listed_payload = json.loads(listed.body)
    assert listed.status == 200
    assert [item["id"] for item in listed_payload["data"]] == [artifact.id]
    assert all("path" not in item for item in listed_payload["data"])

    hidden_download = asyncio.run(
        adapter._handle_download_artifact(_ArtifactRequest(second_token, artifact.id))
    )
    hidden_delete = asyncio.run(
        adapter._handle_delete_artifact(_ArtifactRequest(second_token, artifact.id))
    )
    assert hidden_download.status == 404
    assert hidden_delete.status == 404

    downloaded = asyncio.run(
        adapter._handle_download_artifact(_ArtifactRequest(first_token, artifact.id))
    )
    assert downloaded.status == 200
    assert downloaded.body == b"%PDF-private"
    assert downloaded.headers["X-Content-Type-Options"] == "nosniff"

    deleted = asyncio.run(
        adapter._handle_delete_artifact(_ArtifactRequest(first_token, artifact.id))
    )
    assert deleted.status == 200
    assert adapter._artifact_store.read_for_user(first_principal.user_id, artifact.id) is None


def test_product_device_context_requires_explicit_consent(tmp_path) -> None:
    adapter, first_token, _ = _adapter_with_two_users(tmp_path)
    request = _Request(first_token)
    assert adapter._check_auth(request) is None
    assert not adapter._product_device_context_allowed(request)

    request.headers["X-Troika-Device-Context-Consent"] = "granted"
    assert adapter._product_device_context_allowed(request)


def test_product_chat_never_receives_operator_active_project_context(
    tmp_path, monkeypatch
) -> None:
    adapter, first_token, _ = _adapter_with_two_users(tmp_path)
    captured = {}

    async def fake_run_agent(**kwargs):
        captured.update(kwargs)
        return (
            {"final_response": "ok", "messages": [], "session_id": "private"},
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )

    monkeypatch.setattr(
        "tools.project_tool.get_active_project_summary",
        lambda: '[ACTIVE_PROJECT path="D:\\operator-secret"]',
    )
    monkeypatch.setattr(adapter, "_run_agent", fake_run_agent)
    request = _ChatRequest(
        first_token,
        {
            "messages": [
                {"role": "system", "content": "Product system"},
                {"role": "user", "content": "hello"},
            ]
        },
    )

    response = asyncio.run(adapter._handle_chat_completions(request))

    assert response.status == 200
    assert captured["ephemeral_system_prompt"] == "Product system"


def test_product_toolset_only_exposes_paired_phone_safe_slice() -> None:
    tools = resolve_toolset("troika-product")
    assert {"web_search", "vision_analyze", "image_generate"} <= set(tools)
    assert {
        "android_status",
        "android_open_app",
        "android_set_alarm",
        "android_navigate",
        "troika_create_docx",
        "troika_create_pdf",
        "troika_create_pptx",
    } <= set(tools)
    forbidden = {
        "terminal",
        "process",
        "read_file",
        "write_file",
        "pc_gui_control",
        "pc_see_screen",
        "android_send_sms",
        "android_call",
        "android_file_read",
        "android_file_write",
        "android_file_delete",
        "android_screenshot",
        "troika_screen_snapshot",
        "android_calendar_create_event",
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


def test_product_screen_toolset_requires_explicit_external_vision_opt_in(
    tmp_path, monkeypatch
) -> None:
    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("run_agent.AIAgent", FakeAgent)
    monkeypatch.setattr(
        "gateway.run._resolve_runtime_agent_kwargs", lambda: {"api_key": "test"}
    )
    monkeypatch.setattr("gateway.run._resolve_gateway_model", lambda: "test/model")
    monkeypatch.setattr("gateway.run._load_gateway_config", lambda: {})
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
                "product_screen_snapshot_enabled": True,
                "product_screen_external_vision_enabled": True,
            },
        )
    )
    monkeypatch.setattr(adapter, "_ensure_session_db", lambda: None)

    adapter._create_agent()
    assert captured["enabled_toolsets"] == [
        "troika-product",
        "troika-screen-snapshot",
    ]


def test_product_action_rejects_session_wide_confirmation(tmp_path) -> None:
    from tools.approval import _ApprovalEntry, _gateway_queues, unregister_gateway_notify

    adapter, first_token, _ = _adapter_with_two_users(tmp_path)
    principal = adapter._access_registry.authenticate(first_token)
    assert principal is not None
    run_id = "run_phone_action"
    approval_session = "approval_phone_action"
    adapter._run_statuses[run_id] = {"run_id": run_id, "status": "waiting_for_approval"}
    adapter._run_owners[run_id] = (principal.user_id, principal.device_id)
    adapter._run_approval_sessions[run_id] = approval_session
    _gateway_queues[approval_session] = [
        _ApprovalEntry(
            {
                "choices": ["once", "deny"],
                "product_action": True,
            }
        )
    ]
    try:
        response = asyncio.run(
            adapter._handle_run_approval(
                _ApprovalRequest(first_token, run_id, {"choice": "session"})
            )
        )
        payload = json.loads(response.body)
        assert response.status == 400
        assert payload["error"]["code"] == "invalid_approval_choice"
    finally:
        unregister_gateway_notify(approval_session)
