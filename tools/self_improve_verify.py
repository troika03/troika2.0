"""
self_improve_verify — слой ПРОВЕРКИ и БЕЗОПАСНОГО ПЕРЕКЛЮЧЕНИЯ для самоулучшения Тройки.

Идея Миши («у Тройки вторая копия; добавил инструмент → проверил в копии → если
работает, перепрыгнул на неё») реализована БЕЗ вечно-живой второй копии, потому что
хот-релоада инструментов в Hermes нет (registry.discover_builtin_tools() импортирует
tools/*.py только на старте — новый tool виден LLM лишь после перезапуска процесса).

Поэтому:
  • «Вторая копия» = ОДНОРАЗОВАЯ green-песочница: git worktree на ветке предложения,
    headless-gateway на ДРУГОМ HERMES_HOME + ДРУГОМ порту (8652). Поднимается только
    чтобы доказать «новый код стартует + проходит тесты», затем сносится. Телефона не
    касается (порт 8652, отдельный HERMES_HOME → duplicate-instance guard разрешает
    сосуществование, см. gateway/run.py).
  • «Перепрыгивание» = squash-merge в main + перезапуск gateway. Телефон stateless,
    сам переподключается на 8642 (gateway/platforms/phone_bridge.py).
  • Безопасное (новый tool/навык/мелкая правка) — авто-применяется после проверки.
    Рискованное (память/сеть/деньги/ядро) — всегда требует голосового «да» Миши.
  • После перезапуска — health-check; если gateway не поднялся, отдельный detached
    health-watcher делает git revert и поднимает старый код. Это сеть под принятым
    Мишей слепым пятном «import+тесты прошли, но tool врёт в рантайме».

ВАЖНО: этот модуль входит в _FORBIDDEN_PATTERNS (tools/self_improve*) — Тройка не может
изменить сам движок проверки/переключения через предложение. Несгораемый якорь.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple  # noqa: F401 — Tuple используется в _SEED_FORBIDDEN_PREFIXES

# Переиспользуем готовые хелперы движка предложений — не дублируем git/subprocess.
from tools.self_improve_tool import (
    _git,
    _REPO_ROOT,
    _TROIKA_HOME,
    _save_proposal,
    _load_proposal,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы green-песочницы
# ---------------------------------------------------------------------------

# Отдельный HERMES_HOME → PID-файл gateway scoped к нему → duplicate-instance guard
# разрешает green-копии жить рядом с боевой (gateway/run.py:18099).
GREEN_HERMES_HOME = Path.home() / ".troika-green"
# Никогда 8642 — иначе перехватим телефон у боевой копии.
GREEN_API_PORT = 8652
GREEN_API_HOST = "127.0.0.1"
# Worktree вне репозитория, чтобы не попасть в git status боевого дерева.
WORKTREE_DIR = _REPO_ROOT.parent / ".troika-green-wt"

# Логи песочницы — с подчёркиванием → попадают под gitignore (_*.log).
_GREEN_OUT_LOG = _REPO_ROOT / "_green_gateway.log"
_GREEN_ERR_LOG = _REPO_ROOT / "_green_gateway.err"

# Лок против параллельных self-improve прогонов (green порт/home — синглтоны).
_VERIFY_LOCK = _TROIKA_HOME / "verify.lock"
_VERIFY_LOCK_STALE_SEC = 1800  # 30 мин: считаем лок протухшим (краш не снял)

_BOOT_HEALTH_TIMEOUT = 90      # сколько ждём что green-gateway ответит на /health
# (30с не хватало на cold-start Windows: gateway импортит tools/skills/LLM-клиент
# ~40-60с до бинда api_server; 90с — с запасом)
_IMPORT_SMOKE_TIMEOUT = 60
_PYTEST_TIMEOUT = 240          # общий бюджет на scoped pytest
_POST_SWITCH_HEALTH_TIMEOUT = 40  # сколько watcher ждёт боевую копию после прыжка

# LIVE ~/.troika/.env содержит ключи (OPENROUTER/GROQ/…) без которых gateway
# висит на инициализации LLM-клиента и api_server никогда не биндится. Пустой
# green-HERMES_HOME + не-инициированный os.environ = точно эта ситуация. Поэтому
# seed'им .env копией родительского с фильтром платформенных токенов.
_SEED_FORBIDDEN_PREFIXES: Tuple[str, ...] = (
    "TELEGRAM_", "DISCORD_", "SLACK_", "WHATSAPP_", "TWITTER_", "MATRIX_",
    "SIGNAL_", "SMS_", "TWILIO_",
    "API_SERVER_",  # свои ставим через env-vars _green_env → задают порт/host/key
    "STT_",         # STT в песочнице не нужен — не даём ему стартовать/конфликтовать
    "WEBHOOK_",     # webhook-платформа в green не нужна
    "TERMINAL_",    # чтобы не тащить TERMINAL_CWD/TERMINAL_ENV из боевого профиля
    "MESSAGING_",   # deprecated MESSAGING_CWD и т.п.
)


# ---------------------------------------------------------------------------
# B. Классификатор риска
# ---------------------------------------------------------------------------

# Пути/имена, прикосновение к которым = рискованно (требует голосового «да»).
# Запретные пути (gateway/cli/registry/...) уже жёстко режутся ВЫШЕ в
# self_improve_tool._validate_diff — здесь только разбивка safe vs risky внутри
# уже-разрешённого множества.
_RISKY_RE = re.compile(
    r"(memory|vault|secret|credential|auth|token|network|http|request|"
    r"quota|billing|money|payment|registry|job_runner|session|state\.py|"
    r"\.env|config)",
    re.IGNORECASE,
)

# Что считаем «безопасной зоной» по расположению файла.
_SAFE_DIR_RE = re.compile(r"^(tools/|skills/)")
_DOC_RE = re.compile(r"\.(md|markdown|txt)$", re.IGNORECASE)

# Порог «малой правки» существующего файла, выше которого — risky из осторожности.
_SMALL_EDIT_LINES = 60


def _count_changed_lines(diff_text: str) -> int:
    n = 0
    for ln in diff_text.splitlines():
        if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---")):
            n += 1
    return n


def classify_risk(changed_files: List[str], diff_text: str) -> Dict[str, Any]:
    """Возвращает {"risk": "safe"|"risky", "reasons": [...]}.

    SAFE — каждый файл лежит в tools/ или skills/ (или это документация) И не матчит
    risky-regex, И суммарная правка невелика. RISKY — иначе. При сомнении → risky.
    """
    reasons: List[str] = []
    if not changed_files:
        return {"risk": "risky", "reasons": ["no_files"]}

    risky = False
    for f in changed_files:
        fn = f.replace("\\", "/")
        if _RISKY_RE.search(fn):
            risky = True
            reasons.append(f"risky_path:{fn}")
            continue
        if _DOC_RE.search(fn):
            continue  # доки всегда безопасны
        if not _SAFE_DIR_RE.match(fn):
            risky = True
            reasons.append(f"outside_safe_dirs:{fn}")

    total = _count_changed_lines(diff_text)
    if total > _SMALL_EDIT_LINES:
        # Новый файл целиком может быть большим и при этом безопасным, но крупная
        # правка СУЩЕСТВУЮЩЕГО кода — повод показать Мише. Дешевле перестраховаться.
        existing_edit = any(
            not _is_new_file(f, diff_text) for f in changed_files
        )
        if existing_edit:
            risky = True
            reasons.append(f"large_edit:{total}_lines")

    if not risky:
        reasons.append("safe: new tool/skill/doc, small footprint")
    return {"risk": "risky" if risky else "safe", "reasons": reasons}


def _is_new_file(path: str, diff_text: str) -> bool:
    """Грубая эвристика: в diff есть 'new file mode' для этого пути."""
    norm = path.replace("\\", "/")
    return f"new file mode" in diff_text and norm in diff_text and (
        re.search(rf"diff --git a/{re.escape(norm)} .*?\nnew file mode", diff_text)
        is not None
    )


# ---------------------------------------------------------------------------
# Лок
# ---------------------------------------------------------------------------

def _acquire_lock() -> bool:
    try:
        _TROIKA_HOME.mkdir(parents=True, exist_ok=True)
        if _VERIFY_LOCK.exists():
            age = time.time() - _VERIFY_LOCK.stat().st_mtime
            if age < _VERIFY_LOCK_STALE_SEC:
                return False
            # протух — перехватываем
        _VERIFY_LOCK.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except Exception as e:
        logger.warning("verify lock acquire failed: %s", e)
        return False


def _release_lock() -> None:
    try:
        _VERIFY_LOCK.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# A. Green-песочница: worktree → boot → health → tests → teardown
# ---------------------------------------------------------------------------

def _make_worktree(branch: str) -> Path:
    """Создаёт git worktree на указанной ветке. Чистит прошлую песочницу."""
    _remove_worktree(WORKTREE_DIR)
    _git("worktree", "prune", check=False)
    _git("worktree", "add", "--force", str(WORKTREE_DIR), branch)
    return WORKTREE_DIR


def _remove_worktree(path: Path) -> None:
    try:
        if path.exists():
            _git("worktree", "remove", "--force", str(path), check=False)
    except Exception:
        pass
    # На случай если git не смог — добиваем вручную, потом prune.
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
    try:
        _git("worktree", "prune", check=False)
    except Exception:
        pass


def _green_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["HERMES_HOME"] = str(GREEN_HERMES_HOME)
    # api_server включается флагом API_SERVER_ENABLED — без него gateway стартует, но
    # не биндит HTTP, и /health никогда не отвечает (booted=False). Это и есть «копия,
    # которую проверяем»: только api_server на 8652, без телефона/Telegram.
    env["API_SERVER_ENABLED"] = "true"
    env["API_SERVER_PORT"] = str(GREEN_API_PORT)
    env["API_SERVER_HOST"] = GREEN_API_HOST
    env["API_SERVER_KEY"] = "green-sandbox"
    env["HERMES_GREEN_SANDBOX"] = "1"
    env["HERMES_QUIET"] = "1"
    # STT в песочнице не нужен — не даём ему стартовать/конфликтовать.
    env.pop("STT_PROXY_PORT", None)
    env.pop("STT_BACKEND", None)
    # Телефон/Telegram токены боевой копии в песочницу не тащим — green не должен
    # подключаться к платформам, только api_server.
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS",
              "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "WHATSAPP_TOKEN"):
        env.pop(k, None)
    # TERMINAL_CWD/MESSAGING_CWD из родительского окружения — их fallback в
    # gateway/run.py:1012 сработает и подставит правильное значение из green home.
    # Если оставить унаследованный worktree-путь — сработает deprecation-warning
    # (косметика, но шумит в логах).
    env.pop("TERMINAL_CWD", None)
    env.pop("MESSAGING_CWD", None)
    return env


def _seed_green_env_file() -> None:
    """Скопировать ключи из LIVE ~/.troika/.env в свежий ~/.troika-green/.env,
    отфильтровав платформенные токены (иначе green подключится к боевому Telegram),
    API_SERVER_* (их задаём через env-vars) и TERMINAL_*/STT_*/WEBHOOK_*/MESSAGING_*
    (deprecated, дублирует ложные warning'и и/или конфликтует с песочницей).

    Без seed'а: пустой .env → нет OPENROUTER/GROQ ключа → gateway висит на init
    LLM-клиента → api_server никогда не биндится → verify falses out."""
    live_home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".troika"))
    src = live_home / ".env"
    dst = GREEN_HERMES_HOME / ".env"
    if not src.exists() or src.resolve() == dst.resolve():
        return
    try:
        raw = src.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("seed green .env: cannot read %s: %s", src, e)
        return
    kept: List[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            # комментарии/пустые не тащим — только реальные ключи
            continue
        key = s.split("=", 1)[0].strip()
        if any(key.startswith(p) for p in _SEED_FORBIDDEN_PREFIXES):
            continue
        kept.append(line)
    try:
        dst.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    except Exception as e:
        logger.warning("seed green .env: cannot write %s: %s", dst, e)


def _reset_green_home() -> None:
    """Свежий HERMES_HOME с засеянным .env — нет токенов телефона/Telegram, биндится
    только api_server, но LLM-ключи из боевого профиля пробрасываются, иначе green
    висит на init LLM."""
    try:
        if GREEN_HERMES_HOME.exists():
            shutil.rmtree(GREEN_HERMES_HOME, ignore_errors=True)
        GREEN_HERMES_HOME.mkdir(parents=True, exist_ok=True)
        _seed_green_env_file()
    except Exception as e:
        logger.warning("reset green home failed: %s", e)


def _boot_green(worktree: Path) -> Optional[subprocess.Popen]:
    """Стартует headless-gateway green-копии. Логи в ФАЙЛ, не PIPE
    (windows-subprocess-no-pipe → иначе buffer-deadlock)."""
    _reset_green_home()
    cli = worktree / "cli.py"
    if not cli.exists():
        logger.error("green boot: cli.py not found in worktree %s", worktree)
        return None
    args = [sys.executable, str(cli), "--gateway"]
    try:
        f_out = open(_GREEN_OUT_LOG, "wb")
        f_err = open(_GREEN_ERR_LOG, "wb")
    except Exception as e:
        logger.error("green boot: cannot open log files: %s", e)
        return None
    try:
        proc = subprocess.Popen(
            args, cwd=str(worktree), env=_green_env(),
            stdout=f_out, stderr=f_err,
        )
    except Exception as e:
        f_out.close(); f_err.close()
        logger.error("green boot spawn failed: %s", e)
        return None
    # Дескрипторы держит дочерний процесс; нам они больше не нужны.
    f_out.close(); f_err.close()
    return proc


def _http_health_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            if r.status != 200:
                return False
            data = json.loads(r.read().decode("utf-8", "replace"))
            return data.get("status") == "ok"
    except Exception:
        return False


def _probe_health(proc: subprocess.Popen, timeout_s: int = _BOOT_HEALTH_TIMEOUT) -> bool:
    """booted = процесс жив И /health отвечает ok в пределах таймаута."""
    url = f"http://{GREEN_API_HOST}:{GREEN_API_PORT}/health"
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return False  # упал на старте
        if _http_health_ok(url):
            return True
        time.sleep(0.5)
    return False


def _kill_proc(proc: Optional[subprocess.Popen]) -> None:
    if proc is None:
        return
    try:
        if proc.poll() is None:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                capture_output=True, timeout=15,
            )
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def _touched_tool_modules(changed_files: List[str]) -> List[str]:
    mods = []
    for f in changed_files:
        fn = f.replace("\\", "/")
        m = re.match(r"^tools/([A-Za-z_][A-Za-z0-9_]*)\.py$", fn)
        if m:
            mods.append(f"tools.{m.group(1)}")
    return mods


def _pytest_k_from_files(changed_files: List[str]) -> Optional[str]:
    """Из tools/foo_tool.py → ключевое слово 'foo' для pytest -k. None если не вывелось."""
    keys = []
    for f in changed_files:
        fn = f.replace("\\", "/")
        m = re.match(r"^tools/([A-Za-z0-9_]+?)(_tool)?\.py$", fn)
        if m:
            keys.append(m.group(1))
    if not keys:
        return None
    # уникальные, OR-объединение для -k
    seen = []
    for k in keys:
        if k not in seen:
            seen.append(k)
    return " or ".join(seen)


def _run_scoped_tests(worktree: Path, changed_files: List[str]) -> Dict[str, Any]:
    """import-smoke на затронутые tools-модули + scoped pytest. Никогда не весь suite."""
    env = _green_env()
    result: Dict[str, Any] = {"import_ok": True, "tests_ok": True, "details": {}}

    # 1. import-smoke
    mods = _touched_tool_modules(changed_files)
    for mod in mods:
        try:
            p = subprocess.run(
                [sys.executable, "-c", f"import {mod}"],
                cwd=str(worktree), env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=_IMPORT_SMOKE_TIMEOUT,
            )
            if p.returncode != 0:
                result["import_ok"] = False
                result["details"][f"import:{mod}"] = (p.stderr or p.stdout)[-600:]
        except subprocess.TimeoutExpired:
            result["import_ok"] = False
            result["details"][f"import:{mod}"] = "timeout"
        except Exception as e:
            result["import_ok"] = False
            result["details"][f"import:{mod}"] = f"spawn_error: {e}"

    # 2. scoped pytest (только если import прошёл — иначе бессмысленно)
    kexpr = _pytest_k_from_files(changed_files)
    tests_dir = worktree / "tests" / "tools"
    if result["import_ok"] and kexpr and tests_dir.exists():
        args = [
            sys.executable, "-m", "pytest", "tests/tools",
            "-k", kexpr, "-q",
            "--timeout=30", "--timeout-method=thread",
            "-p", "no:cacheprovider",
        ]
        try:
            p = subprocess.run(
                args, cwd=str(worktree), env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=_PYTEST_TIMEOUT,
            )
            tail = (p.stdout or "")[-1500:]
            # rc 5 = «не собрано ни одного теста под -k» → не провал, просто нет покрытия.
            if p.returncode == 5 or "no tests ran" in tail.lower():
                result["details"]["pytest"] = "no_scoped_tests"
            elif p.returncode != 0:
                result["tests_ok"] = False
                result["details"]["pytest"] = tail
            else:
                result["details"]["pytest"] = "passed"
        except subprocess.TimeoutExpired:
            result["tests_ok"] = False
            result["details"]["pytest"] = "timeout"
        except Exception as e:
            result["tests_ok"] = False
            result["details"]["pytest"] = f"spawn_error: {e}"
    else:
        result["details"]["pytest"] = "no_scoped_tests"

    return result


async def verify_proposal(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Полный цикл проверки предложения в green-песочнице.

    Возвращает {booted, health_ok, tests_ok, import_ok, details}. Teardown гарантирован
    (finally): green-процесс убит, worktree снесён, GREEN_HERMES_HOME очищен.
    """
    branch = proposal.get("branch")
    changed_files = proposal.get("files", []) or []
    verdict: Dict[str, Any] = {
        "booted": False, "health_ok": False,
        "tests_ok": False, "import_ok": False, "details": {},
    }
    if not branch:
        verdict["details"]["error"] = "no_branch"
        return verdict

    proc: Optional[subprocess.Popen] = None
    worktree: Optional[Path] = None
    loop = asyncio.get_event_loop()
    try:
        worktree = await loop.run_in_executor(None, _make_worktree, branch)

        proc = await loop.run_in_executor(None, _boot_green, worktree)
        if proc is None:
            verdict["details"]["error"] = "boot_spawn_failed"
            return verdict

        health = await loop.run_in_executor(None, _probe_health, proc)
        verdict["booted"] = health
        verdict["health_ok"] = health
        if not health:
            # Лог-хвост в детали — поможет понять, почему не стартовал.
            try:
                tail = _GREEN_ERR_LOG.read_text("utf-8", "replace")[-800:]
                verdict["details"]["boot_err_tail"] = tail
            except Exception:
                pass
            return verdict

        tres = await loop.run_in_executor(None, _run_scoped_tests, worktree, changed_files)
        verdict["import_ok"] = tres["import_ok"]
        verdict["tests_ok"] = tres["tests_ok"]
        verdict["details"].update(tres["details"])
        return verdict
    except Exception as e:
        verdict["details"]["error"] = f"{type(e).__name__}: {e}"
        return verdict
    finally:
        await loop.run_in_executor(None, _kill_proc, proc)
        if worktree is not None:
            await loop.run_in_executor(None, _remove_worktree, worktree)
        try:
            await loop.run_in_executor(
                None, lambda: shutil.rmtree(GREEN_HERMES_HOME, ignore_errors=True)
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# E. Перезапуск + health-watcher (detached, переживает рестарт)
# ---------------------------------------------------------------------------

def _spawn_health_watcher(merge_commit: str, proposal_id: str) -> bool:
    """Запускает ОТДЕЛЬНЫЙ detached процесс, который переживёт перезапуск gateway,
    дождётся боевой /health/detailed и при неудаче сделает git revert + поднимет старый
    код. Логику нельзя держать в самом gateway — он себя перезапускает."""
    watcher = _REPO_ROOT / "tools" / "self_improve_watcher.py"
    if not watcher.exists():
        logger.warning("health watcher script missing: %s", watcher)
        return False
    try:
        flags = 0
        if os.name == "nt":
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP — переживёт смерть родителя.
            flags = 0x00000008 | 0x00000200
        log = _REPO_ROOT / "_self_improve_watcher.log"
        f = open(log, "ab")
        subprocess.Popen(
            [sys.executable, str(watcher), merge_commit, proposal_id],
            cwd=str(_REPO_ROOT), stdout=f, stderr=f,
            creationflags=flags, close_fds=True,
        )
        f.close()
        return True
    except Exception as e:
        logger.warning("spawn health watcher failed: %s", e)
        return False


def _trigger_gateway_restart() -> bool:
    """Просит боевую gateway перезапуститься на новом коде (start_gateway(replace=True)).
    Телефон stateless — переподключится на 8642 сам. Если боевая не запущена, no-op:
    keep-alive поднимет новый код при следующем цикле."""
    try:
        # `python cli.py --gateway --replace` атомарно заменяет текущий инстанс.
        flags = 0
        if os.name == "nt":
            flags = 0x00000008 | 0x00000200  # detached
        subprocess.Popen(
            [sys.executable, str(_REPO_ROOT / "cli.py"), "--gateway", "--replace"],
            cwd=str(_REPO_ROOT), env=os.environ.copy(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags, close_fds=True,
        )
        return True
    except Exception as e:
        logger.warning("trigger restart failed: %s", e)
        return False


def _trigger_restart_and_healthcheck(merge_commit: str, proposal_id: str) -> Dict[str, Any]:
    """Запускает detached health-watcher (он сделает revert при беде), затем просит
    gateway перезапуститься. Возврат — что инициировано, не финальный исход (исход
    озвучит сам watcher через notify_voice)."""
    watcher_ok = _spawn_health_watcher(merge_commit, proposal_id)
    restart_ok = _trigger_gateway_restart()
    return {"watcher_spawned": watcher_ok, "restart_triggered": restart_ok}


# ---------------------------------------------------------------------------
# C. Оркестратор: проверить → классифицировать → (авто-применить | оставить pending)
# ---------------------------------------------------------------------------

async def verify_classify_and_maybe_apply(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Вызывается из self_improve_tool._handle_propose после создания proposal.

    Возвращает обогащённый словарь с risk/verify/auto_applied и say_to_user.
    """
    pid = proposal.get("id")
    changed_files = proposal.get("files", []) or []
    diff_text = proposal.get("diff_preview", "") or ""

    if not _acquire_lock():
        return {
            "auto_applied": False, "needs_approval": True,
            "verify_skipped": "busy",
            "say_to_user": f"Предложение {pid} готово, но сейчас идёт другая проверка. "
                           f"Скажи «применить {pid}» когда захочешь.",
        }

    try:
        risk = classify_risk(changed_files, diff_text)
        verdict = await verify_proposal(proposal)

        # Сохраняем результаты в proposal JSON.
        fresh = _load_proposal(pid) or proposal
        fresh["risk"] = risk
        fresh["verify"] = verdict
        passed = bool(
            verdict.get("booted") and verdict.get("health_ok")
            and verdict.get("tests_ok") and verdict.get("import_ok")
        )

        if risk["risk"] == "safe" and passed:
            # АВТО-ПРИМЕНЕНИЕ: merge → main, затем перезапуск + watcher.
            from tools.self_improve_tool import _handle_approve
            appr = await _handle_approve({"proposal_id": pid})
            if not appr.get("ok"):
                fresh["auto_applied"] = False
                fresh["details_apply"] = appr
                _save_proposal(fresh)
                return {
                    "auto_applied": False, "needs_approval": True,
                    "risk": risk, "verify": verdict,
                    "say_to_user": f"Проверила предложение {pid} — код рабочий, но "
                                   f"применить автоматически не вышло ({appr.get('error')}). "
                                   f"Скажи «применить {pid}».",
                }
            merge_commit = appr.get("merge_commit", "")
            fresh["auto_applied"] = True
            fresh["merge_commit"] = merge_commit
            fresh["auto_applied_at"] = time.time()
            _save_proposal(fresh)

            switch = _trigger_restart_and_healthcheck(merge_commit, pid)
            fresh["switch"] = switch
            _save_proposal(fresh)

            desc = (proposal.get("description") or "изменение")[:50]
            return {
                "auto_applied": True, "needs_approval": False,
                "risk": risk, "verify": verdict,
                "merge_commit": merge_commit,
                "say_to_user": f"Готово: {desc}. Проверила в песочнице — работает, "
                               f"применила и перезапускаюсь на новой версии. "
                               f"Если что-то не так — скажи «откати {pid}».",
            }

        # Не безопасно ИЛИ не прошло проверку → оставляем pending, просим Мишу.
        _save_proposal(fresh)
        if not passed:
            why = "не прошло проверку в песочнице"
            if not verdict.get("booted"):
                why = "новый код не запустился"
            elif not verdict.get("import_ok"):
                why = "ошибка импорта в новом коде"
            elif not verdict.get("tests_ok"):
                why = "упали тесты"
            return {
                "auto_applied": False, "needs_approval": True,
                "risk": risk, "verify": verdict,
                "say_to_user": f"Предложение {pid} {why}. Не применяю. "
                               f"Скажи «покажи предложение {pid}» чтобы разобраться.",
            }
        # passed, но risky
        return {
            "auto_applied": False, "needs_approval": True,
            "risk": risk, "verify": verdict,
            "say_to_user": f"Предложение {pid} проверила — код рабочий, но оно затрагивает "
                           f"чувствительное ({', '.join(risk['reasons'][:2])}). "
                           f"Сам реши: «применить {pid}» или «покажи предложение {pid}».",
        }
    finally:
        _release_lock()
