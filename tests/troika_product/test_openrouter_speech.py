"""Check free-only routing, early delivery, bounds, and cancellation."""

import asyncio
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from troika_product.speech import (
    MODEL, SERVICE, OpenRouterSpeech, SpeechUnavailable, verified_free_model,
)


def model(price="0"):
    return {"id": MODEL, "pricing": {"prompt": price, "completion": "0"},
            "architecture": {"output_modalities": ["speech"]}}


@pytest.mark.parametrize("price", ["0.000001", "NaN", "-1", "Infinity", None])
def test_changed_or_unknown_price_is_not_free(price):
    assert not verified_free_model([model(price)])


def test_free_requires_exact_model_prices_and_speech():
    assert verified_free_model([model()])
    assert not verified_free_model([])
    assert not verified_free_model([model(), model()])
    row = model()
    row["id"] = "fish-audio/s2.1-pro"
    assert not verified_free_model([row])
    assert not verified_free_model(None)
    assert not verified_free_model([None])
    assert not verified_free_model([{**model(), "pricing": None}])
    assert not verified_free_model([{**model(), "architecture": None}])
    row = model()
    row["pricing"].pop("completion")
    assert not verified_free_model([row])
    row = model()
    row["architecture"]["output_modalities"] = ["text"]
    assert not verified_free_model([row])


def test_stream_delivers_before_synthesis_finishes_and_pins_route(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-private-key")

    async def check():
        release = asyncio.Event()
        calls = []

        async def catalog(request):
            return web.json_response({"data": [model()]})

        async def synthesize(request):
            calls.append(await request.json())
            assert request.headers["Authorization"] == "Bearer test-private-key"
            response = web.StreamResponse(headers={"Content-Type": "audio/mpeg"})
            await response.prepare(request)
            await response.write(b"first-audio")
            await release.wait()
            await response.write(b"-last-audio")
            return response

        upstream = web.Application()
        upstream.router.add_get("/models", catalog)
        upstream.router.add_post("/audio/speech", synthesize)
        async with TestServer(upstream) as server:
            speech = OpenRouterSpeech({}, base_url=str(server.make_url("")).rstrip("/"))
            app = web.Application()

            async def handler(request):
                return await speech.render(request, "Проверка", "joy", stream=True)

            app.router.add_post("/speech", handler)
            async with TestClient(TestServer(app)) as client:
                response = await client.post("/speech")
                assert response.headers["Cache-Control"] == "private, no-store"
                assert response.headers["X-Troika-Speech-Provider"] == "openrouter"
                assert await asyncio.wait_for(response.content.readexactly(11), 1) == b"first-audio"
                assert not release.is_set()
                release.set()
                assert await response.read() == b"-last-audio"
            assert len(calls) == 1
            assert calls[0]["model"] == MODEL
            assert "speed" not in calls[0]
            assert "models" not in calls[0]
            assert "Cheerful" in calls[0]["instructions"]

    asyncio.run(check())


def test_revoke_closes_active_stream_and_stops_provider(monkeypatch, tmp_path):
    import aiohttp
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter
    from troika_product import voice

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-private-key")
    monkeypatch.setattr(voice, "ACCESS_POLL_SECONDS", 0.01)

    async def check():
        adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={
            "product_auth_enabled": True, "product_auth_db": str(tmp_path / "access.db"),
            "product_speech": {"backend": "openrouter"},
        }))
        registry = adapter._access_registry
        user = registry.create_user("voice-stream@example.com")
        token = registry.issue_device_token(registry.create_device(user, name="Test", platform="android"))

        async def synthesize(request):
            response = web.StreamResponse(headers={"Content-Type": "audio/mpeg"})
            await response.prepare(request)
            await response.write(b"first")
            await asyncio.sleep(0.08)
            try:
                await response.write(b"private-late-audio")
            except ConnectionResetError:
                pass
            return response

        upstream = web.Application()
        upstream.router.add_get("/models", lambda r: web.json_response({"data": [model()]}))
        upstream.router.add_post("/audio/speech", synthesize)
        async with TestServer(upstream) as server:
            adapter._product_speech = OpenRouterSpeech({}, base_url=str(server.make_url("")).rstrip("/"))
            app = web.Application()
            app.router.add_post("/speech", adapter._handle_audio_speech)
            async with TestClient(TestServer(app)) as client:
                response = await client.post("/speech", headers={"Authorization": "Bearer " + token},
                                             json={"input": "Private speech", "stream": True})
                assert await response.content.readexactly(5) == b"first"
                registry.revoke_token(token)
                with pytest.raises(aiohttp.ClientPayloadError):
                    await response.read()

    asyncio.run(check())


@pytest.mark.parametrize("failure", ["priced", "missing", "rate_limit", "empty", "json"])
def test_failure_is_bounded_and_never_retries_paid_model(monkeypatch, failure):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-private-key")

    async def check():
        calls = []

        async def catalog(request):
            rows = [] if failure == "missing" else [model("1" if failure == "priced" else "0")]
            return web.json_response({"data": rows})

        async def synthesize(request):
            calls.append(await request.json())
            if failure == "rate_limit":
                return web.json_response({"error": "private provider error"}, status=429)
            return web.Response(body=b"" if failure == "empty" else b"{}",
                                content_type="application/json" if failure == "json" else "audio/mpeg")

        app = web.Application()
        app.router.add_get("/models", catalog)
        app.router.add_post("/audio/speech", synthesize)
        async with TestServer(app) as server:
            speech = OpenRouterSpeech({}, base_url=str(server.make_url("")).rstrip("/"))
            for _ in range(2):
                with pytest.raises(SpeechUnavailable):
                    await speech.render(None, "Private text", None)
            assert len(calls) == (0 if failure in {"priced", "missing"} else 1)

    asyncio.run(check())


def test_verified_free_usage_settles_zero_even_when_provider_fails(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-private-key")

    async def check():
        settled = []
        meter = SimpleNamespace(
            prices={SERVICE: {"version": "free-v1", "unit": "characters", "rub_per_unit": "0", "maximum_units": 5000}},
            begin=lambda *a, **kw: SimpleNamespace(succeeded=settled.append),
        )
        app = web.Application()
        app.router.add_get("/models", lambda r: web.json_response({"data": [model()]}))
        app.router.add_post("/audio/speech", lambda r: web.Response(status=429))
        async with TestServer(app) as server:
            speech = OpenRouterSpeech({}, base_url=str(server.make_url("")).rstrip("/"))
            with pytest.raises(SpeechUnavailable):
                await speech.render(None, "Проверка", None, meter=meter)
            assert settled == [len("Проверка")]

    asyncio.run(check())
