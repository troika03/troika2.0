"""
WebSocket-мост между Hermes (на PC) и приложением Hermes на Android-телефоне.

Поток:
- Телефон подключается к ``ws://host:8642/v1/phone/commands`` и держит соединение открытым.
- Hermes-инструменты (``android_open_app`` и т.д.) вызывают ``send_command(...)``
  чтобы передать действие на телефон.
- Телефон выполняет действие и присылает обратно JSON ``{"id": ..., "result": ...}``.
- Корутина-инструмент ждёт ``asyncio.Future`` пока не придёт ответ или не сработает таймаут.

Аутентификация: тот же ``Bearer <API_SERVER_KEY>`` что и для остальных эндпойнтов.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any, Dict, Optional

from aiohttp import WSMsgType, web

logger = logging.getLogger(__name__)


class PhoneBridge:
    """Единый канал к подключённому телефону. Один экземпляр на процесс."""

    def __init__(self) -> None:
        self._ws: Optional[web.WebSocketResponse] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def send_command(
        self,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        """Послать команду на телефон и дождаться результата."""
        if not self.is_connected():
            return {"ok": False, "error": "phone_not_connected"}

        request_id = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        payload = {"id": request_id, "action": action, "params": params or {}}
        try:
            assert self._ws is not None
            # ВАЖНО: ограничиваем сам ws.send_json таймаутом. Если телефон числится
            # connected, но сокет мёртв (ушёл без close), send_json виснет навсегда
            # и вешает вызывающую корутину (напр. автопилот). Не даём ей висеть.
            await asyncio.wait_for(self._ws.send_json(payload), timeout=min(5.0, timeout))
        except Exception as e:
            self._pending.pop(request_id, None)
            return {"ok": False, "error": f"send_failed: {e}"}

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            return {"ok": False, "error": "timeout"}

    async def handle_connection(self, request: web.Request) -> web.WebSocketResponse:
        """Обработчик ``/v1/phone/commands`` — держит WebSocket-соединение."""
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=16 * 1024 * 1024)
        await ws.prepare(request)

        # Замещаем предыдущее соединение если есть
        async with self._lock:
            if self._ws is not None and not self._ws.closed:
                try:
                    await self._ws.close(code=1001, message=b"replaced")
                except Exception:
                    pass
            self._ws = ws

        client_addr = request.remote
        logger.info("Phone connected from %s", client_addr)

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_message(msg.data)
                elif msg.type == WSMsgType.ERROR:
                    logger.warning("Phone WS error: %s", ws.exception())
                    break
        finally:
            async with self._lock:
                if self._ws is ws:
                    self._ws = None
            # Резолвим все pending futures чтобы не висели
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_result({"ok": False, "error": "connection_closed"})
            self._pending.clear()
            logger.info("Phone disconnected: %s", client_addr)

        return ws

    async def _handle_message(self, data: str) -> None:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Phone sent bad JSON: %r", data[:200])
            return

        # Это либо ответ на наш запрос, либо событие от телефона (например wake_word)
        msg_id = payload.get("id")
        if msg_id and msg_id in self._pending:
            fut = self._pending.pop(msg_id)
            if not fut.done():
                fut.set_result(payload.get("result") or {"ok": True})
            return

        event = payload.get("event")
        if event:
            logger.debug("Phone event %s: %s", event, payload)
            # Хук для будущей расширяемости (например wake_word_detected → телеграм)
            return


# Глобальный синглтон, который импортируется и в api_server.py, и в android_tool.py
bridge = PhoneBridge()


class ProductPhoneBridge:
    """Device-bound WebSocket bridge used by the hosted Troika product.

    ``PhoneBridge`` above is kept for a single-user local Hermes install.  It
    intentionally has only one socket and must never be used for a hosted
    product: a later connection could otherwise receive another customer's
    commands.  This bridge keeps independent connections and pending requests
    per authenticated device id.
    """

    # This is deliberately a small first product slice.  The bridge rejects
    # every other legacy Android action even if a caller somehow reaches its
    # handler without a tool schema.
    ALLOWED_ACTIONS = frozenset(
        {
            "status",
            "battery",
            "network",
            "open_app",
            "web_search",
            "set_alarm",
            "set_timer",
            "navigate",
            "volume",
            "brightness",
            "torch",
            "camera_photo",
            "screen_snapshot",
        }
    )
    READ_ONLY_ACTIONS = frozenset({"status", "battery", "network"})

    def __init__(self) -> None:
        self._connections: Dict[str, web.WebSocketResponse] = {}
        self._pending: Dict[tuple[str, str], asyncio.Future] = {}
        self._lock = asyncio.Lock()

    def is_connected(self, device_id: str) -> bool:
        ws = self._connections.get(device_id)
        return ws is not None and not ws.closed

    @classmethod
    def is_allowed_action(cls, action: str) -> bool:
        return action in cls.ALLOWED_ACTIONS

    @classmethod
    def requires_confirmation(cls, action: str) -> bool:
        return action in cls.ALLOWED_ACTIONS and action not in cls.READ_ONLY_ACTIONS

    async def send_command(
        self,
        device_id: str,
        action: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        """Send an allowlisted command to exactly one authenticated device."""
        if not device_id:
            return {"ok": False, "error": "product_device_required"}
        if not self.is_allowed_action(action):
            return {"ok": False, "error": "product_action_not_available"}

        async with self._lock:
            ws = self._connections.get(device_id)
        if ws is None or ws.closed:
            return {"ok": False, "error": "phone_not_connected"}

        request_id = uuid.uuid4().hex
        key = (device_id, request_id)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[key] = future
        payload = {"id": request_id, "action": action, "params": params or {}}
        try:
            await asyncio.wait_for(ws.send_json(payload), timeout=min(5.0, timeout))
        except Exception:
            self._pending.pop(key, None)
            return {"ok": False, "error": "phone_command_send_failed"}

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result if isinstance(result, dict) else {"ok": True}
        except asyncio.TimeoutError:
            self._pending.pop(key, None)
            return {"ok": False, "error": "phone_command_timeout"}

    async def disconnect_devices(self, device_ids: set[str]) -> None:
        """Close revoked device sockets and release their pending commands."""
        clean_ids = {str(device_id) for device_id in device_ids if device_id}
        async with self._lock:
            sockets = [
                self._connections.pop(device_id, None) for device_id in clean_ids
            ]
            pending_keys = [key for key in self._pending if key[0] in clean_ids]
        for key in pending_keys:
            future = self._pending.pop(key, None)
            if future is not None and not future.done():
                future.set_result({"ok": False, "error": "device_access_revoked"})
        for ws in sockets:
            if ws is not None and not ws.closed:
                try:
                    await ws.close(code=1008, message=b"device access revoked")
                except Exception:
                    logger.debug("Failed to close revoked product phone socket")

    async def handle_connection(
        self,
        request: web.Request,
        device_id: str,
        *,
        lifecycle_callback: Optional[Callable[[str], None]] = None,
    ) -> web.WebSocketResponse:
        """Keep a product phone connection scoped to *device_id* only."""
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=1024 * 1024)
        await ws.prepare(request)

        previous: Optional[web.WebSocketResponse]
        async with self._lock:
            previous = self._connections.get(device_id)
            self._connections[device_id] = ws
        if previous is not None and previous is not ws and not previous.closed:
            try:
                await previous.close(code=1001, message=b"replaced")
            except Exception:
                pass
        if lifecycle_callback is not None:
            lifecycle_callback("connected")

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_message(device_id, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    logger.warning("Product phone WS error for device %s", device_id)
                    break
        finally:
            async with self._lock:
                if self._connections.get(device_id) is ws:
                    self._connections.pop(device_id, None)
                    pending_keys = [key for key in self._pending if key[0] == device_id]
                else:
                    pending_keys = []
            for key in pending_keys:
                future = self._pending.pop(key, None)
                if future is not None and not future.done():
                    future.set_result({"ok": False, "error": "phone_connection_closed"})
            if lifecycle_callback is not None:
                lifecycle_callback("disconnected")

        return ws

    async def _handle_message(self, device_id: str, data: str) -> None:
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("Product phone sent invalid JSON for device %s", device_id)
            return
        msg_id = payload.get("id")
        if not isinstance(msg_id, str) or not msg_id:
            return
        future = self._pending.pop((device_id, msg_id), None)
        if future is not None and not future.done():
            result = payload.get("result")
            future.set_result(result if isinstance(result, dict) else {"ok": True})


# Separate singleton from the legacy local-only bridge above.  Product callers
# must supply an authenticated device id for every status check and command.
product_bridge = ProductPhoneBridge()
