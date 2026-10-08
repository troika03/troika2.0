"""Product-auth integration checks for the OpenAI-compatible API server."""

import asyncio
from io import BytesIO
import json
import sqlite3
import pytest
from zipfile import ZipFile

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from hermes_state import SessionDB
from toolsets import resolve_toolset
from troika_product.notifications import NotificationPreferences
from troika_product.vision_sessions import VisionSessionStore


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


class _AccountRequest(_ChatRequest):
    def __init__(self, token: str, body: dict) -> None:
        super().__init__(token, body)
        self.method = "DELETE"
        self.path_qs = "/v1/account"


class _DeviceRequest(_Request):
    def __init__(self, token: str, device_id: str = "", *, method: str = "GET") -> None:
        super().__init__(token)
        self.method = method
        self.match_info = {"device_id": device_id}
        self.path_qs = (
            f"/v1/account/devices/{device_id}"
            if device_id
            else "/v1/account/devices"
        )


def _adapter_with_two_users(tmp_path, *, quotas_enabled=True):
    adapter = APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "product_auth_enabled": True,
                "product_auth_db": str(tmp_path / "access.db"),
                "product_artifact_root": str(tmp_path / "artifacts"),
                "product_workspace_root": str(tmp_path / "workspaces"),
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


def test_product_registration_and_login_issue_device_tokens(tmp_path) -> None:
    adapter = APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "product_auth_enabled": True,
                "product_auth_db": str(tmp_path / "access.db"),
            },
        )
    )
    registration = asyncio.run(
        adapter._handle_product_register(
            _ChatRequest(
                "",
                {
                    "email": "new@example.com",
                    "password": "safe-password-123",
                    "device_name": "Test Pixel",
                    "platform": "android",
                },
            )
        )
    )
    registered = json.loads(registration.body)
    assert registration.status == 201
    assert registered["account"]["plan"] == "free"
    assert registered["home_session_id"].startswith("ses_")
    assert registered["refresh_token"].startswith("trk_refresh_")
    assert 0 < registered["expires_in"] <= 86_400
    assert adapter._access_registry.authenticate(registered["token"]) is not None

    login = asyncio.run(
        adapter._handle_product_login(
            _ChatRequest(
                "",
                {
                    "email": "new@example.com",
                    "password": "safe-password-123",
                    "device_name": "Test Windows",
                    "platform": "windows",
                },
            )
        )
    )
    logged_in = json.loads(login.body)
    assert login.status == 200
    assert logged_in["home_session_id"] == registered["home_session_id"]
    assert logged_in["refresh_token"].startswith("trk_refresh_")
    assert adapter._access_registry.authenticate(logged_in["token"]) is not None

    refreshed = asyncio.run(
        adapter._handle_product_refresh(
            _ChatRequest("", {"refresh_token": logged_in["refresh_token"]})
        )
    )
    refreshed_body = json.loads(refreshed.body)
    assert refreshed.status == 200
    assert refreshed_body["token"] != logged_in["token"]
    assert refreshed_body["refresh_token"] != logged_in["refresh_token"]
    assert refreshed_body["home_session_id"] == registered["home_session_id"]
    replay = asyncio.run(
        adapter._handle_product_refresh(
            _ChatRequest("", {"refresh_token": logged_in["refresh_token"]})
        )
    )
    assert replay.status == 401


def test_product_registration_rejects_duplicate_and_bad_password(tmp_path) -> None:
    adapter = APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "product_auth_enabled": True,
                "product_auth_db": str(tmp_path / "access.db"),
            },
        )
    )
    body = {
        "email": "new@example.com",
        "password": "safe-password-123",
        "device_name": "Test Pixel",
        "platform": "android",
    }
    assert (
        asyncio.run(adapter._handle_product_register(_ChatRequest("", body))).status
        == 201
    )
    assert (
        asyncio.run(adapter._handle_product_register(_ChatRequest("", body))).status
        == 409
    )

    bad_login = asyncio.run(
        adapter._handle_product_login(
            _ChatRequest("", {**body, "password": "wrong-password"})
        )
    )
    assert bad_login.status == 401


