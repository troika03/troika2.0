"""
self_improve_watcher — отдельный detached процесс, страхующий «перепрыгивание».

Запускается из self_improve_verify._trigger_restart_and_healthcheck ПЕРЕД тем, как
боевая gateway перезапустится на новом коде. Поскольку gateway перезапускает сам себя,
проверять «поднялась ли она здоровой» должен кто-то снаружи — это и есть watcher.

Логика:
  1. Дать боевой gateway время рестартануть.
  2. Пуллить http://127.0.0.1:8642/health/detailed.
  3. Если за таймаут НЕ стала здоровой → git revert <merge_commit> на main, снова
     перезапустить gateway (уже на откаченном, заведомо рабочем коде), озвучить Мише.
  4. Если здорова → записать live_ok в proposal, тихо выйти.

Аргументы: argv[1]=merge_commit, argv[2]=proposal_id.

Этот файл матчит _FORBIDDEN_PATTERNS (tools/self_improve*) — Тройка не может его
переписать через предложение.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TROIKA_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".troika"))
_PROPOSALS_DIR = _TROIKA_HOME / "proposals"

LIVE_HOST = "127.0.0.1"
LIVE_PORT = 8642
HEALTH_URL = f"http://{LIVE_HOST}:{LIVE_PORT}/health/detailed"

RESTART_GRACE_SEC = 8        # дать боевой выйти/подняться прежде чем начать пуллить
HEALTH_TIMEOUT_SEC = 40      # сколько ждём здоровья после прыжка
POLL_INTERVAL = 1.5


def _log(msg: str) -> None:
    print(f"[watcher {time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _health_ok() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=2.0) as r:
            if r.status != 200:
                return False
            data = json.loads(r.read().decode("utf-8", "replace"))
            if data.get("status") != "ok":
                return False
            state = data.get("gateway_state")
            # None допускаем (старая сборка), явный сбойный — нет.
            if state in ("error", "crashed", "stopped"):
                return False
            return True
    except Exception:
        return False


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(_REPO_ROOT), check=check,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )


def _restart_gateway() -> None:
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
    try:
        subprocess.Popen(
            [sys.executable, str(_REPO_ROOT / "cli.py"), "--gateway", "--replace"],
            cwd=str(_REPO_ROOT), env=os.environ.copy(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags, close_fds=True,
        )
    except Exception as e:
        _log(f"restart spawn failed: {e}")


def _notify_voice(text: str) -> None:
    """Best-effort голосовое уведомление через тот же HTTP-интерфейс боевой gateway.
    Если не вышло — не критично, статус всё равно в proposal JSON."""
    # Watcher живёт вне event-loop боевой; шлём через notify-эндпоинт если есть.
    # Фолбэк: просто лог. (Телефон в любом случае увидит результат при следующем turn.)
    _log(f"NOTIFY: {text}")


def _update_proposal(pid: str, **fields) -> None:
    try:
        path = _PROPOSALS_DIR / f"{pid}.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(fields)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        _log(f"update proposal failed: {e}")


def main() -> int:
    if len(sys.argv) < 3:
        _log("usage: self_improve_watcher.py <merge_commit> <proposal_id>")
        return 2
    merge_commit = sys.argv[1]
    pid = sys.argv[2]
    _log(f"watching switch: commit={merge_commit[:8]} proposal={pid}")

    time.sleep(RESTART_GRACE_SEC)

    deadline = time.time() + HEALTH_TIMEOUT_SEC
    healthy = False
    while time.time() < deadline:
        if _health_ok():
            healthy = True
            break
        time.sleep(POLL_INTERVAL)

    if healthy:
        _log("live gateway healthy after switch ✓")
        _update_proposal(pid, live_ok_at=time.time(), status="applied")
        return 0

    # ── Беда: новый код не поднялся здоровым → откат ──
    _log("live gateway NOT healthy → reverting")
    rev = _git("revert", "--no-edit", merge_commit)
    if rev.returncode != 0:
        _log(f"git revert failed: {rev.stderr[:300]}")
        _update_proposal(pid, status="revert_failed",
                         revert_error=rev.stderr[:300])
        _notify_voice(
            f"Беда: новая версия не запустилась, и откатить автоматически не вышло. "
            f"Нужна твоя помощь, Миша — git revert {merge_commit[:8]} вручную."
        )
        return 1

    revert_commit = _git("rev-parse", "HEAD").stdout.strip()
    _log(f"reverted as {revert_commit[:8]}, restarting on good code")
    _update_proposal(pid, status="reverted", revert_commit=revert_commit)
    _restart_gateway()
    _notify_voice(
        "Ой — новая версия не поднялась, я откатилась на прежний рабочий код. "
        "Ничего не сломалось, просто это изменение отменено."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
