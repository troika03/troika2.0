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
import tempfile
from pathlib import Path
from dotenv import load_dotenv

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

try:
    _home = Path.home()
except (RuntimeError, OSError):
    _home = Path("/tmp")
_try_load_env(_home / ".troika" / ".env")
_try_load_env(_home / "troika" / ".env")

from aiohttp import web, ClientSession, FormData
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("stt-proxy")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
API_SERVER_KEY = os.getenv("API_SERVER_KEY", "hermes-2024")
PORT = int(os.getenv("STT_PROXY_PORT", "8643"))
HOST = "0.0.0.0"

# Backend selection
STT_BACKEND = (os.getenv("STT_BACKEND") or "auto").strip().lower()
LOCAL_MODEL_SIZE = (os.getenv("WHISPER_MODEL_SIZE") or "large-v3").strip()
LOCAL_DEVICE = (os.getenv("WHISPER_DEVICE") or "auto").strip().lower()
LOCAL_COMPUTE = (os.getenv("WHISPER_COMPUTE_TYPE") or "").strip().lower()

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


# ── Local faster-whisper (lazy init) ──────────────────────────────────────

_local_model = None
_local_init_error: str = ""
_local_lock = asyncio.Lock()


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
    global _local_model
    if _local_model is not None:
        return _local_model
    async with _local_lock:
        if _local_model is not None:
            return _local_model
        # blocking → in thread
        loop = asyncio.get_running_loop()
        model, device, compute = await loop.run_in_executor(None, _init_local_model_sync)
        _local_model = (model, device, compute)
        return _local_model


async def _transcribe_local(audio_bytes: bytes, language: str) -> tuple[str, dict]:
    """Сохраняет во временный файл и гоняет через faster-whisper."""
    model, device, compute = await _ensure_local_model()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        tmp.write(audio_bytes)
        tmp.flush()
        tmp.close()

        def _run():
            segments, info = model.transcribe(
                tmp.name,
                language=language or None,
                beam_size=1,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                temperature=0.0,
                condition_on_previous_text=False,
            )
            text_parts = [seg.text for seg in segments]
            return "".join(text_parts).strip(), info

        loop = asyncio.get_running_loop()
        text, info = await loop.run_in_executor(None, _run)
        meta = {
            "backend": "local",
            "device": device,
            "compute": compute,
            "model": LOCAL_MODEL_SIZE,
            "language": getattr(info, "language", language),
            "duration": round(getattr(info, "duration", 0.0) or 0.0, 2),
        }
        return text, meta
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


async def _groq_post(audio_bytes: bytes, filename: str, language: str, model: str) -> str:
    form = FormData()
    form.add_field("file", audio_bytes, filename=filename, content_type="audio/m4a")
    form.add_field("model", model)
    form.add_field("language", language)
    form.add_field("response_format", "json")
    form.add_field("temperature", "0")
    form.add_field("prompt", "")
    async with ClientSession() as session:
        async with session.post(
            GROQ_URL, data=form,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            # 30с заставляли ждать полминуты при лаге сети → «не реагирует».
            # 8с: не дождались — отдаём провал быстро, а не висим. (env override)
            timeout=int(os.getenv("GROQ_STT_TIMEOUT", "8")),
        ) as resp:
            if resp.status != 200:
                err = await resp.text()
                raise RuntimeError(f"Groq {resp.status}: {err}")
            data = await resp.json()
            return (data.get("text", "") or "").strip()


async def _transcribe_groq(audio_bytes: bytes, filename: str, language: str) -> tuple[str, dict]:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY не задан")
    # turbo ~2-4x быстрее large-v3 на коротких командах — режет паузу перед ответом.
    # Если turbo недоступен на ключе (403/404) — один раз падаем на проверенный large-v3.
    primary = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")
    try:
        text = await _groq_post(audio_bytes, filename, language, primary)
        return text, {"backend": "groq", "model": primary}
    except RuntimeError as e:
        msg = str(e)
        if primary != "whisper-large-v3" and (" 403" in msg or " 404" in msg or "model" in msg.lower()):
            text = await _groq_post(audio_bytes, filename, language, "whisper-large-v3")
            return text, {"backend": "groq", "model": "whisper-large-v3", "fellback": True}
        raise


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
        "local_init_error": _local_init_error or None,
        "groq_key_set": bool(GROQ_API_KEY),
        "service": "hermes-stt-proxy"
    })