def test_product_logout_all_revokes_every_owned_token(tmp_path) -> None:
    adapter, first_token, second_token = _adapter_with_two_users(tmp_path)
    registry = adapter._access_registry
    request = _Request(first_token)
    assert adapter._check_auth(request) is None
    principal = request["troika_product_principal"]
    extra_device = registry.create_device(
        principal.user_id, name="Laptop", platform="windows"
    )
    extra_token = registry.issue_device_token(extra_device)

    response = asyncio.run(adapter._handle_product_logout_all(request))

    assert response.status == 200
    assert json.loads(response.body)["reauthentication_required"] is True
    assert registry.authenticate(first_token) is None
    assert registry.authenticate(extra_token) is None
    assert registry.authenticate(second_token) is not None


def test_product_auth_ignores_legacy_server_key_and_derives_memory_scope(
    tmp_path,
) -> None:
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

    assert (
        adapter._authorize_product_session(first, "private-session", claim=True) is None
    )
    assert (
        adapter._authorize_product_session(second, "private-session", claim=True).status
        == 403
    )


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


def test_product_quotas_are_enabled_when_not_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("TROIKA_PRODUCT_QUOTAS_ENABLED", raising=False)
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True,
        "product_auth_db": str(tmp_path / "access.db"),
    }))
    assert adapter._product_quotas_enabled is True


@pytest.mark.parametrize("endpoint", ["runs", "chat_completions"])
def test_exhausted_quota_blocks_both_agent_entry_points(tmp_path, monkeypatch, endpoint):
    adapter, token, _ = _adapter_with_two_users(tmp_path)
    principal = adapter._access_registry.authenticate(token)
    adapter._access_registry.set_entitlement(
        principal.user_id, plan="free", daily_request_limit=1
    )
    adapter._access_registry.consume_chat_request(principal)
    body = {"input": "test"} if endpoint == "runs" else {
        "messages": [{"role": "user", "content": "test"}]
    }
    def fail_if_agent_starts(*args, **kwargs):
        pytest.fail("an exhausted quota must not start an agent")
    monkeypatch.setattr(adapter, "_create_agent", fail_if_agent_starts)
    response = asyncio.run(getattr(adapter, f"_handle_{endpoint}")(_ChatRequest(token, body)))
    assert response.status == 429
    payload = json.loads(response.body)
    assert payload["error"]["code"] == "daily_request_limit_exceeded"
    assert payload["usage"]["remaining"] == 0
    assert payload["usage"]["resets_at"].endswith("T00:00:00+00:00")
    assert int(response.headers["Retry-After"]) > 0
    assert adapter._access_registry.daily_usage(principal.user_id) == 1


def test_usage_service_failure_does_not_allow_unmetered_work(tmp_path, monkeypatch):
    adapter, token, _ = _adapter_with_two_users(tmp_path)
    request = _Request(token)
    assert adapter._check_auth(request) is None
    def unavailable(*args, **kwargs):
        raise RuntimeError("usage unavailable")
    monkeypatch.setattr(adapter._access_registry, "consume_chat_request", unavailable)
    response = adapter._consume_product_request_quota(request)
    assert response.status == 503


