"""Authenticated HTTP integration for personal notification preferences."""

import asyncio
import json
from unittest.mock import patch

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestClient, TestServer

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from troika_product.notifications import NotificationPreferences


def _adapter(tmp_path, *, product=True):
    return APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": product, "product_auth_db": str(tmp_path / "access.db"),
        "product_artifact_root": str(tmp_path / "artifacts"), "key": "test-legacy-key",
        "host": "127.0.0.1", "port": 0,
    }))


def _token(registry, email):
    user = registry.create_user(email)
    return registry.issue_device_token(registry.create_device(user, name="Phone", platform="android"))


def test_http_preferences_auth_isolation_validation_and_revocation(tmp_path):
    async def scenario():
        adapter = _adapter(tmp_path)
        registry = adapter._access_registry
        first = _token(registry, "one@example.com")
        second = _token(registry, "two@example.com")
        path = "/v1/notification-preferences"
        # Use connect's real route registration, not a separately assembled app.
        with patch("tools.job_runner.cleanup_orphan_jobs", return_value=0), \
             patch("tools.job_runner.ensure_watchdog_started"):
            assert await adapter.connect()
        try:
            port = adapter._site._server.sockets[0].getsockname()[1]
            async with ClientSession(base_url=f"http://127.0.0.1:{port}") as client:
                h1 = {"Authorization": f"Bearer {first}"}
                h2 = {"Authorization": f"Bearer {second}"}
                assert (await client.get(path)).status == 401
                assert (await client.put(path, json={})).status == 401
                settings = NotificationPreferences(reminders_enabled=True, timezone="Europe/Moscow").to_dict()
                response = await client.put(path, json=settings, headers=h1)
                assert response.status == 200
                assert response.headers["Cache-Control"] == "no-store"
                assert await response.json() == settings
                assert await (await client.get(path, headers=h1)).json() == settings
                assert await (await client.get(path, headers=h2)).json() == NotificationPreferences().to_dict()
                for invalid in ({**settings, "user_id": registry.authenticate(second).user_id},
                                {**settings, "reminders_enabled": "false"}, [], {}):
                    assert (await client.put(path, json=invalid, headers=h1)).status == 400
                assert (await client.put(path, data="{bad-json", headers=h1)).status == 400
                assert await (await client.get(path, headers=h1)).json() == settings
                principal = registry.authenticate(first)
                assert len(registry.list_audit_events(principal.user_id)) == 1
                capabilities = await (await client.get("/v1/capabilities", headers=h1)).json()
                assert capabilities["features"]["notification_preferences"] is True
                assert capabilities["endpoints"]["notification_preferences_update"]["path"] == path
                registry.revoke_token(first)
                assert (await client.get(path, headers=h1)).status == 401
                assert (await client.put(path, json=settings, headers=h1)).status == 401
        finally:
            await adapter.disconnect()
    asyncio.run(scenario())


def test_legacy_and_storage_failure_do_not_expose_preferences(tmp_path):
    async def scenario():
        path = "/v1/notification-preferences"
        for product in (False, True):
            adapter = _adapter(tmp_path, product=product)
            token = _token(adapter._access_registry, "one@example.com") if product else "test-legacy-key"
            app = web.Application()
            app.router.add_get(path, adapter._handle_notification_preferences)
            async with TestClient(TestServer(app)) as client:
                headers = {"Authorization": f"Bearer {token}"}
                if product:
                    with patch.object(adapter._access_registry, "notification_preferences", side_effect=RuntimeError("private db path")):
                        response = await client.get(path, headers=headers)
                    assert response.status == 503
                    assert "private db path" not in json.dumps(await response.json())
                else:
                    assert (await client.get(path, headers=headers)).status == 404
    asyncio.run(scenario())
