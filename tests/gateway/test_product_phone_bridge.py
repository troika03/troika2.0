"""Security checks for the device-bound hosted-phone bridge."""

import asyncio
import json

from gateway.platforms.phone_bridge import ProductPhoneBridge, product_bridge


class _FakeSocket:
    closed = False

    def __init__(self, bridge: ProductPhoneBridge, device_id: str) -> None:
        self.bridge = bridge
        self.device_id = device_id
        self.sent: list[dict] = []
        self.close_code: int | None = None

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

        async def respond() -> None:
            await self.bridge._handle_message(
                self.device_id,
                json.dumps({"id": payload["id"], "result": {"ok": True}}),
            )

        asyncio.create_task(respond())

    async def close(self, *, code: int, message: bytes) -> None:
        self.closed = True
        self.close_code = code


def test_product_bridge_routes_command_only_to_selected_device() -> None:
    async def scenario() -> None:
        bridge = ProductPhoneBridge()
        first = _FakeSocket(bridge, "device-one")
        second = _FakeSocket(bridge, "device-two")
        bridge._connections["device-one"] = first
        bridge._connections["device-two"] = second

        result = await bridge.send_command("device-one", "open_app", {"app": "Maps"})

        assert result == {"ok": True}
        assert len(first.sent) == 1
        assert second.sent == []

    asyncio.run(scenario())


def test_product_bridge_rejects_unlisted_or_unbound_commands() -> None:
    async def scenario() -> None:
        bridge = ProductPhoneBridge()
        socket = _FakeSocket(bridge, "device-one")
        bridge._connections["device-one"] = socket

        blocked = await bridge.send_command("device-one", "send_sms", {"text": "hi"})
        offline = await bridge.send_command("other-device", "open_app", {"app": "Maps"})

        assert blocked["error"] == "product_action_not_available"
        assert offline["error"] == "phone_not_connected"
        assert socket.sent == []

    asyncio.run(scenario())


def test_product_bridge_confirms_only_privacy_sensitive_capture() -> None:
    assert not ProductPhoneBridge.requires_confirmation("battery")
    assert not ProductPhoneBridge.requires_confirmation("open_app")
    assert not ProductPhoneBridge.requires_confirmation("set_alarm")
    assert not ProductPhoneBridge.requires_confirmation("navigate")
    assert not ProductPhoneBridge.requires_confirmation("send_sms")
    assert ProductPhoneBridge.requires_confirmation("screen_snapshot")


def test_product_bridge_disconnects_only_revoked_account_devices() -> None:
    async def scenario() -> None:
        bridge = ProductPhoneBridge()
        revoked = _FakeSocket(bridge, "revoked-device")
        retained = _FakeSocket(bridge, "retained-device")
        bridge._connections["revoked-device"] = revoked
        bridge._connections["retained-device"] = retained
        pending = asyncio.get_running_loop().create_future()
        bridge._pending[("revoked-device", "pending-command")] = pending

        await bridge.disconnect_devices({"revoked-device"})

        assert revoked.closed
        assert revoked.close_code == 1008
        assert not retained.closed
        assert "retained-device" in bridge._connections
        assert await pending == {"ok": False, "error": "device_access_revoked"}

    asyncio.run(scenario())


def test_product_tool_availability_is_scoped_to_current_device() -> None:
    from gateway.session_context import clear_session_override, set_session_override
    from model_tools import _clear_tool_defs_cache, get_tool_definitions
    from tools.registry import invalidate_check_fn_cache

    def tool_names() -> set[str]:
        return {
            item["function"]["name"]
            for item in get_tool_definitions(
                enabled_toolsets=["troika-product"], quiet_mode=True
            )
        }

    previous = dict(product_bridge._connections)
    product_bridge._connections.clear()
    set_session_override("TROIKA_PRODUCT_MODE", "1")
    try:
        set_session_override("TROIKA_PRODUCT_DEVICE_ID", "offline-device")
        _clear_tool_defs_cache()
        invalidate_check_fn_cache()
        assert "android_status" not in tool_names()

        product_bridge._connections["online-device"] = _FakeSocket(
            product_bridge, "online-device"
        )
        set_session_override("TROIKA_PRODUCT_DEVICE_ID", "online-device")
        assert "android_status" in tool_names()

        set_session_override("TROIKA_PRODUCT_DEVICE_ID", "other-offline-device")
        assert "android_status" not in tool_names()
    finally:
        product_bridge._connections.clear()
        product_bridge._connections.update(previous)
        clear_session_override("TROIKA_PRODUCT_DEVICE_ID")
        clear_session_override("TROIKA_PRODUCT_MODE")
        _clear_tool_defs_cache()
        invalidate_check_fn_cache()
