"""Exercise real HTTP/auth boundaries with deterministic in-memory providers."""

import asyncio
import importlib.util
import io
import logging
from pathlib import Path
from types import SimpleNamespace

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from troika_product.access import AccessRegistry
from troika_product import voice


@pytest.fixture
def proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("TROIKA_PRODUCT_AUTH_ENABLED", "true")
    monkeypatch.setenv("TROIKA_PRODUCT_AUTH_DB", str(tmp_path / "access.db"))
    monkeypatch.setenv("TROIKA_PRODUCT_VOICE_ENABLED", "true")
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: None)
    path = Path(__file__).resolve().parents[2] / "hermes-android" / "stt_proxy_server.py"
    spec = importlib.util.spec_from_file_location("test_product_stt_proxy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.STT_BACKEND = "local"
    return module


def issue(registry, email="voice@example.com"):
    user = registry.create_user(email)
    device = registry.create_device(user, name="Test", platform="android")
    return registry.issue_device_token(device)


def upload(payload=b"test audio"):
    data = FormData()
    data.add_field("file", payload, filename="voice.wav", content_type="audio/wav")
    data.add_field("language", "ru")
    return data


async def client_for(handler):
    app = web.Application()
    app.router.add_post("/v1/audio/transcriptions", handler)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.parametrize("bad_access", ["missing", "revoked", "other_user", "no_session"])
def test_denied_voice_never_calls_provider(proxy, monkeypatch, bad_access):
    registry = proxy.ACCESS_REGISTRY
    token = issue(registry)
    owner = registry.authenticate(token)
    registry.claim_session(owner, "private-session")
    if bad_access == "other_user":
        token = issue(registry, "other@example.com")
    elif bad_access == "revoked":
        registry.revoke_token(token)
    elif bad_access == "missing":
        token = "invalid"
    calls = []

    async def provider(*args):
        calls.append(args)
        return "private words", {}

    monkeypatch.setattr(proxy, "_transcribe_local", provider)

    async def check():
        async with await client_for(proxy.transcribe) as client:
            headers = {"Authorization": f"Bearer {token}"}
            if bad_access != "no_session":
                headers["X-Hermes-Session-Id"] = "private-session"
            response = await client.post("/v1/audio/transcriptions", headers=headers, data=upload())
            assert response.status in {401, 403}
        assert not calls
    asyncio.run(check())


def test_same_account_second_device_can_use_owned_session(proxy, monkeypatch):
    registry = proxy.ACCESS_REGISTRY
    first_token = issue(registry)
    owner = registry.authenticate(first_token)
    registry.claim_session(owner, "shared-account-session")
    second_token = registry.issue_device_token(
        registry.create_device(owner.user_id, name="Other", platform="windows")
    )
    calls = []

    async def provider(*args):
        calls.append(args)
        return "Общий аккаунт", {}

    monkeypatch.setattr(proxy, "_transcribe_local", provider)

    async def check():
        async with await client_for(proxy.transcribe) as client:
            response = await client.post(
                "/v1/audio/transcriptions",
                headers={
                    "Authorization": f"Bearer {second_token}",
                    "X-Hermes-Session-Id": "shared-account-session",
                },
                data=upload(),
            )
            assert response.status == 200
            assert (await response.json())["text"] == "Общий аккаунт"
        assert len(calls) == 1

    asyncio.run(check())


def test_transcript_and_provider_errors_never_enter_logs(proxy, monkeypatch, caplog):
    token = issue(proxy.ACCESS_REGISTRY)
    secret_text = "Личный текст пользователя"

    async def provider(*args):
        return secret_text, {}

    monkeypatch.setattr(proxy, "_transcribe_local", provider)
    caplog.set_level(logging.INFO)

    async def check():
        async with await client_for(proxy.transcribe) as client:
            response = await client.post("/v1/audio/transcriptions", headers={
                "Authorization": f"Bearer {token}", "X-Hermes-Session-Id": "session",
            }, data=upload())
            assert response.status == 200
            assert (await response.json())["text"] == secret_text
    asyncio.run(check())
    assert secret_text not in caplog.text
    assert token not in caplog.text


@pytest.mark.parametrize("stop", ["revoke", "disable", "timeout"])
def test_active_voice_is_cancelled(proxy, monkeypatch, stop):
    registry = proxy.ACCESS_REGISTRY
    token = issue(registry)
    monkeypatch.setattr(voice, "ACCESS_POLL_SECONDS", 0.01)
    if stop == "timeout":
        monkeypatch.setattr(voice, "VOICE_TIMEOUT_SECONDS", 0.05)

    async def check():
        started, cancelled = asyncio.Event(), asyncio.Event()

        async def provider(*args):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(proxy, "_transcribe_local", provider)
        async with await client_for(proxy.transcribe) as client:
            pending = asyncio.create_task(client.post("/v1/audio/transcriptions", headers={
                "Authorization": f"Bearer {token}", "X-Hermes-Session-Id": "session",
            }, data=upload()))
            await asyncio.wait_for(started.wait(), 2)
            if stop == "revoke":
                registry.revoke_token(token)
            elif stop == "disable":
                monkeypatch.setenv("TROIKA_PRODUCT_VOICE_ENABLED", "false")
            response = await asyncio.wait_for(pending, 2)
            assert response.status == {"revoke": 401, "disable": 503, "timeout": 504}[stop]
            assert cancelled.is_set()
    asyncio.run(check())


def test_oversized_multipart_rejected_without_provider(proxy, monkeypatch):
    token = issue(proxy.ACCESS_REGISTRY)
    monkeypatch.setattr(voice, "MAX_AUDIO_BYTES", 16)

    async def check():
        async with await client_for(proxy.transcribe) as client:
            response = await client.post("/v1/audio/transcriptions", headers={
                "Authorization": f"Bearer {token}", "X-Hermes-Session-Id": "session",
            }, data=upload(b"x" * 32))
            assert response.status == 413
    asyncio.run(check())


def test_local_decoder_receives_memory_stream(proxy):
    def transcribe(source, **kwargs):
        assert isinstance(source, io.BytesIO)
        assert source.read() == b"audio bytes"
        return [SimpleNamespace(text="Проверка голоса")], SimpleNamespace(language="ru", duration=1)

    proxy._local_model = (SimpleNamespace(transcribe=transcribe), "cpu", "int8")
    text, meta = asyncio.run(proxy._transcribe_local(b"audio bytes", "ru"))
    assert text == "Проверка голоса"
    assert meta["backend"] == "local"


def test_gateway_forwards_only_to_private_stt_and_preserves_session(tmp_path, monkeypatch):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    registry = AccessRegistry(tmp_path / "access.db")
    token = issue(registry)
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True, "product_auth_db": str(registry.database_path),
    }))

    async def check():
        async def upstream(request):
            assert request.headers["Authorization"] == f"Bearer {token}"
            assert request.headers["X-Hermes-Session-Id"] == "shared-session"
            assert await voice.read_audio_upload(request) == (b"test audio", "ru")
            return web.json_response({"text": "Проверка", "internal": "not exposed"})

        async with await client_for(upstream) as worker:
            adapter._product_stt_url = str(worker.make_url("")).rstrip("/")
            async with await client_for(adapter._handle_audio_transcriptions) as gateway:
                response = await gateway.post("/v1/audio/transcriptions", headers={
                    "Authorization": f"Bearer {token}", "X-Hermes-Session-Id": "shared-session",
                }, data=upload())
                assert response.status == 200
                assert await response.json() == {"text": "Проверка"}
                assert registry.session_belongs_to(registry.authenticate(token), "shared-session")
    asyncio.run(check())


