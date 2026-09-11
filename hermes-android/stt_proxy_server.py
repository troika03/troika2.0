"""
Hermes STT Proxy Server
=========================
Принимает аудио от Android APK и распознаёт его в текст.

Бэкенды (env STT_BACKEND):
  local — faster-whisper локально, GPU если есть, иначе CPU
  groq  — облачный Groq Whisper (быстрый, но требует токен и сеть)
  auto  — пробует local, fallback на groq если local не поднялся (default)

Порт: 8643 (рядом с Hermes на 8642)
"""

import os
import sys
import time
import asyncio
import hmac
import io
from pathlib import Path
from dotenv import load_dotenv

# Direct script execution must resolve product modules from this checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hermes_constants import get_hermes_home
from troika_product.voice import guarded_voice, read_audio_upload

# Подгружаем .env из возможных мест. В Docker переменные уже приходят
# через env_file/environment, а домашняя папка может быть недоступна
# процессу (UID hermes vs /root) — поэтому .exists()/load обёрнуты так,
# чтобы PermissionError не ронял сервис (s6 иначе крутит рестарт по кругу).
def _try_load_env(path: Path) -> None:
    try:
        if path.is_file():
            load_dotenv(path)
    except (PermissionError, OSError):
        pass

_try_load_env(get_hermes_home() / ".env")

from aiohttp import web, ClientSession, FormData
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("stt-proxy")

def _collect_groq_keys() -> list[str]:
    """Собирает все Groq-ключи: GROQ_API_KEY, GROQ_API_KEY2, GROQ_API_KEY3...
    Несколько бесплатных аккаунтов = суммарный дневной лимит. Прокси при 429
    на одном ключе переключается на следующий."""
    keys: list[str] = []
    primary = os.getenv("GROQ_API_KEY", "").strip()
    if primary:
        keys.append(primary)
    for i in range(2, 6):  # GROQ_API_KEY2..GROQ_API_KEY5
        k = os.getenv(f"GROQ_API_KEY{i}", "").strip()
        if k and k not in keys:
            keys.append(k)
    return keys


GROQ_KEYS = _collect_groq_keys()
GROQ_API_KEY = GROQ_KEYS[0] if GROQ_KEYS else ""  # обратная совместимость
API_SERVER_KEY = os.getenv("API_SERVER_KEY", "").strip()
PORT = int(os.getenv("STT_PROXY_PORT", "8643"))
HOST = os.getenv("STT_PROXY_HOST", "127.0.0.1")
PRODUCT_AUTH_ENABLED = os.getenv("TROIKA_PRODUCT_AUTH_ENABLED", "").strip().lower() in {
    "1", "true", "yes", "on",
}
PRODUCT_AUTH_ERROR = ""
ACCESS_REGISTRY = None
if PRODUCT_AUTH_ENABLED:
    try:
        from troika_product.access import AccessRegistry

        raw_database = os.getenv("TROIKA_PRODUCT_AUTH_DB", "").strip()
        ACCESS_REGISTRY = AccessRegistry(Path(raw_database) if raw_database else None)
    except Exception as exc:
        PRODUCT_AUTH_ERROR = str(exc)

_PLACEHOLDER_KEYS = {
    "hermes-2024", "your_api_key", "your_api_key_here", "changeme",
    "placeholder", "example", "dummy", "none", "null",
}


def _has_usable_api_key(value: str) -> bool:
    """Reject an empty or published API key before handling audio uploads."""
    return len(value) >= 8 and value.lower() not in _PLACEHOLDER_KEYS


API_KEY_CONFIGURED = _has_usable_api_key(API_SERVER_KEY)

# Backend selection
STT_BACKEND = (os.getenv("STT_BACKEND") or "auto").strip().lower()
LOCAL_MODEL_SIZE = (os.getenv("WHISPER_MODEL_SIZE") or "large-v3").strip()
LOCAL_DEVICE = (os.getenv("WHISPER_DEVICE") or "auto").strip().lower()
LOCAL_COMPUTE = (os.getenv("WHISPER_COMPUTE_TYPE") or "").strip().lower()

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


# ── Local faster-whisper (lazy init) ──────────────────────────────────────

