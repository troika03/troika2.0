"""
hf_media_tool — генерация фото и видео через публичные HuggingFace Spaces
без API-ключей и без OAuth. Бесплатно, на чужих GPU.

Tools:
  • image_hf_flux       — FLUX.1-schnell text-to-image (быстрый, ~5-15 сек)
  • phone_create_video  — Lightricks LTX-Video text-to-video (~60-180 сек) → телефон
  • video_hf_url        — то же что выше, но возвращает локальный путь без отправки

Видео идёт через job_runner (async), фото — синхронно (быстро).
Все запросы — через gradio_client к публичным Spaces. Если Space упал —
LLM получит понятную ошибку.

Spaces:
  - black-forest-labs/FLUX.1-schnell (картинки)
  - Lightricks/ltx-video-distilled    (text-to-video)

Зависит от: `pip install gradio_client`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


_FLUX_SPACE = "black-forest-labs/FLUX.1-schnell"
_LTX_SPACE = "Lightricks/ltx-video-distilled"

# Fallback chain для фото — бесплатные Spaces часто в GPU-очереди или upload-quota.
# Пробуем по очереди пока какой-то не отдаст файл.
# Каждая запись: (space_id, api_name, build_kwargs_fn)
def _flux_kwargs(prompt, width, height, seed):
    return dict(prompt=prompt, seed=seed or 0, randomize_seed=seed is None,
                width=width, height=height, num_inference_steps=4)

def _sdxl_lightning_kwargs(prompt, width, height, seed):
    return dict(prompt=prompt, ckpt="4-Step")

def _sdxl_flash_kwargs(prompt, width, height, seed):
    # KingNish/SDXL-Flash /run signature: (prompt, negative, use_negative, seed, width, height, guidance, steps, randomize)
    return dict(prompt=prompt, negative_prompt="", use_negative_prompt=False,
                seed=seed or 0, width=width, height=height,
                guidance_scale=3.0, num_inference_steps=8, randomize_seed=seed is None)

_IMAGE_BACKENDS = [
    (_FLUX_SPACE, "/infer", _flux_kwargs, "FLUX.1-schnell"),
    ("ByteDance/SDXL-Lightning", "/generate_image", _sdxl_lightning_kwargs, "SDXL-Lightning"),
    ("KingNish/SDXL-Flash", "/run", _sdxl_flash_kwargs, "SDXL-Flash"),
]


def _bridge():
    from gateway.platforms.phone_bridge import bridge
    return bridge


def _check_phone_connected() -> bool:
    try:
        return _bridge().is_connected()
    except Exception:
        return False


def _check_gradio_installed() -> bool:
    try:
        import gradio_client  # noqa: F401
        return True
    except ImportError:
        return False


def _safe_filename(name: str, ext: str) -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip("._ ")
    if not base:
        base = "media"
    base = base[:60]
    if not base.lower().endswith("." + ext):
        base = f"{base}.{ext}"
    return base


# ---------------------------------------------------------------------------
# Sync helpers (gradio_client is sync; we run them in thread executor)
# ---------------------------------------------------------------------------

def _extract_image_path(result: Any) -> Optional[str]:
    """Развернуть произвольную форму ответа gradio-Space до пути к файлу.
    Поддерживает: str | (str, ...) | [{'image': str}, ...] | (..., ...) | {'path': str} | {'image': str}."""
    # Распаковка кортежа: путь обычно в [0]
    if isinstance(result, tuple) and result:
        result = result[0]
    # Галерея — list of dicts
    if isinstance(result, list) and result:
        result = result[0]
    if isinstance(result, dict):
        return result.get("image") or result.get("path") or result.get("url") or result.get("video")
    if isinstance(result, str):
        return result
    return None


def _gen_image_sync(prompt: str, width: int, height: int, seed: Optional[int]) -> Dict[str, Any]:
    """Try image backends in order. Returns {'path': str, 'model': str}.
    Raises if ALL fail. Each backend failure is logged but doesn't stop the chain."""
    from gradio_client import Client
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    errors = []
    for space, api_name, kw_fn, display in _IMAGE_BACKENDS:
        try:
            client_kwargs: Dict[str, Any] = {"verbose": False}
            if hf_token:
                client_kwargs["hf_token"] = hf_token
            c = Client(space, **client_kwargs)
            kwargs = kw_fn(prompt, width, height, seed)
            kwargs["api_name"] = api_name
            result = c.predict(**kwargs)
            path = _extract_image_path(result)
            if path and os.path.exists(path):
                return {"path": path, "model": display, "space": space}
            errors.append(f"{display}: returned no usable file ({str(result)[:120]})")
        except Exception as e:
            errors.append(f"{display}: {type(e).__name__}: {str(e)[:100]}")
            logger.warning("image backend %s failed: %s", space, e)
            continue
    raise RuntimeError("All image backends failed: " + " | ".join(errors))