def test_product_device_list_and_revoke_close_device_activity(
    tmp_path, monkeypatch
) -> None:
    from gateway.platforms.phone_bridge import product_bridge
    from tools.approval import _ApprovalEntry, _gateway_queues

    adapter, first_token, second_token = _adapter_with_two_users(tmp_path)
    registry = adapter._access_registry
    first_request = _Request(first_token)
    second_request = _Request(second_token)
    assert adapter._check_auth(first_request) is None
    assert adapter._check_auth(second_request) is None
    first = first_request["troika_product_principal"]
    second = second_request["troika_product_principal"]
    extra_device = registry.create_device(
        first.user_id, name="First laptop", platform="windows"
    )
    extra_token = registry.issue_device_token(extra_device)
    extra_second_token = registry.issue_device_token(extra_device)
    stale_extra_request = _Request(extra_token)
    assert adapter._check_auth(stale_extra_request) is None

    disconnected: list[set[str]] = []

    async def fake_disconnect(device_ids: set[str]) -> None:
        disconnected.append(device_ids)

    monkeypatch.setattr(product_bridge, "disconnect_devices", fake_disconnect)

    listed = asyncio.run(adapter._handle_account_devices(_DeviceRequest(first_token)))
    listed_payload = json.loads(listed.body)
    assert listed.status == 200
    assert listed.headers["Cache-Control"] == "private, no-store"
    assert {item["id"] for item in listed_payload["devices"]} == {
        first.device_id,
        extra_device,
    }
    assert all(
        set(item) == {
            "id",
            "name",
            "platform",
            "status",
            "created_at",
            "current",
        }
        for item in listed_payload["devices"]
    )
    assert next(
        item for item in listed_payload["devices"] if item["id"] == first.device_id
    )["current"]

    denied = asyncio.run(
        adapter._handle_revoke_account_device(
            _DeviceRequest(first_token, second.device_id, method="DELETE")
        )
    )
    assert denied.status == 404
    assert registry.authenticate(second_token) == second
    denied_event = registry.list_audit_events(first.user_id)[0]
    assert denied_event.event_type == "device.revoke_denied"
    assert second.device_id not in json.dumps(denied_event.details)
    assert first_token not in json.dumps(denied_event.details)

    class FakeAgent:
        def __init__(self) -> None:
            self.interrupt_reason = ""

        def interrupt(self, reason: str) -> None:
            self.interrupt_reason = reason

    async def revoke_extra_device() -> tuple[object, asyncio.Task, asyncio.Queue]:
        run_id = "run_extra_device"
        approval_key = "approval_extra_device"
        agent = FakeAgent()
        queue: asyncio.Queue = asyncio.Queue()
        queue.put_nowait({"event": "message.delta", "delta": "private"})

        async def wait_forever() -> None:
            await asyncio.Event().wait()

        task = asyncio.create_task(wait_forever())
        await asyncio.sleep(0)
        adapter._run_owners[run_id] = (first.user_id, extra_device)
        adapter._run_statuses[run_id] = {"run_id": run_id, "status": "running"}
        adapter._run_streams[run_id] = queue
        adapter._run_streams_created[run_id] = 1.0
        adapter._active_run_agents[run_id] = agent
        adapter._active_run_tasks[run_id] = task
        adapter._run_approval_sessions[run_id] = approval_key
        _gateway_queues[approval_key] = [_ApprovalEntry({"choices": ["once"]})]

        response = await adapter._handle_revoke_account_device(
            _DeviceRequest(first_token, extra_device, method="DELETE")
        )
        assert agent.interrupt_reason == "Device access revoked"
        assert task.cancelled()
        assert approval_key not in _gateway_queues
        assert adapter._run_statuses[run_id]["status"] == "cancelled"
        assert adapter._run_statuses[run_id]["cancellation_reason"] == "device_revoked"
        assert queue.get_nowait() is None
        return response, task, queue

    revoked, _, _ = asyncio.run(revoke_extra_device())
    revoked_payload = json.loads(revoked.body)
    assert revoked.status == 200
    assert revoked_payload == {
        "status": "revoked",
        "device_id": extra_device,
        "current": False,
        "reauthentication_required": False,
    }
    assert disconnected == [{extra_device}]
    assert registry.authenticate(extra_token) is None
    assert registry.authenticate(extra_second_token) is None
    assert adapter._authorize_product_run(
        stale_extra_request, "run_extra_device"
    ).status == 404
    revoked_event = next(
        event
        for event in registry.list_audit_events(first.user_id)
        if event.event_type == "device.revoked"
    )
    assert revoked_event.event_type == "device.revoked"
    assert revoked_event.details == {"current": False}

    revoked_current = asyncio.run(
        adapter._handle_revoke_account_device(
            _DeviceRequest(first_token, first.device_id, method="DELETE")
        )
    )
    assert revoked_current.status == 200
    assert json.loads(revoked_current.body)["current"] is True
    assert json.loads(revoked_current.body)["reauthentication_required"] is True
    assert registry.authenticate(first_token) is None
    assert adapter._check_auth(_Request(first_token)).status == 401


def test_product_requests_are_unmetered_while_quota_enforcement_is_disabled(
    tmp_path,
) -> None:
    adapter, first_token, _ = _adapter_with_two_users(tmp_path, quotas_enabled=False)
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
    assert payload["features"]["private_workspace"] is True
    assert payload["features"]["product_quota_enforcement"] is True
    assert payload["features"]["screen_snapshot"] is False
    assert payload["features"]["screen_snapshot_external_vision"] is False
    assert not any(payload["features"]["experimental"].values())
    assert payload["features"]["account_export"] is True
    assert payload["features"]["account_deletion"] is True
    assert payload["features"]["subscription_status"] is True
    assert "artifacts" in payload["endpoints"]
    assert payload["endpoints"]["account"] == {
        "method": "DELETE",
        "path": "/v1/account",
    }
    assert payload["endpoints"]["account_export"] == {
        "method": "GET",
        "path": "/v1/account/export",
    }
    assert payload["endpoints"]["subscription"] == {
        "method": "GET",
        "path": "/v1/subscription",
    }