_local_model = None
_local_init_task = None
_local_init_error: str = ""
_local_lock = asyncio.Lock()
_inference_lock = asyncio.Lock()


def _init_local_model_sync():
    """Загружает faster-whisper. Делается синхронно при первом запросе.
    Возвращает (model_instance, device_used, compute_used) или бросает."""
    global _local_init_error
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        _local_init_error = (
            f"faster-whisper не установлен: {e}. "
            "Поставь: pip install faster-whisper"
        )
        raise RuntimeError(_local_init_error)

    # Решаем device
    device = LOCAL_DEVICE
    if device == "auto":
        try:
            import torch  # type: ignore
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

    compute = LOCAL_COMPUTE
    if not compute:
        compute = "float16" if device == "cuda" else "int8"

    log.info(
        "Loading faster-whisper model=%s device=%s compute=%s …",
        LOCAL_MODEL_SIZE, device, compute,
    )
    t0 = time.monotonic()
    model = WhisperModel(LOCAL_MODEL_SIZE, device=device, compute_type=compute)
    log.info("faster-whisper ready in %.1fs", time.monotonic() - t0)
    return model, device, compute


async def _ensure_local_model():
    global _local_model, _local_init_task
    if _local_model is not None:
        return _local_model
    async with _local_lock:
        if _local_model is not None:
            return _local_model
        if _local_init_task is None:
            _local_init_task = asyncio.get_running_loop().run_in_executor(None, _init_local_model_sync)
        try:
            _local_model = await asyncio.shield(_local_init_task)
        except Exception:
            _local_init_task = None
            raise
        return _local_model


async def _transcribe_local(audio_bytes: bytes, language: str) -> tuple[str, dict]:
    """Decode from RAM and keep one native inference slot until it finishes."""
    model, device, compute = await _ensure_local_model()
    if _inference_lock.locked():
        raise web.HTTPServiceUnavailable(text="Speech worker is busy")
    await _inference_lock.acquire()

    def _run():
        with io.BytesIO(audio_bytes) as source:
            segments, info = model.transcribe(
                source,
                language=language or None,
                beam_size=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                temperature=0.0,
                condition_on_previous_text=False,
            )
            text_parts = [seg.text for seg in segments]
            return "".join(text_parts).strip(), info

    future = asyncio.get_running_loop().run_in_executor(None, _run)
    future.add_done_callback(lambda _: _inference_lock.release())
    # Cancelling the HTTP request cannot stop CTranslate2's native worker.
    # Shield preserves the capacity slot until that worker really finishes.
    text, info = await asyncio.shield(future)
    return text, {
        "backend": "local",
        "device": device,
        "compute": compute,
        "model": LOCAL_MODEL_SIZE,
        "language": getattr(info, "language", language),
        "duration": round(getattr(info, "duration", 0.0) or 0.0, 2),
    }


class _GroqRateLimited(RuntimeError):
    """429 от Groq — стоит попробовать другой ключ."""


async def _groq_post(audio_bytes: bytes, filename: str, language: str, model: str, api_key: str) -> str:
    form = FormData()
    form.add_field("file", audio_bytes, filename=filename, content_type="application/octet-stream")
    form.add_field("model", model)
    form.add_field("language", language)
    form.add_field("response_format", "json")
    form.add_field("temperature", "0")
    form.add_field("prompt", "")
    async with ClientSession() as session:
        async with session.post(
            GROQ_URL, data=form,
            headers={"Authorization": f"Bearer {api_key}"},
            # 30с заставляли ждать полминуты при лаге сети → «не реагирует».
            # 8с: не дождались — отдаём провал быстро, а не висим. (env override)
            timeout=int(os.getenv("GROQ_STT_TIMEOUT", "8")),
        ) as resp:
            if resp.status == 429:
                raise _GroqRateLimited("Groq 429")
            if resp.status != 200:
                raise RuntimeError(f"Groq {resp.status}")
            data = await resp.json()
            return (data.get("text", "") or "").strip()