def _gen_ltx_video_sync(prompt: str, negative: str, duration: int,
                        width: int, height: int, seed: Optional[int]) -> str:
    """Returns local filepath to generated MP4."""
    from gradio_client import Client
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    client_kwargs: Dict[str, Any] = {"verbose": False}
    if hf_token:
        client_kwargs["hf_token"] = hf_token
    c = Client(_LTX_SPACE, **client_kwargs)
    result = c.predict(
        prompt=prompt,
        negative_prompt=negative,
        image_n=None,
        video_n=None,
        height=height,
        width=width,
        task="text-to-video",
        duration_seconds=duration,
        frames_to_use=9,
        seed=seed if seed is not None else 42,
        randomize_seed=seed is None,
        guidance_scale=1.0,
        improve_texture=True,
        api_name="/text_to_video",
    )
    # result: ({'video': filepath, 'subtitles': ...}, used_seed)
    video_info = result[0] if isinstance(result, (list, tuple)) else result
    path = video_info.get("video") if isinstance(video_info, dict) else video_info
    if not path or not os.path.exists(path):
        raise RuntimeError(f"LTX returned no file: {result!r}")
    return path


# ---------------------------------------------------------------------------
# Image: FLUX schnell — синхронно (быстро, 5-15 сек)
# ---------------------------------------------------------------------------

async def _handle_image_hf_flux(args: Dict[str, Any], **_kw) -> str:
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return json.dumps({"ok": False, "error": "missing 'prompt'"}, ensure_ascii=False)
    if not _check_gradio_installed():
        return json.dumps({"ok": False, "error": "gradio_client not installed",
                           "hint": "pip install gradio_client"}, ensure_ascii=False)

    width = int(args.get("width") or 1024)
    height = int(args.get("height") or 1024)
    seed = args.get("seed")
    if seed is not None:
        seed = int(seed)
    deliver = args.get("deliver", "phone")  # phone / url / none

    loop = asyncio.get_running_loop()
    try:
        gen = await loop.run_in_executor(
            None, _gen_image_sync, prompt, width, height, seed,
        )
        local_path = gen["path"]
        used_model = gen["model"]
    except Exception as e:
        return json.dumps({"ok": False, "error": f"all_backends_failed: {str(e)[:300]}",
                           "say_to_user": "Не получилось сгенерировать картинку — все бесплатные сервера сейчас перегружены. Попробуй через минуту."},
                          ensure_ascii=False)

    size_bytes = os.path.getsize(local_path)
    result: Dict[str, Any] = {
        "ok": True,
        "model": used_model,
        "size": f"{width}x{height}",
        "size_bytes": size_bytes,
        "local_path": local_path,
    }

    if deliver == "phone" and _check_phone_connected():
        # HF Spaces возвращают webp/png/jpg — берём настоящее расширение из файла
        ext = (os.path.splitext(local_path)[1] or ".png").lstrip(".").lower()
        if ext not in ("png", "jpg", "jpeg", "webp"):
            ext = "png"
        filename = _safe_filename(args.get("filename") or prompt[:40], ext)
        try:
            with open(local_path, "rb") as f:
                data = f.read()
            encoded = base64.b64encode(data).decode("ascii")
            timeout = max(60.0, len(encoded) / 30_000)
            bridge_result = await _bridge().send_command(
                "file_write",
                {"path": f"Pictures/Hermes/{filename}", "content": encoded,
                 "encoding": "base64", "append": False},
                timeout=timeout,
            )
            result["delivered"] = bool(bridge_result.get("ok"))
            result["filename"] = filename
            result["say_to_user"] = (f"Картинка готова, в Pictures/Hermes/{filename}"
                                     if result["delivered"] else
                                     "Картинка готова, но не получилось отправить на телефон")
        except Exception as e:
            result["delivered"] = False
            result["delivery_error"] = str(e)

    if "say_to_user" not in result:
        result["say_to_user"] = f"Картинка готова ({size_bytes // 1024} КБ)."

    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Video: LTX — через job_runner (медленно, 60-180 сек)
# ---------------------------------------------------------------------------