def test_gateway_returns_generic_error_when_private_stt_is_unavailable(tmp_path):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True,
        "product_auth_db": str(tmp_path / "access.db"),
        "product_stt_url": "http://127.0.0.1:1",
    }))
    token = issue(adapter._access_registry)

    async def check():
        async with await client_for(adapter._handle_audio_transcriptions) as gateway:
            response = await gateway.post("/v1/audio/transcriptions", headers={
                "Authorization": f"Bearer {token}",
                "X-Hermes-Session-Id": "network-loss",
            }, data=upload())
            assert response.status == 503
            assert await response.json() == {
                "error": "Speech recognition unavailable",
            }

    asyncio.run(check())


def test_tts_uses_stream_without_persisting_audio(tmp_path, monkeypatch, caplog):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    import edge_tts

    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True, "product_auth_db": str(tmp_path / "access.db"),
    }))
    token = issue(adapter._access_registry)

    class Communicate:
        def __init__(self, text, **kwargs):
            assert "emo:" not in text

        async def stream(self):
            yield {"type": "audio", "data": b"mp3-bytes"}

    monkeypatch.setattr(edge_tts, "Communicate", Communicate)
    monkeypatch.setenv("TTS_BACKEND", "edge")

    async def check():
        app = web.Application()
        app.router.add_post("/speech", adapter._handle_audio_speech)
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/speech", headers={"Authorization": f"Bearer {token}"},
                                         json={"input": "[emo:joy] Проверка голоса"})
            assert response.status == 200
            assert await response.read() == b"mp3-bytes"
    asyncio.run(check())
    assert "Проверка голоса" not in caplog.text


def test_gateway_voice_kill_switch_blocks_stt_and_tts(tmp_path):
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
        "product_auth_enabled": True,
        "product_auth_db": str(tmp_path / "access.db"),
        "product_voice_enabled": False,
    }))
    token = issue(adapter._access_registry)

    async def check():
        app = web.Application()
        app.router.add_post("/stt", adapter._handle_audio_transcriptions)
        app.router.add_post("/tts", adapter._handle_audio_speech)
        async with TestClient(TestServer(app)) as client:
            headers = {
                "Authorization": f"Bearer {token}",
                "X-Hermes-Session-Id": "session",
            }
            stt = await client.post("/stt", headers=headers, data=upload())
            tts = await client.post("/tts", headers=headers, json={"input": "test"})
            assert stt.status == 503
            assert tts.status == 503
    asyncio.run(check())