async def _transcribe_groq(audio_bytes: bytes, filename: str, language: str) -> tuple[str, dict]:
    if not GROQ_KEYS:
        raise RuntimeError("GROQ_API_KEY не задан")
    # turbo ~2-4x быстрее large-v3 на коротких командах — режет паузу перед ответом.
    # Если turbo недоступен на ключе (403/404) — один раз падаем на проверенный large-v3.
    primary = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
    last_429: Exception | None = None
    # Перебираем ключи: первый словил 429 (дневной лимит) → пробуем следующий.
    for idx, key in enumerate(GROQ_KEYS):
        try:
            try:
                text = await _groq_post(audio_bytes, filename, language, primary, key)
                meta = {"backend": "groq", "model": primary}
            except RuntimeError as e:
                if isinstance(e, _GroqRateLimited):
                    raise
                msg = str(e)
                if primary != "whisper-large-v3" and (" 403" in msg or " 404" in msg or "model" in msg.lower()):
                    text = await _groq_post(audio_bytes, filename, language, "whisper-large-v3", key)
                    meta = {"backend": "groq", "model": "whisper-large-v3", "fellback": True}
                else:
                    raise
            if idx > 0:
                meta["key_index"] = idx  # пометка что сработал запасной ключ
            return text, meta
        except _GroqRateLimited as e:
            last_429 = e
            log.warning("Groq key #%d rate-limited, trying next key (%d total)", idx, len(GROQ_KEYS))
            continue
    # все ключи исчерпали лимит
    raise _GroqRateLimited(str(last_429) if last_429 else "all Groq keys rate-limited")


# Серверный фильтр Whisper-галлюцинаций — последняя линия защиты,
# если клиентский фильтр пропустил. Whisper тренировался на YouTube,
# поэтому на тишине / шуме часто выплёвывает куски титров.
_HALLUCINATION_EXACT = {
    "спасибо", "спасибо за внимание", "спасибо за просмотр", "спасибо большое",
    "продолжение следует", "продолжение следует...",
    "субтитры", "субтитры подогнал", "субтитры сделал",
    "субтитры сделал dimatorzok", "субтитры создавал dimatorzok",
    "редактор субтитров а.семкин", "корректор а.кулакова",
    "до встречи", "до новых встреч", "до скорой встречи",
    "до свидания", "пока всем", "всем пока", "всем спасибо",
    "ну", "так", "и", "да", "вот", "ага", "угу", "ох", "эх", "хм",
    "конец", "конец фильма", "конец видео", "начало", "стоп",
    "продолжение", "тишина", "молчание", "аплодисменты", "музыка",
    # Частые галлюцинации Whisper на тишине/шуме (наблюдались в логах 16.06):
    "поехали", "поехали.", "слышь", "прекрасно", "качество",
    "давай", "давай.", "у нас", "у нас?", "и когда", "время",
    "вот и есть", "ваши младенцы", "вечный комплекс",
    "thanks", "thank you", "you", "bye", "okay", "ok", "the end",
    ".", "..", "...", "[музыка]", "(музыка)",
    "[аплодисменты]", "(аплодисменты)",
    "подписывайтесь на канал", "ставьте лайки", "ставьте лайк",
    "не забывайте подписываться", "не забудьте подписаться",
}

_HALLUCINATION_PATTERNS = (
    "продолжение следует",
    "субтитры создавал",
    "субтитры сделал",
    "субтитры подогнал",
    "редактор субтитров",
    "корректор",
    "спасибо за просмотр",
    "спасибо за внимание",
    "dimatorzok",
    "семкин",
    "кулакова",
    "подписывайтесь на канал",
    "ставьте лайк",
    "поставьте лайк",
    "не забудьте подписаться",
)


def _looks_like_hallucination(text: str) -> bool:
    if not text:
        return True
    cleaned = text.strip().strip(".!?,, \n\r\t").lower()
    if len(cleaned) < 3:
        return True
    if cleaned in _HALLUCINATION_EXACT:
        return True
    return any(p in cleaned for p in _HALLUCINATION_PATTERNS)


async def health(request):
    return web.json_response({
        "status": "ok",
        "backend": STT_BACKEND,
        "local_ready": _local_model is not None,
        "auth_ready": ACCESS_REGISTRY is not None if PRODUCT_AUTH_ENABLED else API_KEY_CONFIGURED,
        "service": "hermes-stt-proxy"
    })


