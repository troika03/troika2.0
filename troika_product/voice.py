"""Bounded, revocable voice requests without audio or transcript persistence."""

import asyncio
from contextlib import suppress
import os
import time

from aiohttp import web

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_MULTIPART_BYTES = MAX_AUDIO_BYTES + 8192
VOICE_TIMEOUT_SECONDS = 90
ACCESS_POLL_SECONDS = 0.25


def voice_enabled() -> bool:
    """Emergency switch, checked throughout each product voice request."""
    return os.getenv("TROIKA_PRODUCT_VOICE_ENABLED", "true").lower() in {
        "1", "true", "yes", "on",
    }


async def guarded_voice(operation, *, registry, token, request=None, enabled=None):
    """Cancel delivery on revoke, disconnect, kill switch, or deadline.

    Native inference already executing in a thread may finish there, but its
    result is discarded. Providers must retain their capacity slot until the
    native worker actually finishes.
    """
    task = asyncio.create_task(operation())
    deadline = time.monotonic() + VOICE_TIMEOUT_SECONDS
    try:
        while True:
            is_enabled = enabled() if enabled is not None else voice_enabled()
            if not is_enabled:
                raise web.HTTPServiceUnavailable(text="Voice is disabled")
            if registry.authenticate(token) is None:
                raise web.HTTPUnauthorized(text="Device access revoked")
            if request is not None:
                transport = request.transport
                if transport is None or transport.is_closing():
                    raise asyncio.CancelledError
            if time.monotonic() >= deadline:
                raise web.HTTPGatewayTimeout(text="Voice request timed out")
            if task.done():
                return task.result()
            await asyncio.wait({task}, timeout=ACCESS_POLL_SECONDS)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task


async def read_audio_upload(request):
    """Read multipart incrementally; aiohttp's limit alone does not cap parts."""
    if request.content_length and request.content_length > MAX_MULTIPART_BYTES:
        raise web.HTTPRequestEntityTooLarge(
            max_size=MAX_MULTIPART_BYTES, actual_size=request.content_length,
        )
    audio = None
    language = "ru"
    total = 0
    try:
        reader = await request.multipart()
        async for field in reader:
            if field.name not in {"file", "language"}:
                raise web.HTTPBadRequest(text="Unexpected audio field")
            if field.name == "file" and audio is not None:
                raise web.HTTPBadRequest(text="Only one audio file is allowed")
            limit = MAX_AUDIO_BYTES if field.name == "file" else 32
            content = bytearray()
            while chunk := await field.read_chunk():
                total += len(chunk)
                if len(content) + len(chunk) > limit or total > MAX_MULTIPART_BYTES:
                    raise web.HTTPRequestEntityTooLarge(max_size=limit, actual_size=total)
                content.extend(chunk)
            if field.name == "file":
                audio = bytes(content)
            else:
                language = content.decode("ascii").strip() or "ru"
                if not language.isalpha():
                    raise web.HTTPBadRequest(text="Invalid language")
    except (ValueError, UnicodeError, AssertionError) as exc:
        raise web.HTTPBadRequest(text="Invalid audio upload") from exc
    if not audio:
        raise web.HTTPBadRequest(text="No audio file in request")
    return audio, language