async def transcribe(request):
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return web.json_response({"error": "Missing Authorization header"}, status=401)
    token = auth.replace("Bearer ", "").strip()
    if token != API_SERVER_KEY:
        return web.json_response({"error": "Invalid API key"}, status=401)

    reader = await request.multipart()
    audio_data = None
    audio_filename = "voice.m4a"
    language = "ru"

    async for field in reader:
        if field.name == "file":
            audio_filename = field.filename or "voice.m4a"
            audio_data = await field.read()
        elif field.name == "language":
            language = (await field.text()).strip() or "ru"

    if not audio_data:
        return web.json_response({"error": "No audio file in request"}, status=400)

    log.info(f"Got audio: {len(audio_data)} bytes, lang={language}")

    backend_order: list[str] = []
    if STT_BACKEND == "local":
        backend_order = ["local"]
    elif STT_BACKEND == "groq":
        backend_order = ["groq"]
    else:  # auto
        backend_order = ["local", "groq"]

    last_err = None
    for backend in backend_order:
        t0 = time.monotonic()
        try:
            if backend == "local":
                text, meta = await _transcribe_local(audio_data, language)
            else:
                text, meta = await _transcribe_groq(audio_data, audio_filename, language)
            meta["latency_s"] = round(time.monotonic() - t0, 2)
            if _looks_like_hallucination(text):
                log.info("[%s] hallucination filtered: %r (%.1fs)", backend, text, meta["latency_s"])
                return web.json_response({"text": "", "meta": meta})
            log.info("[%s] %r (%.1fs)", backend, text, meta["latency_s"])
            return web.json_response({"text": text, "meta": meta})
        except Exception as e:
            last_err = e
            log.warning("backend %s failed: %s", backend, e)
            continue

    return web.json_response(
        {"error": f"all backends failed: {last_err}"},
        status=500,
    )


def main():
    if STT_BACKEND in ("groq", "auto") and not GROQ_API_KEY:
        log.warning("GROQ_API_KEY не задан — Groq backend будет пропущен")

    if STT_BACKEND in ("local", "auto"):
        # Прогрев модели в фоне — не блокируем старт, но первое распознавание
        # будет быстрым.
        async def _warmup():
            try:
                await _ensure_local_model()
            except Exception as e:
                log.warning("local backend warmup failed: %s", e)

        async def _start():
            asyncio.create_task(_warmup())

    app = web.Application(client_max_size=50 * 1024 * 1024)
    app.router.add_get("/health", health)
    app.router.add_post("/v1/audio/transcriptions", transcribe)
    if STT_BACKEND in ("local", "auto"):
        async def _on_startup(app):
            asyncio.create_task(_ensure_local_model() if False else _warmup_safe())
        async def _warmup_safe():
            try:
                await _ensure_local_model()
            except Exception as e:
                log.warning("local warmup failed: %s", e)
        app.on_startup.append(_on_startup)

    log.info(f"🎙️  Hermes STT Proxy запущен на http://{HOST}:{PORT}")
    log.info(f"    API ключ: {API_SERVER_KEY}")
    log.info(f"    STT_BACKEND={STT_BACKEND}  GROQ_API_KEY={'✓' if GROQ_API_KEY else '✗'}")
    log.info(f"    Local model: {LOCAL_MODEL_SIZE} (device={LOCAL_DEVICE}, compute={LOCAL_COMPUTE or 'auto'})")
    log.info(f"    Endpoint: POST /v1/audio/transcriptions")

    web.run_app(app, host=HOST, port=PORT, access_log=None)


if __name__ == "__main__":
    main()
