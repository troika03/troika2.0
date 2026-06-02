"""
Job runner для Тройки: фоновые задачи с уведомлением голосом по готовности.

Поток:
- `submit(kind, payload, session_id)` → возвращает task_id, ставит задачу в очередь.
- `asyncio.Semaphore(3)` ограничивает параллелизм.
- Worker исполняет handler из `KIND_HANDLERS`, сохраняет результат в SQLite.
- При успехе/ошибке делает 2 вещи:
    1) Шлёт `notify_voice` на телефон через phone_bridge (TTS-озвучка).
    2) Инжектит system-сообщение в session history, чтобы LLM знала о готовой задаче в следующем turn.

Хранение: `~/.troika/jobs.db` (SQLite). Состояния: queued/running/done/failed/cancelled.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_TROIKA = Path.home() / ".troika"
_DB_PATH = _TROIKA / "jobs.db"
_MAX_PARALLEL = 6                 # лимит снят: до 6 параллельных агентов
_WATCHDOG_INTERVAL = 30          # сек между проверками
_HARD_TIMEOUT_SEC = 3600          # дефолтный потолок для job без явного timeout (1 час)
_WATCHDOG_GRACE_SEC = 300         # буфер сверх payload.timeout перед force-fail
_AUTOPILOT_TIMEOUT_SEC = 21600    # автопилот может идти до 6 часов
_ORPHAN_THRESHOLD = 60            # если задача в running дольше — это сирота с прошлой жизни gateway


def _effective_timeout(payload_json: str) -> int:
    """Сколько секунд ждём задачу до force-fail watchdog'ом.

    Берём payload.timeout (если есть) + грейс-буфер, иначе дефолтный потолок.
    Так длинные сборки/автопилот не убиваются раньше времени."""
    try:
        payload = json.loads(payload_json) if payload_json else {}
        t = int(payload.get("timeout", 0) or 0)
        if t > 0:
            return t + _WATCHDOG_GRACE_SEC
    except Exception:
        pass
    return _HARD_TIMEOUT_SEC

# kind -> async handler(payload) -> result dict with {ok, say_to_user, ...}
KIND_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {}


def register_handler(kind: str, fn: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]) -> None:
    KIND_HANDLERS[kind] = fn


# ---------------------------------------------------------------------------
# SQLite store
# ---------------------------------------------------------------------------

def _ensure_db() -> None:
    _TROIKA.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                session_id TEXT,
                short_label TEXT,
                payload_json TEXT NOT NULL,
                result_json TEXT,
                error TEXT,
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_session ON jobs(session_id)")


@contextmanager
def _db():
    _ensure_db()
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _insert(job_id: str, kind: str, payload: Dict[str, Any], session_id: Optional[str], label: str) -> None:
    with _db() as c:
        c.execute(
            "INSERT INTO jobs(id,kind,status,session_id,short_label,payload_json,created_at) VALUES (?,?,?,?,?,?,?)",
            (job_id, kind, "queued", session_id, label, json.dumps(payload, ensure_ascii=False), time.time()),
        )


def _update(job_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [job_id]
    with _db() as c:
        c.execute(f"UPDATE jobs SET {cols} WHERE id=?", vals)


def _get(job_id: str) -> Optional[Dict[str, Any]]:
    with _db() as c:
        row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None


def _list_active(session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _db() as c:
        if session_id:
            rows = c.execute(
                "SELECT * FROM jobs WHERE status IN ('queued','running') AND session_id=? ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM jobs WHERE status IN ('queued','running') ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def _list_recent(session_id: Optional[str], limit: int = 5) -> List[Dict[str, Any]]:
    with _db() as c:
        if session_id:
            rows = c.execute(
                "SELECT * FROM jobs WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Worker runtime (in-process, lives with gateway lifecycle)
# ---------------------------------------------------------------------------

_semaphore: Optional[asyncio.Semaphore] = None
_active_tasks: Dict[str, asyncio.Task] = {}
_pending_notifications: Dict[str, List[Dict[str, Any]]] = {}  # session_id -> list of notes
_pending_lock = asyncio.Lock() if False else None  # init lazily inside loop


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(_MAX_PARALLEL)
    return _semaphore


def submit(kind: str, payload: Dict[str, Any], session_id: Optional[str] = None, short_label: str = "") -> str:
    """Поставить задачу в очередь. Возвращает task_id."""
    if kind not in KIND_HANDLERS:
        raise ValueError(f"unknown job kind: {kind}")
    ensure_watchdog_started()
    job_id = uuid.uuid4().hex[:12]
    label = short_label or kind
    _insert(job_id, kind, payload, session_id, label)
    task = asyncio.create_task(_worker(job_id))
    _active_tasks[job_id] = task
    task.add_done_callback(lambda _t: _active_tasks.pop(job_id, None))
    return job_id


async def _worker(job_id: str) -> None:
    job = _get(job_id)
    if not job:
        return
    kind = job["kind"]
    payload = json.loads(job["payload_json"])
    handler = KIND_HANDLERS.get(kind)
    if not handler:
        _update(job_id, status="failed", error=f"no handler for {kind}", finished_at=time.time())
        return

    sem = _get_semaphore()
    async with sem:
        _update(job_id, status="running", started_at=time.time())
        logger.info("job %s [%s] started: %s", job_id, kind, job.get("short_label"))
        # Heartbeat task: раз в HEARTBEAT_SEC напоминает голосом что Тройка
        # ещё работает над задачей. Только если job длится дольше FIRST_HEARTBEAT_SEC.
        hb_task = asyncio.create_task(_heartbeat_loop(job_id, kind, job.get("short_label") or kind))
        try:
            result = await handler(payload)
            _update(
                job_id,
                status="done" if result.get("ok") else "failed",
                result_json=json.dumps(result, ensure_ascii=False),
                finished_at=time.time(),
            )
            await _on_finish(job_id, kind, job.get("session_id"), job.get("short_label") or kind, result)
        except Exception as e:
            logger.exception("job %s [%s] crashed", job_id, kind)
            _update(job_id, status="failed", error=str(e), finished_at=time.time())
            await _on_finish(job_id, kind, job.get("session_id"), job.get("short_label") or kind,
                             {"ok": False, "error": str(e), "say_to_user": f"Задача '{job.get('short_label') or kind}' упала: {e}"})
        finally:
            hb_task.cancel()
            try:
                await asyncio.wait_for(hb_task, timeout=1)
            except Exception:
                pass


_FIRST_HEARTBEAT_SEC = 90      # первое напоминание через 90с
_HEARTBEAT_INTERVAL_SEC = 120  # дальше каждые 2 минуты
_HEARTBEAT_MAX = 3             # не более 3 напоминаний (иначе всё надоест)

_HEARTBEAT_PHRASES = [
    "ещё работаю",
    "продолжаю, секунду",
    "почти готово, потерпи",
]


async def _heartbeat_loop(job_id: str, kind: str, label: str) -> None:
    """Периодически озвучивает что задача всё ещё идёт. Без интрузивности —
    максимум 3 напоминания, и только после 90 секунд."""
    try:
        await asyncio.sleep(_FIRST_HEARTBEAT_SEC)
        for i in range(_HEARTBEAT_MAX):
            phrase = _HEARTBEAT_PHRASES[min(i, len(_HEARTBEAT_PHRASES) - 1)]
            try:
                from gateway.platforms.phone_bridge import bridge
                if bridge.is_connected():
                    await bridge.send_command("notify_voice", {
                        "text": f"{phrase} — {label[:40]}",
                        "task_id": job_id,
                        "kind": kind,
                        "is_heartbeat": True,
                    }, timeout=5)
            except Exception as e:
                logger.debug("heartbeat send failed: %s", e)
            await asyncio.sleep(_HEARTBEAT_INTERVAL_SEC)
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.debug("heartbeat loop error: %s", e)


async def _on_finish(job_id: str, kind: str, session_id: Optional[str], label: str, result: Dict[str, Any]) -> None:
    """Уведомить телефон голосом + инжектить в историю сессии."""
    text = (result.get("say_to_user") or "").strip()
    if not text:
        text = f"Готово: {label}." if result.get("ok") else f"Не получилось: {label}."

    # 1. Голосовое уведомление на телефон
    try:
        from gateway.platforms.phone_bridge import bridge
        if bridge.is_connected():
            await bridge.send_command("notify_voice", {
                "text": text,
                "task_id": job_id,
                "kind": kind,
                "next_action_hint": result.get("next_action_hint"),
            }, timeout=10)
    except Exception as e:
        logger.warning("notify_voice failed: %s", e)

    # 2. Инжект в session history (для следующего turn LLM)
    if session_id:
        try:
            from hermes_state import SessionDB
            db = SessionDB()
            # ВАЖНО: уведомление пользователю УЖЕ озвучено через notify_voice.
            # Тройка не должна дублировать. Это сообщение — справка для контекста.
            sys_msg = (
                f"[BG_TASK_COMPLETED already announced to user via TTS] "
                f"task_id={job_id} kind={kind} "
                f"status={'ok' if result.get('ok') else 'failed'}. "
                f"What user heard: \"{text}\". "
                f"Do NOT re-announce. Use this info only if user asks follow-up."
            )
            if result.get("workspace"):
                sys_msg += f" workspace={result['workspace']}"
            if result.get("next_action_hint"):
                sys_msg += f" next_action_hint={result['next_action_hint']}"
            db.append_message(session_id=session_id, role="system", content=sys_msg)
            logger.info("injected completion of %s into session %s", job_id, session_id)
        except Exception as e:
            logger.warning("session injection failed for %s: %s", job_id, e)


def get_status(job_id: str) -> Optional[Dict[str, Any]]:
    return _get(job_id)


def list_active(session_id: Optional[str] = None) -> List[Dict[str, Any]]:
    return _list_active(session_id)


def list_recent(session_id: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
    return _list_recent(session_id, limit)


def active_count() -> int:
    return len(_list_active())


def cancel(job_id: str) -> bool:
    task = _active_tasks.get(job_id)
    if task and not task.done():
        task.cancel()
        _update(job_id, status="cancelled", finished_at=time.time())
        return True
    return False


# ---------------------------------------------------------------------------
# Watchdog: ловит зависшие задачи (worker висит в await — например на subprocess
# который не закрывает пайпы на Windows). Принудительно помечает failed и
# уведомляет пользователя голосом.
# ---------------------------------------------------------------------------

_watchdog_started = False


async def _watchdog_loop() -> None:
    """Гоняется вечно. Любая ошибка ловится — loop не падает."""
    while True:
        try:
            await _watchdog_tick()
        except Exception as e:
            logger.warning("watchdog loop error: %s", e)
        try:
            await asyncio.sleep(_WATCHDOG_INTERVAL)
        except asyncio.CancelledError:
            logger.info("watchdog cancelled")
            return


async def _watchdog_tick() -> None:
    now = time.time()
    with _db() as c:
        # Берём все running и фильтруем по per-job timeout (из payload).
        rows = c.execute(
            "SELECT id, kind, session_id, short_label, started_at, payload_json "
            "FROM jobs WHERE status='running' AND started_at IS NOT NULL"
        ).fetchall()
    for r in rows:
        job_id = r["id"]
        age = int(now - (r["started_at"] or now))
        limit = _effective_timeout(r["payload_json"])
        if age < limit:
            continue  # ещё в пределах своего таймаута
        logger.warning("watchdog: job %s stuck for %ds, force-failing", job_id, age)
        _update(job_id, status="failed",
                error=f"watchdog_timeout after {age}s",
                finished_at=now)
        # Жёстко отменяем worker task — если он держит await на закрытом пайпе
        t = _active_tasks.pop(job_id, None)
        if t and not t.done():
            t.cancel()
            # ждём отмены чтобы semaphore освободился
            try:
                await asyncio.wait_for(asyncio.shield(t), timeout=2)
            except Exception:
                pass
        # Уведомляем пользователя
        label = r["short_label"] or r["kind"]
        fake_result = {
            "ok": False,
            "error": "watchdog_timeout",
            "say_to_user": f"Задача '{label}' не успела за {max(1, age // 60)} минут. Отменил.",
        }
        try:
            await _on_finish(job_id, r["kind"], r["session_id"], label, fake_result)
        except Exception as e:
            logger.warning("watchdog: _on_finish failed: %s", e)


def cleanup_orphan_jobs() -> int:
    """При старте gateway: все running-задачи без активного worker'а — сироты.
    Помечаем failed. Вызывается из api_server при init."""
    _ensure_db()
    n = 0
    with sqlite3.connect(_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, kind, short_label FROM jobs WHERE status='running'").fetchall()
        for r in rows:
            if r["id"] not in _active_tasks:
                conn.execute(
                    "UPDATE jobs SET status=?, error=?, finished_at=? WHERE id=?",
                    ("failed", "orphan_after_gateway_restart", time.time(), r["id"]),
                )
                n += 1
        conn.commit()
    if n:
        logger.info("cleaned up %d orphan jobs from previous gateway run", n)
    return n


def ensure_watchdog_started() -> None:
    """Идемпотентный старт watchdog. Вызывается при первом submit()."""
    global _watchdog_started
    if _watchdog_started:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _watchdog_started = True
    loop.create_task(_watchdog_loop())
    logger.info("job_runner watchdog started (interval=%ds, hard_timeout=%ds)",
                _WATCHDOG_INTERVAL, _HARD_TIMEOUT_SEC)