async def transcribe(request):
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "", 1).strip() if auth.startswith("Bearer ") else ""
    if PRODUCT_AUTH_ENABLED:
        if ACCESS_REGISTRY is None:
            return web.json_response(
                {"error": "STT proxy product authentication is unavailable"}, status=503
            )
        principal = ACCESS_REGISTRY.authenticate(token)
        if principal is None:
            return web.json_response({"error": "Invalid API key"}, status=401)
        session_id = request.headers.get("X-Hermes-Session-Id", "")
        if not session_id or not ACCESS_REGISTRY.claim_session(principal, session_id):
            return web.json_response({"error": "Invalid voice session"}, status=403)
    else:
        if not API_KEY_CONFIGURED:
            return web.json_response(
                {"error": "STT proxy is not configured with a valid API_SERVER_KEY"},
                status=503,
            )
        if not auth.startswith("Bearer "):
            return web.json_response({"error": "Missing Authorization header"}, status=401)
        if not hmac.compare_digest(token, API_SERVER_KEY):
            return web.json_response({"error": "Invalid API key"}, status=401)

    async def operation():
        audio_data, language = await read_audio_upload(request)
        return await _transcribe_audio(audio_data, language)

    if PRODUCT_AUTH_ENABLED:
        return await guarded_voice(
            operation, registry=ACCESS_REGISTRY, token=token, request=request,
        )
    async with asyncio.timeout(90):
        return await operation()


async def _transcribe_audio(audio_data, language):

    backend_order: list[str] = []
    if STT_BACKEND == "local":
        backend_order = ["local"]
    elif STT_BACKEND == "groq":
        backend_order = ["groq"]
    else:  # auto
        backend_order = ["local", "groq"]

    for backend in backend_order:
        t0 = time.monotonic()
        try:
            if backend == "local":
                text, meta = await _transcribe_local(audio_data, language)
            else:
                text, meta = await _transcribe_groq(audio_data, "voice.wav", language)
            meta["latency_s"] = round(time.monotonic() - t0, 2)
            if _looks_like_hallucination(text):
                log.info("[%s] empty speech (%.1fs)", backend, meta["latency_s"])
                return web.json_response({"text": "", "meta": meta})
            log.info("[%s] transcription completed (%.1fs)", backend, meta["latency_s"])
            return web.json_response({"text": text, "meta": meta})
        except web.HTTPException:
            raise
        except Exception as e:
            log.warning("backend %s failed (%s)", backend, type(e).__name__)
            continue

    return web.json_response(
        {"error": "Speech recognition is temporarily unavailable"},
        status=503,
    )


def main():
    if STT_BACKEND in ("groq", "auto") and not GROQ_API_KEY:
        log.warning("GROQ_API_KEY не задан — Groq backend будет пропущен")

    app = web.Application(client_max_size=50 * 1024 * 1024)
    app.router.add_get("/health", health)
    app.router.add_post("/v1/audio/transcriptions", transcribe)
    if STT_BACKEND in ("local", "auto"):
        async def _on_startup(app):
            asyncio.create_task(_warmup_safe())
        async def _warmup_safe():
            try:
                await _ensure_local_model()
            except Exception as e:
                log.warning("local warmup failed (%s)", type(e).__name__)
        app.on_startup.append(_on_startup)

    log.info(f"🎙️  Hermes STT Proxy запущен на http://{HOST}:{PORT}")
    log.info(
        "    Auth mode: %s",
        "product device tokens" if PRODUCT_AUTH_ENABLED else "legacy API_SERVER_KEY",
    )
    if PRODUCT_AUTH_ENABLED and ACCESS_REGISTRY is None:
        log.error("STT proxy product auth unavailable: %s", PRODUCT_AUTH_ERROR or "unknown error")
    elif not PRODUCT_AUTH_ENABLED and not API_KEY_CONFIGURED:
        log.error("STT proxy will reject requests until API_SERVER_KEY is a unique secret")
    log.info("    STT_BACKEND=%s", STT_BACKEND)
    log.info(f"    Local model: {LOCAL_MODEL_SIZE} (device={LOCAL_DEVICE}, compute={LOCAL_COMPUTE or 'auto'})")
    log.info(f"    Endpoint: POST /v1/audio/transcriptions")

    web.run_app(app, host=HOST, port=PORT, access_log=None)


if __name__ == "__main__":
    main()
