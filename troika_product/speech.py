"""Bounded free OpenRouter speech, with early audio and no paid fallback."""

import asyncio
from decimal import Decimal, InvalidOperation
import os
import time

import aiohttp
from aiohttp import web

MODEL = "fish-audio/s2.1-pro-free:free"
SERVICE = "openrouter:" + MODEL
BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_RUSSIAN_VOICE = "7aff72b7f4224a9ebeeb58bc79f1050c"
MAX_AUDIO_BYTES = 10 * 1024 * 1024
CATALOG_TTL = 300


class SpeechUnavailable(Exception):
    """Safe signal to use the existing free voice before delivery starts."""


def verified_free_model(rows):
    """Reject disappearance, changed price, or changed output modality."""
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        return False
    matches = [row for row in rows if row.get("id") == MODEL]
    if len(matches) != 1:
        return False
    row = matches[0]
    prices = row.get("pricing", {})
    architecture = row.get("architecture", {})
    if not isinstance(prices, dict) or not isinstance(architecture, dict):
        return False
    try:
        return (
            "speech" in (architecture.get("output_modalities") or [])
            and {"prompt", "completion"}.issubset(prices)
            and all(Decimal(str(value)).is_finite() and Decimal(str(value)) == 0
                    for value in prices.values())
        )
    except (TypeError, ValueError, InvalidOperation):
        return False


class OpenRouterSpeech:
    def __init__(self, settings, *, base_url=BASE_URL):
        self.settings = settings
        self.base_url = base_url
        self._free_until = 0
        self._retry_after = 0
        self._catalog_lock = asyncio.Lock()
        self._capacity = asyncio.Semaphore(4)

    async def _verify(self, client):
        if time.monotonic() < self._free_until:
            return
        async with self._catalog_lock:
            if time.monotonic() < self._free_until:
                return
            async with asyncio.timeout(3):
                async with client.get(self.base_url + "/models?output_modalities=speech") as response:
                    if response.status != 200:
                        raise SpeechUnavailable()
                    payload = await response.json()
                    if not verified_free_model(payload.get("data", [])):
                        raise SpeechUnavailable()
            self._free_until = time.monotonic() + CATALOG_TTL

    async def render(self, request, text, tone, *, meter=None, stream=False):
        """Return MP3; opt-in clients receive the first bytes immediately.

        Older clients retain the buffered response contract. Once streaming
        starts, failures close that stream and never append a second voice.
        """
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        if not key or time.monotonic() < self._retry_after or self._capacity.locked():
            raise SpeechUnavailable()
        response = None
        lease = None
        try:
            async with self._capacity:
                timeout = aiohttp.ClientTimeout(total=30, connect=3, sock_read=3)
                async with aiohttp.ClientSession(timeout=timeout) as client:
                    await self._verify(client)
                    # A free-only route must never inherit a paid service price.
                    if meter is not None:
                        from troika_product.service_metering import ServicePrice
                        price = ServicePrice.from_config(meter.prices.get(SERVICE))
                        if price.rub_per_unit != 0:
                            raise SpeechUnavailable()
                        lease = meter.begin(SERVICE, len(text), kind="tts")
                    directions = (
                        "Warm, friendly conversational Russian, with a light smile and clear diction. "
                        "Speak fluently at a normal lively pace. Keep vowels short and pauses brief."
                    )
                    emotion = {
                        "joy": "Cheerful and friendly.", "радость": "Cheerful and friendly.",
                        "sad": "Gentle and supportive.", "грусть": "Gentle and supportive.",
                        "calm": "Calm and reassuring.", "excited": "Lively and interested.",
                    }.get(str(tone).lower(), "Friendly and attentive.")
                    payload = {
                        "model": MODEL, "input": text, "response_format": "mp3",
                        "instructions": directions + " " + emotion,
                    }
                    voice = self.settings.get("voice") or DEFAULT_RUSSIAN_VOICE
                    if isinstance(voice, str) and voice.strip():
                        payload["voice"] = voice.strip()
                    # Fixed model and URL; never accept a client model, key, URL,
                    # cloning sample, or provider fallback list.
                    async with asyncio.timeout(3):
                        upstream = await client.post(
                            self.base_url + "/audio/speech", json=payload,
                            headers={"Authorization": "Bearer " + key},
                            allow_redirects=False,
                        )
                        try:
                            if upstream.status != 200 or upstream.content_type != "audio/mpeg":
                                raise SpeechUnavailable()
                            first = await upstream.content.readany()
                            if not first:
                                raise SpeechUnavailable()
                        except BaseException:
                            upstream.close()
                            raise
                    async with upstream:
                        size = len(first)
                        if size > MAX_AUDIO_BYTES:
                            raise SpeechUnavailable()
                        headers = {
                            "Cache-Control": "private, no-store", "X-Accel-Buffering": "no",
                            "X-Troika-Speech-Provider": "openrouter",
                        }
                        if stream:
                            response = web.StreamResponse(headers=headers)
                            response.content_type = "audio/mpeg"
                            await response.prepare(request)
                            await response.write(first)
                            audio = None
                        else:
                            audio = bytearray(first)
                        async for chunk in upstream.content.iter_chunked(8192):
                            size += len(chunk)
                            if size > MAX_AUDIO_BYTES:
                                raise SpeechUnavailable()
                            if response is not None:
                                await response.write(chunk)
                            else:
                                audio.extend(chunk)
                        if response is not None:
                            await response.write_eof()
                            return response
                        return web.Response(body=bytes(audio), content_type="audio/mpeg", headers=headers)
        except asyncio.CancelledError:
            if response is not None and request.transport is not None:
                request.transport.close()
            raise
        except (SpeechUnavailable, aiohttp.ClientError, TimeoutError, ValueError, TypeError, KeyError, InvalidOperation):
            self._retry_after = time.monotonic() + 15
            if response is not None:
                if request.transport is not None:
                    request.transport.close()
                raise ConnectionResetError("Speech stream interrupted") from None
            raise SpeechUnavailable() from None
        finally:
            if lease is not None:
                # Both catalogue and operator price were verified zero before
                # dispatch, so even a timeout has a known zero monetary cost.
                lease.succeeded(len(text))
