import asyncio
import base64
import json

from gateway.session_context import clear_session_override, set_session_override
from tools import troika_screen_tool
from troika_product.access import AccessRegistry


class _FakeBridge:
    def __init__(self):
        self.calls = []

    def is_connected(self, device_id):
        return bool(device_id)

    async def send_command(self, device_id, action, params, timeout=0):
        self.calls.append((device_id, action, params, timeout))
        jpeg = b"\xff\xd8\xff" + b"safe-frame"
        return {
            "ok": True,
            "vision_session_id": params["vision_session_id"],
            "session_nonce": params["session_nonce"],
            "width": 720,
            "height": 1280,
            "image": base64.b64encode(jpeg).decode("ascii"),
        }


def _identity(tmp_path):
    database = tmp_path / "access.db"
    registry = AccessRegistry(database)
    user_id = registry.create_user("owner@example.com")
    token = registry.issue_device_token(
        registry.create_device(user_id, name="Phone", platform="android")
    )
    principal = registry.authenticate(token)
    assert principal is not None
    return database, principal


def _overrides(database, principal):
    return {
        "TROIKA_PRODUCT_MODE": "1",
        "TROIKA_PRODUCT_USER_ID": principal.user_id,
        "TROIKA_PRODUCT_DEVICE_ID": principal.device_id,
        "TROIKA_PRODUCT_TOKEN_ID": principal.token_id,
        "TROIKA_PRODUCT_ACCESS_DB": str(database),
        "TROIKA_PRODUCT_SCREEN_SNAPSHOT_ENABLED": "1",
        "TROIKA_PRODUCT_SCREEN_EXTERNAL_VISION_ENABLED": "1",
    }


def test_screen_snapshot_requires_both_feature_flags():
    set_session_override("TROIKA_PRODUCT_SCREEN_SNAPSHOT_ENABLED", "1")
    try:
        assert not troika_screen_tool._available()
    finally:
        clear_session_override("TROIKA_PRODUCT_SCREEN_SNAPSHOT_ENABLED")


def test_screen_snapshot_returns_analysis_without_raw_frame(tmp_path, monkeypatch):
    database, principal = _identity(tmp_path)
    fake_bridge = _FakeBridge()
    seen = {}

    async def analyze(data_url, question):
        seen["data_url"] = data_url
        seen["question"] = question
        return "На экране открыта безопасная тестовая страница."

    monkeypatch.setattr(
        "gateway.platforms.phone_bridge.product_bridge", fake_bridge
    )
    monkeypatch.setattr(
        "tools.approval.request_gateway_approval",
        lambda *_args, **_kwargs: {"approved": True},
    )
    monkeypatch.setattr(troika_screen_tool, "_analyze_in_memory", analyze)
    overrides = _overrides(database, principal)
    try:
        for name, value in overrides.items():
            set_session_override(name, value)
        payload = json.loads(
            asyncio.run(troika_screen_tool._handle({"question": "Что видно?"}))
        )
    finally:
        for name in reversed(overrides):
            clear_session_override(name)

    assert payload["ok"] is True
    assert payload["frame_persisted"] is False
    assert "image" not in payload
    assert "data:" not in json.dumps(payload)
    assert seen["data_url"].startswith("data:image/jpeg;base64,")
    assert fake_bridge.calls[0][1] == "screen_snapshot"


def test_screen_snapshot_does_not_capture_when_approval_is_denied(
    tmp_path, monkeypatch
):
    database, principal = _identity(tmp_path)
    fake_bridge = _FakeBridge()
    monkeypatch.setattr(
        "gateway.platforms.phone_bridge.product_bridge", fake_bridge
    )
    monkeypatch.setattr(
        "tools.approval.request_gateway_approval",
        lambda *_args, **_kwargs: {"approved": False},
    )
    overrides = _overrides(database, principal)
    try:
        for name, value in overrides.items():
            set_session_override(name, value)
        payload = json.loads(
            asyncio.run(troika_screen_tool._handle({"question": "Что видно?"}))
        )
    finally:
        for name in reversed(overrides):
            clear_session_override(name)

    assert payload == {"ok": False, "error": "screen_snapshot_not_confirmed"}
    assert fake_bridge.calls == []


def test_screen_snapshot_rejects_oversized_frame_before_vision(tmp_path, monkeypatch):
    database, principal = _identity(tmp_path)
    fake_bridge = _FakeBridge()

    async def oversized(device_id, action, params, timeout=0):
        fake_bridge.calls.append((device_id, action, params, timeout))
        return {
            "ok": True,
            "vision_session_id": params["vision_session_id"],
            "session_nonce": params["session_nonce"],
            "width": 720,
            "height": 1280,
            "image": "A" * (troika_screen_tool._MAX_BASE64_CHARS + 1),
        }

    fake_bridge.send_command = oversized
    monkeypatch.setattr(
        "gateway.platforms.phone_bridge.product_bridge", fake_bridge
    )
    monkeypatch.setattr(
        "tools.approval.request_gateway_approval",
        lambda *_args, **_kwargs: {"approved": True},
    )

    async def should_not_run(*_args):
        raise AssertionError("vision must not receive an oversized frame")

    monkeypatch.setattr(troika_screen_tool, "_analyze_in_memory", should_not_run)
    overrides = _overrides(database, principal)
    try:
        for name, value in overrides.items():
            set_session_override(name, value)
        payload = json.loads(
            asyncio.run(troika_screen_tool._handle({"question": "Что видно?"}))
        )
    finally:
        for name in reversed(overrides):
            clear_session_override(name)

    assert payload == {"ok": False, "error": "invalid_or_oversized_frame"}
