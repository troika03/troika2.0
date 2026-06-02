"""
code_review — структурированный ревью кода через Gemini CLI.

Принимает путь (файл или папка) и опциональный focus
(security, performance, style, bugs). Возвращает структурированные находки:
severity (critical|major|minor|info), категория, файл:строка, описание, fix-предложение.

Использование: «Тройка, посмотри ревью tools/job_runner.py»
или «проверь безопасность файла X».

Tool не правит код — только описывает. Если хочешь применить — используй
self_improve_propose с теми же файлами.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from tools.registry import registry

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MAX_FILE_CHARS = 30_000  # ограничение чтобы не утопить Gemini

_FOCUS_PROMPTS = {
    "security": "Сосредоточься на безопасности: command injection, path traversal, SSRF, утечки secret'ов, race conditions, незакрытые ресурсы.",
    "performance": "Сосредоточься на производительности: N+1 запросы, лишние allocations, sync-блокировки в asyncio, неоптимальные циклы, утечки памяти.",
    "style": "Сосредоточься на читаемости и стиле: длинные функции, неинформативные имена, дублирование, плохие комментарии, нарушения PEP8.",
    "bugs": "Сосредоточься на потенциальных багах: edge-cases (пустые входы, None, off-by-one), необработанные исключения, гонки, неверная логика.",
    "all": "Проведи общий ревью: критичные баги, безопасность, производительность, читаемость. Найди что важнее всего исправить.",
}


def _resolve_target(target: str) -> Path:
    p = Path(target)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return p


def _gather_files(target: Path) -> List[Path]:
    if target.is_file():
        return [target]
    if not target.is_dir():
        return []
    files = []
    for ext in (".py", ".kt", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs"):
        files.extend(target.rglob(f"*{ext}"))
    # Не лезем в node_modules, .venv, __pycache__
    blocked = {"node_modules", ".venv", "__pycache__", ".git", "build", "dist"}
    files = [f for f in files if not any(b in f.parts for b in blocked)]
    return files[:10]  # лимит чтобы не утопить Gemini


async def _run_gemini_review(prompt: str, timeout: int = 180) -> Dict[str, Any]:
    from tools.gemini_code_tool import _find_gemini_cli
    cli = _find_gemini_cli()
    if not cli:
        return {"ok": False, "error": "gemini_cli_not_found"}

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    oauth = Path.home() / ".gemini" / "oauth_creds.json"
    if not api_key and not oauth.exists():
        return {"ok": False, "error": "no_gemini_auth"}

    env = os.environ.copy()
    if api_key:
        env["GEMINI_API_KEY"] = api_key

    # Изолированный temp-dir, чтобы Gemini не лазил по репо
    with tempfile.TemporaryDirectory(prefix="troika_review_") as tmp:
        args = [cli, "--yolo", "--allowed-mcp-server-names", "__none__", "--prompt", prompt]
        log_out_path = Path(tmp) / "out.log"
        log_err_path = Path(tmp) / "err.log"
        try:
            with open(log_out_path, "wb") as f_out, open(log_err_path, "wb") as f_err:
                proc = await asyncio.create_subprocess_exec(
                    *args, cwd=tmp,
                    stdout=f_out, stderr=f_err, env=env,
                )
                try:
                    rc = await asyncio.wait_for(proc.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    try:
                        import subprocess as _sp
                        _sp.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                                capture_output=True, timeout=10)
                    except Exception:
                        pass
                    return {"ok": False, "error": f"gemini_timeout_{timeout}s"}
            out = log_out_path.read_text(encoding="utf-8", errors="replace")
            return {"ok": rc == 0, "rc": rc, "output": out}
        except Exception as e:
            return {"ok": False, "error": f"spawn_failed: {e}"}


def _parse_findings(text: str) -> List[Dict[str, str]]:
    """Парсит JSON-блок findings из ответа Gemini. Если нет JSON — возвращает один общий блок."""
    # Ищем ```json ... ``` или просто [{...}]
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    # fallback: попробуем найти [...] напрямую
    m = re.search(r"(\[\s*\{.*?\}\s*\])", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return [{"severity": "info", "description": text.strip()[:500]}]


async def _handle_review(arguments: dict, **_kw) -> dict:
    target = (arguments.get("target") or "").strip()
    if not target:
        return {"ok": False, "error": "missing_target"}
    focus = (arguments.get("focus") or "all").lower().strip()
    if focus not in _FOCUS_PROMPTS:
        focus = "all"

    target_path = _resolve_target(target)
    files = _gather_files(target_path)
    if not files:
        return {"ok": False, "error": f"no_files_found: {target_path}"}

    # Собираем содержимое
    pieces = []
    total_chars = 0
    used_files = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if total_chars + len(text) > _MAX_FILE_CHARS:
            text = text[:_MAX_FILE_CHARS - total_chars]
        if not text.strip():
            continue
        rel = f.relative_to(_REPO_ROOT).as_posix() if _REPO_ROOT in f.parents else f.name
        pieces.append(f"### FILE: {rel}\n```\n{text}\n```")
        used_files.append(rel)
        total_chars += len(text)
        if total_chars >= _MAX_FILE_CHARS:
            break

    focus_prompt = _FOCUS_PROMPTS[focus]
    prompt = f"""Ты code reviewer. {focus_prompt}

КОД:
{chr(10).join(pieces)}

Верни ответ СТРОГО в формате:
```json
[
  {{"severity": "critical|major|minor|info",
    "category": "security|bug|performance|style|design",
    "file": "path/to/file.py",
    "line": 42,
    "issue": "Что не так (1-2 предложения)",
    "fix": "Как исправить (1-2 предложения)"}}
]
```

Найди до 10 самых важных проблем. Если код в порядке — верни пустой массив [].
НЕ пиши никакого текста до или после JSON-блока.
"""

    gres = await _run_gemini_review(prompt, timeout=180)
    if not gres.get("ok"):
        return {"ok": False, "error": gres.get("error", "gemini_failed")}

    findings = _parse_findings(gres.get("output", ""))
    crit = sum(1 for f in findings if f.get("severity") == "critical")
    major = sum(1 for f in findings if f.get("severity") == "major")
    minor = sum(1 for f in findings if f.get("severity") == "minor")

    summary = f"{len(findings)} находок: {crit} critical, {major} major, {minor} minor"
    say = f"Прошлась по коду — {summary}. " + (
        "Критичного нет, можно жить." if crit == 0 and major == 0
        else f"Главное: " + (findings[0].get("issue", "")[:80] if findings else "")
    )

    return {
        "ok": True,
        "files_reviewed": used_files,
        "focus": focus,
        "findings": findings[:10],
        "summary": summary,
        "say_to_user": say,
    }


REVIEW_SCHEMA = {
    "name": "code_review",
    "description": "Code review через Gemini CLI. Принимает файл или папку, опциональный focus (security|performance|style|bugs|all). Возвращает структурированные находки с severity и предложенным fix. НЕ правит код — только описывает. Чтобы применить — используй self_improve_propose.",
    "parameters": {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "Файл или папка (относительно корня репо или абсолютный путь)."},
            "focus": {"type": "string", "description": "security|performance|style|bugs|all (default)"},
        },
        "required": ["target"],
    },
}


registry.register(name="code_review", toolset="self_improve",
                  schema=REVIEW_SCHEMA, handler=_handle_review,
                  is_async=True, emoji="🔎")