def test_product_subscription_status_is_private_and_reports_enforcement(
    tmp_path,
) -> None:
    adapter, first_token, second_token = _adapter_with_two_users(
        tmp_path, quotas_enabled=True
    )
    first_request = _Request(first_token)
    second_request = _Request(second_token)
    assert adapter._check_auth(first_request) is None
    assert adapter._check_auth(second_request) is None
    first = first_request["troika_product_principal"]
    second = second_request["troika_product_principal"]
    adapter._access_registry.set_entitlement(
        first.user_id, plan="plus", daily_request_limit=10
    )
    adapter._access_registry.set_entitlement(
        second.user_id, plan="pro", daily_request_limit=20
    )
    adapter._access_registry.consume_chat_request(first)

    response = asyncio.run(adapter._handle_subscription(_Request(first_token)))
    payload = json.loads(response.body)["subscription"]

    assert response.status == 200
    assert payload["plan"] == "plus"
    assert payload["daily_limit"] == 10
    assert payload["used"] == 1
    assert payload["remaining"] == 9
    assert payload["quota_enforced"] is True
    assert second.user_id not in response.text


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
    assert (
        adapter._artifact_store.read_for_user(first_principal.user_id, artifact.id)
        is None
    )


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
    assert captured["ephemeral_system_prompt"].startswith("Product system\n\n")
    assert "Текущие локальные дата и время пользователя" in captured[
        "ephemeral_system_prompt"
    ]


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
    assert captured["enabled_toolsets"] == ["troika-capabilities"]
    assert captured["skip_memory"] is True


