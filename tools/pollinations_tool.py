"""
Pollinations.AI image generation — бесплатная генерация изображений без API ключа.

Эндпоинт: https://image.pollinations.ai/prompt/<URL_ENCODED_PROMPT>?model=flux&seed=...

Возвращает PNG/JPG напрямую. Используется FLUX (Schnell) по умолчанию,
доступны также: turbo, flux-realism, flux-anime, flux-3d, any-dark.

Подключается к двум сценариям:
1. ``image_pollinations_url`` — просто возвращает прямой URL картинки
2. ``phone_create_image`` — генерирует и кладёт на телефон через bridge
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import tempfile
import urllib.parse
from typing import Any, Dict

import aiohttp

logger = logging.getLogger(__name__)


def _bridge():
    from gateway.platforms.phone_bridge import bridge
    return bridge


def _check_phone_connected():
    try:
        return _bridge().is_connected()
    except Exception:
        return False


def _safe_filename(name: str, ext: str = "png") -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip("._ ")
    if not base:
        base = "image"
    if not base.lower().endswith("." + ext):
        base = f"{base}.{ext}"
    return base


def _build_url(prompt: str, model: str, width: int, height: int, seed: int | None, nologo: bool, enhance: bool) -> str:
    encoded = urllib.parse.quote(prompt[:2000])
    params = {
        "model": model,
        "width": str(width),
        "height": str(height),
        "nologo": "true" if nologo else "false",
        "enhance": "true" if enhance else "false",
    }
    if seed is not None:
        params["seed"] = str(seed)
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://image.pollinations.ai/prompt/{encoded}?{query}"


async def _download(url: str, timeout: float = 120.0) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
            if r.status != 200:
                body = (await r.text())[:200]
                raise RuntimeError(f"pollinations {r.status}: {body}")
            return await r.read()


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def _handle_generate_image_url(args: Dict[str, Any], **kw) -> str:
    """Просто построить URL — пользователь / LLM сможет открыть в браузере."""
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return json.dumps({"ok": False, "error": "missing 'prompt'"}, ensure_ascii=False)
    model = args.get("model") or "flux"
    width = int(args.get("width") or 1024)
    height = int(args.get("height") or 1024)
    seed = args.get("seed")
    if seed is not None:
        seed = int(seed)
    url = _build_url(prompt, model, width, height, seed,
                     nologo=bool(args.get("nologo", True)),
                     enhance=bool(args.get("enhance", True)))
    return json.dumps({"ok": True, "url": url, "model": model,
                       "size": f"{width}x{height}"}, ensure_ascii=False)


async def _handle_generate_image_on_phone(args: Dict[str, Any], **kw) -> str:
    """Сгенерировать изображение и сохранить его на телефоне в Pictures/Hermes/."""
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return json.dumps({"ok": False, "error": "missing 'prompt'"}, ensure_ascii=False)
    model = args.get("model") or "flux"
    width = int(args.get("width") or 1024)
    height = int(args.get("height") or 1024)
    seed = args.get("seed")
    if seed is not None:
        seed = int(seed)
    filename = _safe_filename(args.get("filename") or prompt[:40], "jpg")

    url = _build_url(prompt, model, width, height, seed,
                     nologo=bool(args.get("nologo", True)),
                     enhance=bool(args.get("enhance", True)))

    try:
        data = await _download(url, timeout=180.0)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"download_failed: {e}"}, ensure_ascii=False)

    # Кладём в Pictures/Hermes (для галереи)
    encoded = base64.b64encode(data).decode("ascii")
    timeout = max(60.0, len(encoded) / 30_000)
    bridge_result = await _bridge().send_command(
        "file_write",
        {"path": f"Pictures/Hermes/{filename}", "content": encoded,
         "encoding": "base64", "append": False},
        timeout=timeout,
    )
    return json.dumps({"ok": bridge_result.get("ok", False),
                       "filename": filename,
                       "model": model,
                       "size_bytes": len(data),
                       "phone_result": bridge_result}, ensure_ascii=False)


async def _handle_generate_image_local(args: Dict[str, Any], **kw) -> str:
    """Сгенерировать и вернуть путь к локальному файлу на PC (для встраивания в PPTX/PDF)."""
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return json.dumps({"ok": False, "error": "missing 'prompt'"}, ensure_ascii=False)
    model = args.get("model") or "flux"
    width = int(args.get("width") or 1024)
    height = int(args.get("height") or 1024)
    seed = args.get("seed")
    if seed is not None:
        seed = int(seed)
    url = _build_url(prompt, model, width, height, seed,
                     nologo=bool(args.get("nologo", True)),
                     enhance=bool(args.get("enhance", True)))
    try:
        data = await _download(url, timeout=180.0)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"download_failed: {e}"}, ensure_ascii=False)

    fd, path = tempfile.mkstemp(suffix=".jpg", prefix="pollinations_")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(data)
    return json.dumps({"ok": True, "path": path, "url": url,
                       "size_bytes": len(data)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

POLLI_URL_SCHEMA = {
    "name": "image_pollinations_url",
    "description": "Generate a URL for a Pollinations.AI image. Free, no API key. Models: flux (default, FLUX.1-schnell), turbo, flux-realism, flux-anime, flux-3d, any-dark. Returns the direct URL — user can open it or you can fetch it.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "model": {"type": "string", "description": "flux/turbo/flux-realism/flux-anime/flux-3d/any-dark"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "seed": {"type": "integer"},
            "nologo": {"type": "boolean", "description": "Strip Pollinations watermark. Default true."},
            "enhance": {"type": "boolean", "description": "Auto-enhance prompt. Default true."},
        },
        "required": ["prompt"],
    },
}

PHONE_IMAGE_SCHEMA = {
    "name": "phone_create_image",
    "description": "Generate an image with Pollinations.AI and save it to the phone's Pictures/Hermes folder. Free, no API key needed.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "model": {"type": "string"},
            "width": {"type": "integer"},
            "height": {"type": "integer"},
            "seed": {"type": "integer"},
            "filename": {"type": "string"},
        },
        "required": ["prompt"],
    },
}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

from tools.registry import registry  # noqa: E402

# image_pollinations_url не требует подключения телефона
registry.register(name="image_pollinations_url", toolset="image_gen",
                  schema=POLLI_URL_SCHEMA,
                  handler=_handle_generate_image_url,
                  is_async=True, emoji="🎨")

# phone_create_image требует bridge
registry.register(name="phone_create_image", toolset="image_gen",
                  schema=PHONE_IMAGE_SCHEMA,
                  handler=_handle_generate_image_on_phone,
                  check_fn=_check_phone_connected,
                  is_async=True, emoji="🎨")
