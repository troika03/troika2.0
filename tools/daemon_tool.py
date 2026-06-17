"""
DAEMON — Background Mind (вдохновлено droidclaw/Kira).

Автономный «ум» Тройки: фоновый цикл, который раз в ~8 минут собирает контекст
(что Тройка видит через GROUND, что знает через SOMA, какие задачи в работе,
время суток) и спрашивает саму себя: «Есть ли СЕЙЧАС реальный повод написать
Мише первой?». Если да — отправляет короткое голосовое сообщение. Если нет —
молчит.

В отличие от Kira (пишет в Telegram каждые 8 мин и легко спамит) у нас жёсткий
анти-спам:
  • тихие часы (по умолчанию 23:00–09:00 — ночью не беспокоим);
  • минимальный интервал между проактивными сообщениями (default 25 мин);
  • лимит сообщений в день (default 6);
  • говорим только если телефон подключён;
  • LLM обязана вернуть ровно 'SILENCE' если повода нет — и мы это уважаем.

Доставка — через тот же phone_bridge.notify_voice, что и job_runner.
Цикл запускается тулом daemon_start (или автоматически при старте gateway, если
включён DAEMON_AUTOSTART=1) и живёт как asyncio-таск.

Tools:
  • daemon_start  — включить автономный режим
  • daemon_stop   — выключить
  • daemon_status — состояние + когда последний раз говорил
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# --- настройки (через env переопределяемы) ----------------------------------
_THINK_INTERVAL_SEC = int(os.environ.get("DAEMON_INTERVAL_SEC", "480"))   # 8 мин как Kira
_MIN_GAP_SEC = int(os.environ.get("DAEMON_MIN_GAP_SEC", "1500"))          # ≥25 мин между сообщениями
_MAX_PER_DAY = int(os.environ.get("DAEMON_MAX_PER_DAY", "6"))
_QUIET_START = int(os.environ.get("DAEMON_QUIET_START", "23"))            # тихо с 23:00
_QUIET_END = int(os.environ.get("DAEMON_QUIET_END", "9"))                 # до 09:00


@dataclass
class _DaemonState:
    running: bool = False
    task: Optional[asyncio.Task] = None
    last_spoke_ts: float = 0.0
    last_message: Optional[str] = None
    spoken_today: int = 0
    today: str = ""
    thoughts: int = 0          # сколько раз «подумал»
    started_ts: float = 0.0
    last_decision: Optional[str] = None


_state = _DaemonState()


def is_running() -> bool:
    return _state.running and _state.task is not None and not _state.task.done()


def _in_quiet_hours() -> bool:
    h = datetime.now().hour
    if _QUIET_START <= _QUIET_END:
        return _QUIET_START <= h < _QUIET_END
    # окно через полночь (например 23..9)
    return h >= _QUIET_START or h < _QUIET_END


def _roll_day() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    if today != _state.today:
        _state.today = today
        _state.spoken_today = 0


def _can_speak() -> Optional[str]:
    """None если можно говорить, иначе строка-причина почему нельзя."""
    _roll_day()
    if _in_quiet_hours():
        return "quiet_hours"
    if _state.spoken_today >= _MAX_PER_DAY:
        return "daily_limit"
    if time.time() - _state.last_spoke_ts < _MIN_GAP_SEC:
        return "min_gap"
    try:
        from tools.android_tool import _bridge
        if not _bridge().is_connected():
            return "phone_offline"
    except Exception:
        return "phone_offline"
    return None


def _gather_context() -> str:
    """Собрать краткий контекст для размышления DAEMON."""
    parts: List[str] = []

    now = datetime.now()
    parts.append(f"Сейчас {now.strftime('%H:%M, %A')}.")

    # GROUND — что видно на экране
    try:
        from tools.ground_tool import get_current_observation
        obs = get_current_observation()
        if obs:
            parts.append(f"На экране телефона: {obs}")
    except Exception:
        pass

    # активные фоновые задачи
    try:
        from tools.job_runner import _list_active
        active = _list_active()
        if active:
            labels = ", ".join(
                (j.get("short_label") or j.get("kind") or "задача") for j in active[:5]
            )
            parts.append(f"В работе фоновые задачи: {labels}.")
    except Exception:
        pass

    # SOMA — самое важное о пользователе
    try:
        from tools.soma_tool import _handle_recall
        import asyncio as _a
        # _handle_recall — корутина; вызываем синхронно через новый прогон в текущем loop недопустимо,
        # поэтому читаем напрямую из БД для контекста.
        from tools.soma_tool import _db, _recency
        with _db() as conn:
            rows = conn.execute("SELECT * FROM memories").fetchall()
        scored = sorted(
            rows,
            key=lambda r: r["salience"] * r["confidence"] * _recency(r["last_seen_ts"]),
            reverse=True,
        )[:4]
        if scored:
            facts = "; ".join(r["text"] for r in scored)
            parts.append(f"Что я знаю о Мише: {facts}.")
    except Exception:
        pass

    # сколько прошло с последнего проактивного сообщения
    if _state.last_spoke_ts:
        mins = int((time.time() - _state.last_spoke_ts) / 60)
        parts.append(f"Последний раз я писала сама {mins} мин назад.")
    else:
        parts.append("Сама ещё ни разу сегодня не писала.")

    return " ".join(parts)


_SYSTEM = (
    "Ты — Тройка, голосовой ассистент Миши, в режиме автономного фонового размышления. "
    "Раз в несколько минут ты осматриваешься и решаешь: есть ли СЕЙЧАС стоящий повод "
    "написать Мише первой, не дожидаясь вопроса. Поводы бывают: заметила что он застрял/устал, "
    "вспомнила про незакрытое дело, фоновая задача готова и важна, наступило время о чём-то "
    "напомнить. НЕ беспокой по пустякам и не повторяйся. "
    "Если повода НЕТ — ответь РОВНО одним словом: SILENCE. "
    "Если повод ЕСТЬ — ответь одной короткой живой фразой (как скажешь вслух), без префиксов."
)


async def _think_once() -> Optional[str]:
    """Один цикл размышления. Возвращает фразу для озвучки или None."""
    block = _can_speak()
    if block:
        _state.last_decision = f"skip:{block}"
        # размышляем «вхолостую» только когда есть смысл — иначе не жжём токены
        return None

    context = _gather_context()
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": context + "\n\nЕсть повод написать сейчас? Ответь SILENCE или одной фразой."},
    ]
    try:
        from agent.auxiliary_client import async_call_llm, extract_content_or_reasoning
        resp = await async_call_llm(
            task="main",
            messages=messages,
            temperature=0.7,
            max_tokens=80,
            timeout=40,
        )
        text = (extract_content_or_reasoning(resp) or "").strip()
    except Exception as e:
        logger.debug("DAEMON think failed: %s", e)
        _state.last_decision = f"error:{str(e)[:60]}"
        return None

    if not text or text.upper().startswith("SILENCE") or len(text) < 4:
        _state.last_decision = "silence"
        return None

    # подчистим возможные кавычки/префиксы
    text = text.strip().strip('"').strip("«»").strip()
    _state.last_decision = "speak"
    return text[:240]


async def _deliver(text: str) -> None:
    """Озвучить проактивное сообщение на телефон + зафиксировать."""
    try:
        from tools.android_tool import _bridge
        bridge = _bridge()
        if bridge.is_connected():
            await bridge.send_command("notify_voice", {
                "text": text,
                "kind": "daemon_proactive",
                "is_proactive": True,
            }, timeout=10)
    except Exception as e:
        logger.warning("DAEMON deliver failed: %s", e)
        return

    _state.last_spoke_ts = time.time()
    _state.last_message = text
    _roll_day()
    _state.spoken_today += 1
    logger.info("DAEMON proactive: %s", text)

    # лёгкий след в дневник — что Тройка проявила инициативу
    try:
        from tools.diary_tool import _handle_add
        await _handle_add({"note": f"Сама написала Мише: «{text}»", "category": "инициатива"})
    except Exception:
        pass


async def _loop() -> None:
    logger.info("DAEMON started (interval=%ss)", _THINK_INTERVAL_SEC)
    # небольшой стартовый сдвиг, чтобы не думать прямо в момент запуска
    await asyncio.sleep(min(60, _THINK_INTERVAL_SEC))
    while _state.running:
        try:
            _state.thoughts += 1
            phrase = await _think_once()
            if phrase:
                await _deliver(phrase)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("DAEMON loop error: %s", e)
        await asyncio.sleep(_THINK_INTERVAL_SEC)
    logger.info("DAEMON stopped")


# --- handlers ----------------------------------------------------------------

async def _handle_daemon_start(args: Dict[str, Any], **_kw) -> str:
    if is_running():
        return json.dumps({"ok": True, "already_running": True}, ensure_ascii=False)
    _state.running = True
    _state.started_ts = time.time()
    _state.task = asyncio.create_task(_loop())
    return json.dumps({
        "ok": True, "started": True,
        "interval_sec": _THINK_INTERVAL_SEC,
        "quiet_hours": f"{_QUIET_START:02d}:00–{_QUIET_END:02d}:00",
        "note": "Автономный режим включён. Буду иногда писать сама, если есть повод.",
    }, ensure_ascii=False)


async def _handle_daemon_stop(args: Dict[str, Any], **_kw) -> str:
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
    return json.dumps({"ok": True, "stopped": True, "thoughts": _state.thoughts}, ensure_ascii=False)


async def _handle_daemon_status(args: Dict[str, Any], **_kw) -> str:
    _roll_day()
    return json.dumps({
        "ok": True,
        "running": is_running(),
        "interval_sec": _THINK_INTERVAL_SEC,
        "thoughts": _state.thoughts,
        "spoken_today": _state.spoken_today,
        "max_per_day": _MAX_PER_DAY,
        "last_message": _state.last_message,
        "last_spoke_min_ago": (round((time.time() - _state.last_spoke_ts) / 60) if _state.last_spoke_ts else None),
        "last_decision": _state.last_decision,
        "in_quiet_hours": _in_quiet_hours(),
        "uptime_sec": (round(time.time() - _state.started_ts) if _state.started_ts else 0),
    }, ensure_ascii=False)


def maybe_autostart() -> None:
    """Запустить DAEMON автоматически при старте gateway, если DAEMON_AUTOSTART=1.
    Безопасно дёргать из async-контекста (создаёт таск). No-op вне event loop."""
    if os.environ.get("DAEMON_AUTOSTART", "").strip() not in ("1", "true", "yes"):
        return
    if is_running():
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            _state.running = True
            _state.started_ts = time.time()
            _state.task = loop.create_task(_loop())
            logger.info("DAEMON autostarted via env")
    except Exception as e:
        logger.debug("DAEMON autostart skipped: %s", e)


# --- schemas -----------------------------------------------------------------

DAEMON_START_SCHEMA = {
    "name": "daemon_start",
    "description": (
        "Включить автономный режим (DAEMON): Тройка будет иногда сама писать первой, "
        "если заметит повод — что ты застрял, устал, готова важная задача, пора о чём-то "
        "напомнить. Не спамит: тихие часы ночью, лимит в день, пауза между сообщениями. "
        "Используй когда пользователь говорит 'будь активнее', 'пиши сама когда надо', "
        "'следи и подсказывай'."
    ),
    "parameters": {"type": "object", "properties": {}},
}

DAEMON_STOP_SCHEMA = {
    "name": "daemon_stop",
    "description": "Выключить автономный режим (DAEMON). Тройка перестанет писать сама и будет отвечать только на обращения. Используй когда 'не пиши сама', 'хватит инициативы', 'отвечай только когда спрошу'.",
    "parameters": {"type": "object", "properties": {}},
}

DAEMON_STATUS_SCHEMA = {
    "name": "daemon_status",
    "description": "Состояние автономного режима (DAEMON): включён ли, сколько раз сегодня писала сама, когда последний раз, тихие ли сейчас часы.",
    "parameters": {"type": "object", "properties": {}},
}


# --- registration ------------------------------------------------------------

from tools.registry import registry  # noqa: E402

registry.register(name="daemon_start", toolset="daemon", schema=DAEMON_START_SCHEMA,
                  handler=_handle_daemon_start, is_async=True, emoji="🌙")
registry.register(name="daemon_stop", toolset="daemon", schema=DAEMON_STOP_SCHEMA,
                  handler=_handle_daemon_stop, is_async=True, emoji="🌙")
registry.register(name="daemon_status", toolset="daemon", schema=DAEMON_STATUS_SCHEMA,
                  handler=_handle_daemon_status, is_async=True, emoji="🌙")