def test_confirmed_account_deletion_purges_all_local_user_data(
    tmp_path, monkeypatch
) -> None:
    adapter, first_token, second_token = _adapter_with_two_users(tmp_path)
    first_request = _Request(first_token)
    second_request = _Request(second_token)
    assert adapter._check_auth(first_request) is None
    assert adapter._check_auth(second_request) is None
    first = first_request["troika_product_principal"]
    second = second_request["troika_product_principal"]
    registry = adapter._access_registry
    first_extra_token = registry.issue_device_token(
        registry.create_device(first.user_id, name="First tablet", platform="android")
    )
    from tools import location_tool

    monkeypatch.setattr(location_tool, "_db_path", lambda: tmp_path / "locations.db")
    monkeypatch.setattr(
        location_tool, "_cache_file", lambda: tmp_path / "device_context.json"
    )
    location_tool._DEVICE_CONTEXT_CACHE.clear()
    location_tool.remember_device_context(first.memory_scope, {"bssid": "first"})
    location_tool.remember_device_context(second.memory_scope, {"bssid": "second"})
    assert location_tool._set({"name": "home"}, first.memory_scope)["ok"]
    assert location_tool._set({"name": "home"}, second.memory_scope)["ok"]

    registry.claim_session(first, "first-private-session")
    registry.claim_session(second, "second-private-session")
    registry.set_notification_preferences(
        first,
        NotificationPreferences(
            reminders_enabled=True,
            proactive_enabled=True,
        ),
    )
    registry.consume_chat_request(first)
    registry.record_audit_event("account.fixture", principal=first)
    adapter._memory_store.create_memory(
        first,
        kind="preference",
        title="Private memory",
        content="First user's private preference",
    )
    second_memory = adapter._memory_store.create_memory(
        second,
        title="Second memory",
        content="Second user's private fact",
    )

    first_project = adapter._proactive_store.create_project(
        first, name="Private project", summary="Private summary"
    )
    first_task = adapter._proactive_store.create_task(
        first, project_id=first_project.id, title="Private task"
    )
    adapter._proactive_store.add_note(
        first,
        project_id=first_project.id,
        content="Private project decision",
        kind="decision",
    )
    adapter._proactive_store.enqueue_message(
        first,
        kind="reminder",
        category="reminder",
        title="Private reminder",
        body="Review the private project result",
        reason="The user explicitly requested this reminder",
        project_id=first_project.id,
        task_id=first_task.id,
    )

    first_artifact = adapter._artifact_store.create(
        user_id=first.user_id,
        device_id=first.device_id,
        filename="private",
        kind="pdf",
        data=b"%PDF-first-private",
    )
    second_artifact = adapter._artifact_store.create(
        user_id=second.user_id,
        device_id=second.device_id,
        filename="second",
        kind="pdf",
        data=b"%PDF-second-private",
    )
    adapter._workspace_store.write_text(
        first.user_id, "private/first.txt", "FIRST WORKSPACE PRIVATE"
    )
    adapter._workspace_store.write_text(
        second.user_id, "private/second.txt", "SECOND WORKSPACE PRIVATE"
    )
    VisionSessionStore(registry.database_path).create(first)

    session_db = SessionDB(db_path=tmp_path / "state.db")
    session_db.create_session("first-private-session", "api_server")
    session_db.append_message("first-private-session", "user", "first private message")
    session_db.create_session("second-private-session", "api_server")
    session_db.append_message(
        "second-private-session", "user", "second private message"
    )
    adapter._session_db = session_db
    adapter._product_sessions_dir = tmp_path / "sessions"
    adapter._product_sessions_dir.mkdir()
    first_transcript = adapter._product_sessions_dir / "first-private-session.jsonl"
    second_transcript = adapter._product_sessions_dir / "second-private-session.jsonl"
    first_transcript.write_text("first private transcript", encoding="utf-8")
    second_transcript.write_text("second private transcript", encoding="utf-8")
    adapter._run_owners["run-first-private"] = (first.user_id, first.device_id)
    adapter._run_statuses["run-first-private"] = {
        "status": "completed",
        "output": "first private output",
    }
    adapter._run_owners["run-second-private"] = (second.user_id, second.device_id)
    adapter._run_statuses["run-second-private"] = {
        "status": "completed",
        "output": "second private output",
    }

    missing_confirmation = asyncio.run(
        adapter._handle_delete_account(_AccountRequest(first_token, {}))
    )
    assert missing_confirmation.status == 400
    assert registry.authenticate(first_token) == first

    deleted = asyncio.run(
        adapter._handle_delete_account(
            _AccountRequest(first_token, {"confirmation": "DELETE_MY_ACCOUNT"})
        )
    )
    assert deleted.status == 200
    assert json.loads(deleted.body) == {"status": "deleted"}
    assert registry.authenticate(first_token) is None
    assert registry.authenticate(first_extra_token) is None
    assert registry.authenticate(second_token) == second
    assert session_db.get_session("first-private-session") is None
    assert session_db.get_session("second-private-session") is not None
    assert not first_transcript.exists()
    assert second_transcript.exists()
    assert "run-first-private" not in adapter._run_statuses
    assert "run-first-private" not in adapter._run_owners
    assert "run-second-private" in adapter._run_statuses
    assert "run-second-private" in adapter._run_owners
    assert (
        adapter._artifact_store.read_for_user(second.user_id, second_artifact.id)
        is not None
    )
    assert adapter._workspace_store.export_files(first.user_id) == []
    assert adapter._workspace_store.read_text(
        second.user_id, "private/second.txt"
    ) == "SECOND WORKSPACE PRIVATE"
    assert [item.id for item in adapter._memory_store.list_memories(second)] == [
        second_memory.id
    ]
    assert location_tool.get_device_context(first.memory_scope) == {}
    assert location_tool.get_device_context(second.memory_scope) == {"bssid": "second"}
    assert location_tool._list(first.memory_scope)["count"] == 0
    assert location_tool._list(second.memory_scope)["count"] == 1
    assert (
        adapter._artifact_store.storage_root.joinpath(
            adapter._artifact_store._user_bucket(first.user_id)
        ).exists()
        is False
    )

    with sqlite3.connect(registry.database_path) as connection:
        account_rows = connection.execute(
            "SELECT COUNT(*) FROM troika_users WHERE id = ?", (first.user_id,)
        ).fetchone()[0]
        leaked_rows = 0
        for table in (
            "troika_devices",
            "troika_sessions",
            "troika_entitlements",
            "troika_usage_daily",
            "troika_audit_events",
            "troika_notification_preferences",
            "troika_memories",
            "troika_artifacts",
            "troika_projects",
            "troika_project_tasks",
            "troika_project_notes",
            "troika_inbox_messages",
            "troika_vision_sessions",
        ):
            leaked_rows += connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (first.user_id,)
            ).fetchone()[0]
    assert account_rows == 0
    assert leaked_rows == 0
    assert first_artifact.id != second_artifact.id
    session_db.close()


