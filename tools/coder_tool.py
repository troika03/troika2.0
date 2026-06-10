"""
coder_tool — делегирование кодинга альтернативным CLI-кодерам с входом по аккаунту:

  • claude_code — Claude Code CLI (подписка Claude, OAuth). ОСНОВНОЙ кодер: сильнее
    Gemini на коде, не страдает «Invalid stream». Headless: claude -p ... acceptEdits.
  • qwen_code  — Qwen Code CLI (Qwen-аккаунт, бесплатный free-tier OAuth ~2000/день).
    Форк Gemini-CLI; запасной кодер на случай лимитов Gemini/Claude.

Оба пишут проект в свежий workspace под ~/.troika/workspaces/, как gemini_code, и
переиспользуют его хелперы (_find_cli, _list_files, _zip_workspace, _HEADLESS_RULES,
_WORKSPACES). Это НЕ дублирует gemini_code — только добавляет два движка с тем же UX
(файлы + ZIP на телефон), не трогая рабочий gemini_code.

State последнего workspace общий с gemini_code (_save_last), поэтому iterate/preview
из gemini_code продолжают работать с проектом, который сделал claude/qwen.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from tools.registry import registry

# Переиспользуем хелперы gemini_code — единый источник правды по workspace/zip/правилам.
from tools.gemini_code_tool import (
    _find_cli,
    _list_files,
    _zip_workspace,
    _HEADLESS_RULES,
    _WORKSPACES,
    _slugify,
    _save_last,
    _send_zip_to_phone,
)

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 600  # кодеры по подписке думают дольше, но качественнее

# Признак того, что модель оборвалась на нестабильности (не сеть/квота).
_MALFORMED_RE = re.compile(r"Invalid stream|malformed tool call|empty response", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Описание бэкендов: как звать CLI и как он принимает headless-задачу
# ---------------------------------------------------------------------------

def _claude_args(cli: str, prompt_file: Path) -> list[str]:
    # Claude Code headless: -p печатает ответ и выходит; acceptEdits авто-применяет
    # правки файлов без интерактивных подтверждений. Промпт даём через stdin (надёжнее
    # длинных cmdline на Windows) — здесь возвращаем базовые флаги, текст пойдёт в stdin.
    return [cli, "-p", "--permission-mode", "acceptEdits",
            "--dangerously-skip-permissions"]


def _qwen_args(cli: str, prompt_file: Path) -> list[str]:
    # Qwen Code — форк Gemini-CLI: те же флаги. --yolo авто-аппрув, без MCP для скорости.
    return [cli, "--yolo", "--allowed-mcp-server-names", "__none__", "--prompt", "@" + str(prompt_file)]


_BACKENDS = {
    "claude": {
        "cli_name": "claude",
        "env_path": "CLAUDE_CLI_PATH",
        "build_args": _claude_args,
        "stdin_prompt": True,   # промпт через stdin
        "auth_hint": "Запусти `claude` в терминале и войди по подписке.",
        "label": "Claude",
    },
    "qwen": {
        "cli_name": "qwen",
        "env_path": "QWEN_CLI_PATH",
        "build_args": _qwen_args,
        "stdin_prompt": False,  # промпт через @file
        "auth_hint": "Запусти `qwen` в терминале и войди в Qwen-аккаунт (free tier).",
        "label": "Qwen",
    },
}


def _find_backend_cli(backend: str) -> Optional[str]:
    spec = _BACKENDS[backend]
    explicit = os.environ.get(spec["env_path"], "").strip()
    if explicit and Path(explicit).exists():
        return explicit
    return _find_cli(spec["cli_name"])


# ---------------------------------------------------------------------------
# Запуск кодера в workspace (file-log, не PIPE — windows-subprocess-no-pipe)
# ---------------------------------------------------------------------------

async def _run_coder(backend: str, workspace: Path, task: str, timeout: int) -> Dict[str, Any]:
    spec = _BACKENDS[backend]
    cli = _find_backend_cli(backend)
    if not cli:
        return {"ok": False, "error": f"{backend}_cli_not_found",
                "hint": spec["auth_hint"]}

    prompt = f"{_HEADLESS_RULES}\nUSER TASK:\n{task}"
    prompt_file = workspace / ".CODE_TASK.md"
    prompt_file.write_text(prompt, encoding="utf-8")

    args = spec["build_args"](cli, prompt_file)

    env = os.environ.copy()
    # node предпочитает IPv4 — лечит висяки на IPv6-DNS без маршрута (как в gemini_code).
    env["NODE_OPTIONS"] = (env.get("NODE_OPTIONS", "") + " --dns-result-order=ipv4first").strip()

    log_out = workspace / "._coder.out"
    log_err = workspace / "._coder.err"
    logger.info("Spawning %s coder in %s", backend, workspace)

    try:
        f_out = open(log_out, "wb")
        f_err = open(log_err, "wb")
    except Exception as e:
        return {"ok": False, "error": f"cannot open log files: {e}"}

    try:
        stdin_data = prompt.encode("utf-8") if spec["stdin_prompt"] else None
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(workspace), env=env,
            stdin=asyncio.subprocess.PIPE if spec["stdin_prompt"] else asyncio.subprocess.DEVNULL,
            stdout=f_out, stderr=f_err,
        )
        try:
            if spec["stdin_prompt"]:
                # Промпт в stdin, затем ждём завершения с таймаутом.
                proc.stdin.write(stdin_data)
                await proc.stdin.drain()
                proc.stdin.close()
            rc = await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                               capture_output=True, timeout=10)
            except Exception:
                pass
            return {"ok": False, "error": f"{backend}_timeout_{timeout}s"}
        finally:
            f_out.close(); f_err.close()
    except Exception as e:
        try:
            f_out.close(); f_err.close()
        except Exception:
            pass
        return {"ok": False, "error": f"spawn failed: {e}"}

    err = log_err.read_text("utf-8", "replace") if log_err.exists() else ""
    out = log_out.read_text("utf-8", "replace") if log_out.exists() else ""
    # Чистим служебные файлы из workspace, чтобы не попали в ZIP.
    for f in (prompt_file, log_out, log_err):
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass

    malformed = bool(_MALFORMED_RE.search(err))
    if rc != 0:
        return {"ok": False, "error": f"{backend}-cli exit {rc}",
                "malformed": malformed, "err_tail": err[-400:]}
    return {"ok": True, "rc": rc, "malformed": malformed, "out_tail": out[-400:]}


# ---------------------------------------------------------------------------
# Handler: create-проект указанным кодером
# ---------------------------------------------------------------------------

async def _handle_coder(backend: str, arguments: dict) -> dict:
    task = (arguments.get("task") or "").strip()
    if not task:
        return {"ok": False, "error": "missing 'task'",
                "say_to_user": "Скажи что именно сделать."}
    timeout = int(arguments.get("timeout") or _DEFAULT_TIMEOUT)
    label = _BACKENDS[backend]["label"]

    slug = _slugify(task)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workspace = _WORKSPACES / f"{slug}-{timestamp}"
    workspace.mkdir(parents=True, exist_ok=True)

    res = await _run_coder(backend, workspace, task, timeout)
    if not res.get("ok"):
        hint = res.get("hint", "")
        say = f"{label} не справился с задачей."
        if res.get("malformed"):
            say = f"{label} оборвался на полпути, попробуй ещё раз."
        elif "not_found" in str(res.get("error", "")):
            say = f"{label} не настроен. {hint}"
        return {"ok": False, "backend": backend, "stage": f"{backend}-cli",
                "workspace": str(workspace), **res, "say_to_user": say}

    files = _list_files(workspace)
    if not files:
        return {"ok": False, "backend": backend, "workspace": str(workspace),
                "error": "no_files",
                "say_to_user": f"{label} ничего не сгенерировал."}

    _save_last(workspace)

    # ZIP + отправка на телефон (как gemini_code).
    zip_info: Dict[str, Any] = {}
    try:
        zip_name = f"{slug}-{timestamp}.zip"
        zip_path = _zip_workspace(workspace, zip_name)
        sent = await _send_zip_to_phone(zip_path, zip_name)
        zip_info = {"name": zip_name, "sent": sent.get("ok", False)}
    except Exception as e:
        logger.warning("zip/send failed: %s", e)
        zip_info = {"error": str(e)}

    say = f"Готово — {label} сделал проект, {len(files)} файлов. Скинул ZIP на телефон."
    return {"ok": True, "backend": backend, "action": "create",
            "workspace": str(workspace), "files": files[:40],
            "file_count": len(files), "zip": zip_info, "say_to_user": say}


async def _handle_claude(arguments: dict, **_kw) -> dict:
    return await _handle_coder("claude", arguments)


async def _handle_qwen(arguments: dict, **_kw) -> dict:
    return await _handle_coder("qwen", arguments)


# ---------------------------------------------------------------------------
# Schemas + registration
# ---------------------------------------------------------------------------

CLAUDE_CODE_SCHEMA = {
    "name": "claude_code",
    "description": "Делегировать кодинг-задачу Claude Code (лучший кодер, вход по подписке Claude). Используй для «сделай сайт/приложение/скрипт», когда нужно высокое качество кода. Пишет проект в workspace, шлёт ZIP на телефон. Для длинных задач лучше через job_runner (в фоне).",
    "parameters": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Что сделать. Чем конкретнее, тем лучше."},
            "timeout": {"type": "integer", "description": "Секунды до прерывания (default 600)."},
        },
        "required": ["task"],
    },
}

QWEN_CODE_SCHEMA = {
    "name": "qwen_code",
    "description": "Делегировать кодинг-задачу Qwen Code (бесплатный кодер, вход по Qwen-аккаунту, ~2000 запросов/день). Запасной вариант когда лимиты Gemini/Claude исчерпаны. Пишет проект в workspace, шлёт ZIP на телефон.",
    "parameters": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Что сделать."},
            "timeout": {"type": "integer", "description": "Секунды до прерывания (default 600)."},
        },
        "required": ["task"],
    },
}


def _check_claude() -> bool:
    return _find_backend_cli("claude") is not None


def _check_qwen() -> bool:
    return _find_backend_cli("qwen") is not None


registry.register(
    name="claude_code", toolset="claude_code",
    schema=CLAUDE_CODE_SCHEMA, handler=_handle_claude,
    check_fn=_check_claude, is_async=True, emoji="🦾",
)
registry.register(
    name="qwen_code", toolset="qwen_code",
    schema=QWEN_CODE_SCHEMA, handler=_handle_qwen,
    check_fn=_check_qwen, is_async=True, emoji="🐉",
)
