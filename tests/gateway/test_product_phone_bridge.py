"""Security checks for the device-bound hosted-phone bridge."""

import asyncio
import json

from gateway.platforms.phone_bridge import ProductPhoneBridge


class _FakeSocket:
    closed = False

    def __init__(self, bridge: ProductPhoneBridge, device_id: str) -> None:
        self.bridge = bridge
        self.device_id = device_id
        self.sent: list[dict] = []

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

        async def respond() -> None:
            await self.bridge._handle_message(
                self.device_id,
                json.dumps({"id": payload["id"], "result": {"ok": True}}),
            )

        asyncio.create_task(respond())


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


def test_product_bridge_marks_only_state_queries_as_read_only() -> None:
    assert not ProductPhoneBridge.requires_confirmation("battery")
    assert ProductPhoneBridge.requires_confirmation("open_app")
    assert not ProductPhoneBridge.requires_confirmation("send_sms")