def test_account_export_contains_only_authenticated_users_data(
    tmp_path, monkeypatch
) -> None:
    adapter, first_token, second_token = _adapter_with_two_users(tmp_path)
    first_request = _Request(first_token)
    second_request = _Request(second_token)
    assert adapter._check_auth(first_request) is None
    assert adapter._check_auth(second_request) is None
    first = first_request["troika_product_principal"]
    second = second_request["troika_product_principal"]
    registry = adapter._access_registry

    registry.claim_session(first, "first-export-session")
    registry.claim_session(second, "second-export-session")
    registry.set_notification_preferences(
        first, NotificationPreferences(reminders_enabled=True)
    )
    registry.consume_chat_request(first)
    first_project = adapter._proactive_store.create_project(
        first, name="First export project", summary="First export summary"
    )
    first_task = adapter._proactive_store.create_task(
        first, project_id=first_project.id, title="First export task"
    )
    adapter._proactive_store.add_note(
        first,
        project_id=first_project.id,
        content="First export decision",
        kind="decision",
    )
    adapter._proactive_store.enqueue_message(
        first,
        kind="reminder",
        category="reminder",
        title="First export reminder",
        body="Review first export",
        reason="Explicit export fixture reminder",
        project_id=first_project.id,
        task_id=first_task.id,
    )
    adapter._proactive_store.create_project(
        second, name="SECOND USER PRIVATE PROJECT", summary="SECOND PRIVATE SUMMARY"
    )
    adapter._memory_store.create_memory(
        first,
        kind="instruction",
        title="First export memory",
        content="FIRST EXPORT MEMORY CONTENT",
    )
    adapter._memory_store.create_memory(
        second,
        title="SECOND USER PRIVATE MEMORY",
        content="SECOND USER PRIVATE MEMORY CONTENT",
    )
    first_artifact = adapter._artifact_store.create(
        user_id=first.user_id,
        device_id=first.device_id,
        filename="first-export",
        kind="pdf",
        data=b"%PDF-FIRST-EXPORT-CONTENT",
    )
    second_artifact = adapter._artifact_store.create(
        user_id=second.user_id,
        device_id=second.device_id,
        filename="second-private",
        kind="pdf",
        data=b"%PDF-SECOND-USER-PRIVATE-CONTENT",
    )
    adapter._workspace_store.write_text(
        first.user_id, "notes/first.txt", "FIRST WORKSPACE EXPORT CONTENT"
    )
    adapter._workspace_store.write_text(
        second.user_id, "notes/second.txt", "SECOND WORKSPACE PRIVATE CONTENT"
    )
    VisionSessionStore(registry.database_path).create(first)

    session_db = SessionDB(db_path=tmp_path / "state.db")
    session_db.create_session("first-export-session", "api_server")
    session_db.append_message(
        "first-export-session", "user", "FIRST EXPORT PRIVATE MESSAGE"
    )
    session_db.create_session("second-export-session", "api_server")
    session_db.append_message(
        "second-export-session", "user", "SECOND USER PRIVATE MESSAGE"
    )
    adapter._session_db = session_db

    from tools import location_tool

    monkeypatch.setattr(location_tool, "_db_path", lambda: tmp_path / "locations.db")
    monkeypatch.setattr(
        location_tool, "_cache_file", lambda: tmp_path / "device_context.json"
    )
    location_tool._DEVICE_CONTEXT_CACHE.clear()
    location_tool.remember_device_context(first.memory_scope, {"ssid": "FIRST_WIFI"})
    location_tool.remember_device_context(second.memory_scope, {"ssid": "SECOND_WIFI"})
    assert location_tool._set({"name": "FIRST PLACE"}, first.memory_scope)["ok"]
    assert location_tool._set({"name": "SECOND PLACE"}, second.memory_scope)["ok"]

    response = asyncio.run(adapter._handle_export_account(_Request(first_token)))
    assert response.status == 200
    assert response.content_type == "application/zip"
    assert response.headers["Cache-Control"] == "private, no-store"

    with ZipFile(BytesIO(response.body)) as archive:
        names = archive.namelist()
        payload = json.loads(archive.read("troika-data.json"))
        unpacked = b"\n".join(archive.read(name) for name in names)

    data = payload["data"]
    assert data["account"]["id"] == first.user_id
    assert data["account"]["email"] == "one@example.com"
    assert data["projects"][0]["name"] == "First export project"
    assert data["tasks"][0]["title"] == "First export task"
    assert data["notes"][0]["content"] == "First export decision"
    assert data["inbox_messages"][0]["title"] == "First export reminder"
    assert data["memories"][0]["title"] == "First export memory"
    assert data["memories"][0]["content"] == "FIRST EXPORT MEMORY CONTENT"
    assert (
        data["notification_preferences"][0]["preferences_json"]["reminders_enabled"]
        is True
    )
    assert len(data["vision_sessions"]) == 1
    assert data["locations"][0]["device_context"]["ssid"] == "FIRST_WIFI"
    assert (
        data["conversations"][0]["conversation"]["messages"][0]["content"]
        == "FIRST EXPORT PRIVATE MESSAGE"
    )
    assert data["audit_events"][-1]["event_type"] == "account.export_requested"
    assert any(first_artifact.id in name for name in names)
    assert "workspace/notes/first.txt" in names
    assert data["workspace_files"] == [
        {
            "archive_path": "workspace/notes/first.txt",
            "path": "notes/first.txt",
            "size": len(b"FIRST WORKSPACE EXPORT CONTENT"),
        }
    ]
    assert b"%PDF-FIRST-EXPORT-CONTENT" in unpacked
    assert b"FIRST WORKSPACE EXPORT CONTENT" in unpacked

    portable_json = json.dumps(payload, ensure_ascii=False)
    for forbidden in (
        second.user_id,
        "two@example.com",
        "SECOND USER PRIVATE PROJECT",
        "SECOND PRIVATE SUMMARY",
        "SECOND USER PRIVATE MEMORY",
        "SECOND USER PRIVATE MEMORY CONTENT",
        "SECOND USER PRIVATE MESSAGE",
        "SECOND_WIFI",
        "SECOND PLACE",
        "SECOND WORKSPACE PRIVATE CONTENT",
        second_artifact.id,
        "token_digest",
        "nonce_digest",
        "storage_name",
        "system_prompt",
        "reasoning_content",
    ):
        assert forbidden not in portable_json
        assert forbidden.encode("utf-8") not in unpacked
    assert b"%PDF-SECOND-USER-PRIVATE-CONTENT" not in unpacked
    assert b"SECOND WORKSPACE PRIVATE CONTENT" not in unpacked
    assert first_token.encode("utf-8") not in unpacked
    session_db.close()


