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
