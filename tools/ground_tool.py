"""
GROUND — Continuous Device Observer (вдохновлено droidclaw/Kira).

Фоновый «глаз» Тройки: периодически снимает экран телефона, и — только если
картинка заметно изменилась (delta-триггер) — отдаёт её vision-модели и кладёт
краткое «что сейчас на экране» в общий контекст. Так Тройка понимает чем занят
Миша БЕЗ явной команды «посмотри на экран».

Отличие от Kira: у Kira агент живёт на телефоне и снимает экран тупо раз в 60с.
У нас агент на сервере, телефон — тонкий клиент, поэтому:
  • снимаем только когда экран ВКЛЮЧЁН и картинка изменилась (экономим батарею + vision-токены);
  • при «телефон молчит / экран выкл» увеличиваем интервал (backoff);
  • анализ через уже существующий vision_analyze (config: auxiliary.vision = Qwen-VL).

Состояние наблюдения держим в модуле — его читают DAEMON и (опционально) инжект
в system prompt. На диск не пишем (как GROUND у Kira — «files not stored»).

Tools:
  • ground_start — запустить фоновое наблюдение (опц. interval_sec)
  • ground_stop  — остановить
  • ground_status — что Тройка «видит» прямо сейчас + статистика
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# --- настройки по умолчанию -------------------------------------------------
_DEFAULT_INTERVAL_SEC = 45        # базовый интервал опроса экрана
_IDLE_INTERVAL_SEC = 180          # когда экран выкл/телефон молчит — реже
_MAX_BACKOFF_SEC = 600            # потолок backoff при цепочке ошибок
_DELTA_FRACTION = 0.12           # какая доля perceptual-«корзин» должна отличаться, чтобы считать «экран изменился» (12%)
_OBS_TTL_SEC = 600                # после стольких секунд последнее наблюдение считается протухшим


@dataclass
class _GroundState:
    running: bool = False
    task: Optional[asyncio.Task] = None
    interval_sec: float = _DEFAULT_INTERVAL_SEC
    last_hash: Optional[str] = None
    last_observation: Optional[str] = None   # текст vision-анализа
    last_obs_ts: float = 0.0
    frames_seen: int = 0
    frames_analyzed: int = 0
    errors: int = 0
    last_error: Optional[str] = None
    started_ts: float = 0.0


_state = _GroundState()


def get_current_observation(max_age_sec: float = _OBS_TTL_SEC) -> Optional[str]:
    """Свежее наблюдение GROUND для DAEMON / контекста. None если протухло."""
    if not _state.last_observation:
        return None
    if time.time() - _state.last_obs_ts > max_age_sec:
        return None
    return _state.last_observation


def is_running() -> bool:
    return _state.running and _state.task is not None and not _state.task.done()


# --- perceptual delta -------------------------------------------------------

def _perceptual_buckets(image_b64: str) -> Optional[str]:
    """Грубый perceptual-хэш: downscale до 16x16 grayscale, квантуем яркость.

    Возвращает строку из «корзин». Сравнение по числу различающихся корзин
    устойчиво к мелкому шуму (мигающие часы, курсор), но ловит реальную смену
    экрана/приложения. Требует Pillow; без него падаем на точный sha1 (тогда
    delta-триггер = «любое отличие байтов»).
    """
    try:
        from PIL import Image
        import io
        raw = base64.b64decode(image_b64)
        img = Image.open(io.BytesIO(raw)).convert("L").resize((16, 16))
        px = img.getdata()
        # квантуем 0..255 → 0..7 (3 бита): лёгкие колебания яркости (антиалиасинг,
        # мигающий курсор, секунды на часах) не считаются отличием.
        return "".join(str(p >> 5) for p in px)
    except Exception:
        try:
            return hashlib.sha1(base64.b64decode(image_b64)).hexdigest()
        except Exception:
            return None


def _diff_fraction(a: str, b: str) -> float:
    """Доля различающихся позиций (0..1). Если длины разные — 1.0 (считаем «всё изменилось»)."""
    if a is None or b is None or len(a) != len(b) or not a:
        return 1.0
    diff = sum(1 for x, y in zip(a, b) if x != y)
    return diff / len(a)


def _changed_enough(new_hash: Optional[str]) -> bool:
    if new_hash is None:
        return True
    if _state.last_hash is None:
        return True
    return _diff_fraction(_state.last_hash, new_hash) >= _DELTA_FRACTION


# --- основной цикл ----------------------------------------------------------

async def _capture_screen_b64() -> Optional[Dict[str, Any]]:
    """Снять экран телефона. Возвращает dict результата или None при ошибке/выкл-экране."""
    from tools.android_tool import _bridge, _call_phone
    if not _bridge().is_connected():
        return None
    raw = await _call_phone("screenshot", {}, timeout=20)
    try:
        return json.loads(raw)
    except Exception:
        return None


async def _analyze(image_b64: str) -> Optional[str]:
    """Vision-анализ скрина → короткое описание «что на экране»."""
    import os
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="ground_")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(base64.b64decode(image_b64))
        from tools.vision_tools import vision_analyze_tool
        prompt = (
            "Это скриншот экрана телефона пользователя. Опиши КРАТКО (1-2 фразы) "
            "что он сейчас делает: какое приложение открыто, чем занят. "
            "Без воды, по-русски. Если экран блокировки/пустой — так и скажи."
        )
        res = await vision_analyze_tool(tmp, prompt)
        try:
            data = json.loads(res)
            return (data.get("analysis") or "").strip() or None
        except Exception:
            return res.strip() or None
    except Exception as e:
        logger.debug("GROUND analyze failed: %s", e)
        return None
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


async def _loop() -> None:
    logger.info("GROUND observer started (interval=%ss)", _state.interval_sec)
    backoff = _state.interval_sec
    while _state.running:
        try:
            shot = await _capture_screen_b64()
            if not shot or not shot.get("ok") or not shot.get("image"):
                # экран выключен / телефон молчит / нет прав — наблюдать реже
                backoff = min(max(_IDLE_INTERVAL_SEC, backoff), _MAX_BACKOFF_SEC)
                await asyncio.sleep(backoff)
                continue

            backoff = _state.interval_sec  # успех — вернули нормальный темп
            _state.frames_seen += 1
            image_b64 = shot["image"]
            new_hash = _perceptual_buckets(image_b64)

            if _changed_enough(new_hash):
                obs = await _analyze(image_b64)
                _state.last_hash = new_hash
                if obs:
                    _state.last_observation = obs
                    _state.last_obs_ts = time.time()
                    _state.frames_analyzed += 1
                    logger.info("GROUND: %s", obs[:120])
            # если не изменилось — просто ждём, vision не зовём (экономия)

            await asyncio.sleep(_state.interval_sec)
        except asyncio.CancelledError:
            break
        except Exception as e:
            _state.errors += 1
            _state.last_error = str(e)[:200]
            logger.warning("GROUND loop error: %s", e)
            backoff = min(backoff * 2, _MAX_BACKOFF_SEC)
            await asyncio.sleep(backoff)
    logger.info("GROUND observer stopped")


# --- handlers ---------------------------------------------------------------

async def _handle_ground_start(args: Dict[str, Any], **kw) -> str:
    if is_running():
        return json.dumps({
            "ok": True, "already_running": True,
            "interval_sec": _state.interval_sec,
        }, ensure_ascii=False)

    try:
        iv = float(args.get("interval_sec") or _DEFAULT_INTERVAL_SEC)
    except (TypeError, ValueError):
        iv = _DEFAULT_INTERVAL_SEC
    _state.interval_sec = max(15.0, min(iv, 600.0))  # 15с..10мин

    from tools.android_tool import _check_phone_connected
    if not _check_phone_connected():
        return json.dumps({
            "ok": False,
            "error": "phone_not_connected",
            "hint": "Телефон не подключён — наблюдать нечего. Подключи приложение Тройки.",
        }, ensure_ascii=False)

    _state.running = True
    _state.started_ts = time.time()
    _state.task = asyncio.create_task(_loop())
    return json.dumps({
        "ok": True, "started": True,
        "interval_sec": _state.interval_sec,
        "note": "Фоновое наблюдение запущено. Снимаю экран и анализирую только при изменениях.",
    }, ensure_ascii=False)


async def _handle_ground_stop(args: Dict[str, Any], **kw) -> str:
    if not is_running():
        _state.running = False
        return json.dumps({"ok": True, "was_running": False}, ensure_ascii=False)
    _state.running = False
    if _state.task:
        _state.task.cancel()
        try:
            await _state.task
        except (asyncio.CancelledError, Exception):
            pass
    _state.task = None
    return json.dumps({
        "ok": True, "stopped": True,
        "frames_seen": _state.frames_seen,
        "frames_analyzed": _state.frames_analyzed,
    }, ensure_ascii=False)


async def _handle_ground_status(args: Dict[str, Any], **kw) -> str:
    obs = get_current_observation()
    return json.dumps({
        "ok": True,
        "running": is_running(),
        "interval_sec": _state.interval_sec,
        "current_observation": obs,
        "observation_age_sec": (round(time.time() - _state.last_obs_ts) if _state.last_obs_ts else None),
        "frames_seen": _state.frames_seen,
        "frames_analyzed": _state.frames_analyzed,
        "errors": _state.errors,
        "last_error": _state.last_error,
        "uptime_sec": (round(time.time() - _state.started_ts) if _state.started_ts else 0),
    }, ensure_ascii=False)


# --- schemas ----------------------------------------------------------------

GROUND_START_SCHEMA = {
    "name": "ground_start",
    "description": (
        "Включить фоновое наблюдение за экраном телефона (GROUND). Тройка начнёт "
        "периодически 'видеть' что делает пользователь, анализируя экран только "
        "когда картинка изменилась. Используй когда пользователь просит 'следи за "
        "экраном', 'смотри что я делаю', 'будь в курсе чем я занят'. Требует "
        "подключённого телефона и включённого AccessibilityService."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "interval_sec": {
                "type": "number",
                "description": "Интервал опроса экрана в секундах (15..600, по умолчанию 45).",
            },
        },
    },
}

GROUND_STOP_SCHEMA = {
    "name": "ground_stop",
    "description": "Выключить фоновое наблюдение за экраном (GROUND). Используй когда пользователь говорит 'хватит следить', 'перестань смотреть на экран'.",
    "parameters": {"type": "object", "properties": {}},
}

GROUND_STATUS_SCHEMA = {
    "name": "ground_status",
    "description": (
        "Узнать что Тройка сейчас 'видит' на экране телефона и статистику наблюдения "
        "(GROUND). Вернёт последнее наблюдение чем занят пользователь. Используй когда "
        "пользователь спрашивает 'что я сейчас делаю по-твоему', 'ты следишь?'."
    ),
    "parameters": {"type": "object", "properties": {}},
}


def _ground_available() -> bool:
    """GROUND доступен если есть телефон-bridge (vision проверяется в рантайме)."""
    try:
        from tools.android_tool import _check_phone_connected
        return _check_phone_connected()
    except Exception:
        return False


# --- registration -----------------------------------------------------------

from tools.registry import registry  # noqa: E402

registry.register(name="ground_start", toolset="ground", schema=GROUND_START_SCHEMA,
                  handler=_handle_ground_start, check_fn=_ground_available,
                  is_async=True, emoji="👁️")
registry.register(name="ground_stop", toolset="ground", schema=GROUND_STOP_SCHEMA,
                  handler=_handle_ground_stop,
                  is_async=True, emoji="👁️")
registry.register(name="ground_status", toolset="ground", schema=GROUND_STATUS_SCHEMA,
                  handler=_handle_ground_status,
                  is_async=True, emoji="👁️")