async def _do_video_work(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Heavy worker, запускается через job_runner."""
    prompt = payload["prompt"]
    negative = payload.get("negative") or "worst quality, blurry, jittery"
    duration = int(payload.get("duration") or 3)
    width = int(payload.get("width") or 704)
    height = int(payload.get("height") or 512)
    seed = payload.get("seed")
    filename = payload.get("filename")
    deliver = payload.get("deliver", "phone")

    loop = asyncio.get_running_loop()
    try:
        local_path = await loop.run_in_executor(
            None, _gen_ltx_video_sync, prompt, negative, duration, width, height, seed,
        )
    except Exception as e:
        return {"ok": False, "error": f"ltx_failed: {e}",
                "say_to_user": "Не получилось сгенерировать видео — Space LTX недоступен или упал."}

    size_bytes = os.path.getsize(local_path)
    result: Dict[str, Any] = {
        "ok": True, "model": "LTX-Video-distilled",
        "size": f"{width}x{height}", "duration_s": duration,
        "size_bytes": size_bytes, "local_path": local_path,
    }

    if deliver == "phone" and _check_phone_connected():
        fname = _safe_filename(filename or prompt[:40], "mp4")
        try:
            with open(local_path, "rb") as f:
                data = f.read()
            encoded = base64.b64encode(data).decode("ascii")
            timeout = max(120.0, len(encoded) / 20_000)
            bridge_result = await _bridge().send_command(
                "file_write",
                {"path": f"Movies/Hermes/{fname}", "content": encoded,
                 "encoding": "base64", "append": False},
                timeout=timeout,
            )
            result["delivered"] = bool(bridge_result.get("ok"))
            result["filename"] = fname
        except Exception as e:
            result["delivered"] = False
            result["delivery_error"] = str(e)

    delivered = result.get("delivered")
    if delivered:
        result["say_to_user"] = f"Видео готово, в Movies/Hermes/{result['filename']}."
    else:
        result["say_to_user"] = f"Видео готово ({size_bytes // 1024} КБ), но не получилось отправить на телефон."

    return result


async def _handle_phone_create_video(args: Dict[str, Any], **_kw) -> str:
    """Submit a video job. Returns task_id immediately, user gets notify_voice when done."""
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        return json.dumps({"ok": False, "error": "missing 'prompt'"}, ensure_ascii=False)
    if not _check_gradio_installed():
        return json.dumps({"ok": False, "error": "gradio_client not installed"}, ensure_ascii=False)

    session_id = _kw.get("session_id")
    payload = {
        "prompt": prompt,
        "negative": args.get("negative_prompt") or args.get("negative"),
        "duration": int(args.get("duration") or 3),
        "width": int(args.get("width") or 704),
        "height": int(args.get("height") or 512),
        "seed": args.get("seed"),
        "filename": args.get("filename"),
        "deliver": args.get("deliver", "phone"),
    }
    short_label = f"видео: {prompt[:40]}"

    try:
        from tools import job_runner
        task_id = job_runner.submit("hf_video_ltx", payload,
                                    session_id=session_id, short_label=short_label)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"submit_failed: {e}"}, ensure_ascii=False)

    return json.dumps({
        "ok": True, "task_id": task_id, "async": True,
        "say_to_user": "Принял, делаю видео в фоне. Скажу когда готово, минуты 2-3.",
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

IMAGE_FLUX_SCHEMA = {
    "name": "image_hf_flux",
    "description": "Generate a high-quality image with FLUX.1-schnell via HuggingFace Space (no API key, free). ~5-15 sec. Best quality of free options. Use this for serious image gen; use phone_create_image (Pollinations) when speed > quality.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "What to draw."},
            "width": {"type": "integer", "description": "Default 1024."},
            "height": {"type": "integer", "description": "Default 1024."},
            "seed": {"type": "integer"},
            "deliver": {"type": "string", "description": "phone (save to Pictures/Hermes) or none (return path only). Default phone."},
            "filename": {"type": "string"},
        },
        "required": ["prompt"],
    },
}

PHONE_VIDEO_SCHEMA = {
    "name": "phone_create_video",
    "description": "Generate a short video (2-5 sec) from a text prompt via LTX-Video on HuggingFace (no API key, free, runs on community GPU). Slow (~60-180 sec), runs in background — returns task_id immediately and notifies when done. Result lands on phone in Movies/Hermes/.",
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Detailed visual description. Cinematic phrasing works best."},
            "negative_prompt": {"type": "string"},
            "duration": {"type": "integer", "description": "Seconds, 2-5. Default 3."},
            "width": {"type": "integer", "description": "Default 704, multiple of 32."},
            "height": {"type": "integer", "description": "Default 512, multiple of 32."},
            "seed": {"type": "integer"},
            "filename": {"type": "string"},
            "deliver": {"type": "string", "description": "phone (default) or none."},
        },
        "required": ["prompt"],
    },
}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

from tools.registry import registry  # noqa: E402

registry.register(
    name="image_hf_flux", toolset="image_gen",
    schema=IMAGE_FLUX_SCHEMA,
    handler=_handle_image_hf_flux,
    is_async=True, emoji="🖼",
)

registry.register(
    name="phone_create_video", toolset="image_gen",
    schema=PHONE_VIDEO_SCHEMA,
    handler=_handle_phone_create_video,
    check_fn=_check_gradio_installed,
    is_async=True, emoji="🎬",
)


# Register video worker with job_runner
try:
    from tools import job_runner as _job_runner
    _job_runner.register_handler("hf_video_ltx", _do_video_work)
except Exception as _e:
    logger.warning("hf_video_ltx job handler registration failed: %s", _e)