def test_account_deletion_revokes_access_before_cleanup_failure(
    tmp_path, monkeypatch
) -> None:
    adapter, first_token, _ = _adapter_with_two_users(tmp_path)
    request = _Request(first_token)
    assert adapter._check_auth(request) is None
    principal = request["troika_product_principal"]

    def fail_cleanup(_user_id: str) -> None:
        raise OSError("simulated storage failure")

    monkeypatch.setattr(adapter, "_purge_account_data_sync", fail_cleanup)
    response = asyncio.run(
        adapter._handle_delete_account(
            _AccountRequest(first_token, {"confirmation": "DELETE_MY_ACCOUNT"})
        )
    )

    assert response.status == 202
    assert json.loads(response.body) == {"status": "deletion_pending"}
    assert adapter._access_registry.authenticate(first_token) is None
    assert principal.user_id in adapter._access_registry.pending_account_deletions()


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
        "troika-capabilities",
    ]


def test_product_action_rejects_session_wide_confirmation(tmp_path) -> None:
    from tools.approval import (
        _ApprovalEntry,
        _gateway_queues,
        unregister_gateway_notify,
    )

    adapter, first_token, _ = _adapter_with_two_users(tmp_path)
    principal = adapter._access_registry.authenticate(first_token)
    assert principal is not None
    run_id = "run_phone_action"
    approval_session = "approval_phone_action"
    adapter._run_statuses[run_id] = {"run_id": run_id, "status": "waiting_for_approval"}
    adapter._run_owners[run_id] = (principal.user_id, principal.device_id)
    adapter._run_approval_sessions[run_id] = approval_session
    _gateway_queues[approval_session] = [
        _ApprovalEntry({
            "choices": ["once", "deny"],
            "product_action": True,
        })
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
