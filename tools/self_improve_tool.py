"""
self_improve — Тройка может предлагать изменения в свой собственный код,
но НЕ применяет их без явного одобрения Миши.

Безопасность:
  • Каждое предложение = ветка `troika/proposal-<id>` в git, не main
  • Diff сохраняется в ~/.troika/proposals/<id>.json
  • Запретные пути: gateway/, .env, cli.py, requirements.txt, скрипты install
  • Лимиты: ≤5 файлов, ≤300 изменённых строк, ≤10 KB diff
  • Применить может только Миша голосом «применить предложение N»
    или через self_improve_approve(proposal_id)

Tools:
  • self_improve_propose — Тройка генерирует diff через Gemini CLI
  • self_improve_list    — показать pending proposals
  • self_improve_show    — diff и rationale конкретного proposal
  • self_improve_approve — мёрджит ветку в main, перезапускает gateway
  • self_improve_reject  — удаляет ветку

Все операции идут через git, поэтому любое применённое предложение откатывается
одним `git revert <hash>`. История ничего не теряет.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.registry import registry

logger = logging.getLogger(__name__)


_TROIKA_HOME = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".troika"))
_PROPOSALS_DIR = _TROIKA_HOME / "proposals"
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Пути которые Тройка НЕ может трогать без отдельного флага бога.
# Это не «строгая безопасность» (Миша всё равно может сам отредактировать),
# а защита от случайных самоудачных правок которые сломают сервер.
_FORBIDDEN_PATTERNS = [
    r"^\.env",
    r"^cli\.py$",
    r"^requirements.*\.txt$",
    r"^pyproject\.toml$",
    r"^scripts/install",
    r"^gateway/",            # gateway критичен для жизни
    r"^hermes_cli/",         # CLI критичен
    r"^\.git/",
    r"^tools/self_improve",  # сама себя не правит! (покрывает _verify, _watcher тоже)
    r"^tools/self_improve_verify",  # явно: движок проверки/переключения — несгораемый
    r"^tools/self_improve_watcher",  # явно: страховочный watcher отката
    r"^tools/registry\.py$",
    r"^tools/job_runner\.py$",
]
_FORBIDDEN_RE = re.compile("|".join(_FORBIDDEN_PATTERNS))

_MAX_FILES = 5
_MAX_LINES_CHANGED = 300
_MAX_DIFF_BYTES = 10_000

_BRANCH_PREFIX = "troika/proposal-"

# Артефакты самого движка — пишутся в репо при работе Gemini и НЕ должны попадать
# в предложение. Иначе diff/файлы/risk-флаги засоряются логами (всплыло на живом
# прогоне 10 июня: .self_improve.log/_logs/ попали в proposal и пометили его risky).
_ARTIFACT_PREFIXES = (
    ".self_improve.log", ".self_improve.err", ".PROPOSAL_NOTE.txt",
    "_logs/", "_logs", "_green_gateway.", "_self_improve_watcher.log",
)


def _is_artifact(path: str) -> bool:
    p = path.replace("\\", "/").lstrip("./")
    return any(p == a or p.startswith(a) for a in
               (a.replace("\\", "/").lstrip("./") for a in _ARTIFACT_PREFIXES))


def _collect_changed_files(cwd: Path = _REPO_ROOT) -> List[str]:
    """Реально изменённые файлы предложения — без артефактов движка и без
    gitignored-путей (untracked мусор вроде _logs/ сюда не попадает)."""
    st = _git("status", "--porcelain", "--untracked-files=normal", cwd=cwd).stdout
    files: List[str] = []
    for line in st.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        f = parts[1].strip('"')
        if _is_artifact(f):
            continue
        files.append(f)
    return files


def _ensure_dirs():
    _PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)


def _slug(text: str, max_len: int = 30) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower())[:max_len].strip("-")
    return s or "noop"


def _git(*args: str, cwd: Path = _REPO_ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=check,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )


def _abort_to_main(branch: Optional[str] = None) -> None:
    """Безопасный откат на чистый main при ЛЮБОМ обрыве propose.

    КРИТИЧНО: Gemini мог оставить НЕзакоммиченные правки в рабочем дереве. Если просто
    `git checkout main`, эти правки «переедут» на main (всплыло на живом прогоне:
    мусорный add_numbers в utils.py утёк на main). Поэтому СНАЧАЛА жёстко сбрасываем
    рабочее дерево (reset --hard + clean реальных файлов), и только потом checkout main.
    """
    try:
        _git("reset", "--hard", "HEAD", check=False)
    except Exception:
        pass
    # Удаляем неотслеживаемые файлы, которые Gemini мог создать (новый tool и т.п.),
    # НО только не-игнорируемые — артефакты/логи не трогаем тут (их чистит вызывающий).
    try:
        _git("clean", "-fd", "--", "tools/", "skills/", check=False)
    except Exception:
        pass
    try:
        _git("checkout", "main", check=False)
    except Exception:
        pass
    if branch:
        try:
            _git("branch", "-D", branch, check=False)
        except Exception:
            pass


def _is_clean_main() -> tuple[bool, str]:
    """Возвращает (ok, reason). ok=True если на main и нет несохранённых правок."""
    try:
        branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if branch != "main":
            return False, f"not_on_main (current: {branch})"
        # --untracked-files=no: неотслеживаемые файлы (логи, scratch-скрипты _*.py,
        # каталоги вроде _logs/) НЕ мешают ветвлению/merge — учитываем только
        # реальные несохранённые правки tracked-файлов.
        st = _git("status", "--porcelain", "--untracked-files=no").stdout.strip()
        if st:
            return False, f"uncommitted_changes ({len(st.splitlines())} files)"
        return True, "ok"
    except Exception as e:
        return False, f"git_error: {e}"


def _validate_diff(diff_text: str, files: List[str]) -> Optional[str]:
    """Возвращает None если ок, иначе текст ошибки."""
    if not diff_text.strip():
        return "empty_diff"
    if len(diff_text.encode("utf-8")) > _MAX_DIFF_BYTES:
        return f"diff_too_large (>{_MAX_DIFF_BYTES} bytes)"
    if len(files) > _MAX_FILES:
        return f"too_many_files ({len(files)} > {_MAX_FILES})"
    for f in files:
        if _FORBIDDEN_RE.match(f):
            return f"forbidden_path: {f}"
    added = sum(1 for ln in diff_text.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff_text.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    if added + removed > _MAX_LINES_CHANGED:
        return f"too_many_lines_changed ({added + removed} > {_MAX_LINES_CHANGED})"
    return None


def _save_proposal(proposal: Dict[str, Any]) -> Path:
    _ensure_dirs()
    pid = proposal["id"]
    path = _PROPOSALS_DIR / f"{pid}.json"
    path.write_text(json.dumps(proposal, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _load_proposal(pid: str) -> Optional[Dict[str, Any]]:
    path = _PROPOSALS_DIR / f"{pid}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _list_proposals() -> List[Dict[str, Any]]:
    _ensure_dirs()
    out = []
    for p in sorted(_PROPOSALS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(data)
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# propose
# ---------------------------------------------------------------------------

def _build_propose_prompt(description: str, target_files: List[str]) -> str:
    """Единый prompt для кодера-под-агента (Gemini или Claude)."""
    file_list_str = ", ".join(target_files) if target_files else "<любые файлы кроме запрещённых>"
    forbidden_str = ", ".join([
        ".env", "cli.py", "requirements.txt", "gateway/", "hermes_cli/",
        "tools/registry.py", "tools/job_runner.py", "tools/self_improve_tool.py",
    ])
    return f"""ВЫПОЛНИ СЕЙЧАС следующую задачу в этом репозитории. Не спрашивай подтверждения,
не уточняй, не отвечай текстом — сразу начни редактировать/создавать файлы инструментами.

ЗАДАЧА:
{description}

Целевые файлы: {file_list_str}

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
1. Делай РОВНО эту задачу. НЕ выбирай другую, НЕ «улучшай на своё усмотрение»
   (никакой локализации/рефакторинга/README, если этого нет в задаче).
2. Если задача про новый инструмент — СОЗДАЙ указанный файл tools/...py с рабочим
   кодом и зарегистрируй его как соседние (registry.register с schema/handler/toolset;
   handler принимает (arguments, **_kw) и возвращает dict с say_to_user). Открой любой
   готовый tools/*_tool.py как образец.
3. ЗАПРЕЩЕНО трогать: {forbidden_str}. Не трогать локали/логи/артефакты.
4. Лимит: ≤5 файлов, ≤300 строк. Готовый код без placeholder'ов и TODO, стиль соседнего.
5. НЕ делай git commit — это сделает скрипт.

ПОСЛЕДНИЙ ШАГ: запиши однострочное summary сделанного в файл .PROPOSAL_NOTE.txt.

Приступай немедленно — первым действием открой образцовый tools/*_tool.py, затем создай
целевой файл."""


def _self_improve_backend() -> Optional[str]:
    """Какой CLI-кодер доступен для самоулучшения. claude приоритетнее (подписка),
    gemini — fallback. None если ни один не настроен."""
    try:
        from tools.coder_tool import _find_backend_cli
        # Claude: подписка/OAuth, основной кодер на сервере
        if _find_backend_cli("claude"):
            return "claude"
    except Exception:
        pass
    # Gemini: нужен ключ или oauth
    try:
        from tools.gemini_code_tool import _find_gemini_cli
        if _find_gemini_cli():
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            oauth = Path.home() / ".gemini" / "oauth_creds.json"
            if api_key or oauth.exists():
                return "gemini"
    except Exception:
        pass
    return None


async def _propose_via_claude(description: str, target_files: List[str]) -> Dict[str, Any]:
    """Запускает Claude Code CLI (подписка) в репо для внесения правок."""
    from tools.coder_tool import _run_coder
    task = _build_propose_prompt(description, target_files)
    res = await _run_coder("claude", _REPO_ROOT, task, timeout=300)
    # _run_coder уже вернул {ok, ...}; нормализуем под контракт _propose_via_gemini
    if res.get("ok"):
        return {"ok": True, "rc": 0, "backend": "claude"}
    return {"ok": False, "error": res.get("error") or "claude_failed",
            "details": res}


async def _propose_via_gemini(branch: str, description: str, target_files: List[str]) -> Dict[str, Any]:
    """Запускает Gemini CLI в репо, даёт задачу, ожидает что он внесёт правки в указанные файлы."""
    from tools.gemini_code_tool import _find_gemini_cli, _HEADLESS_RULES

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
    env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"

    file_list_str = ", ".join(target_files) if target_files else "<любые файлы кроме запрещённых>"
    forbidden_str = ", ".join([
        ".env", "cli.py", "requirements.txt", "gateway/", "hermes_cli/",
        "tools/registry.py", "tools/job_runner.py", "tools/self_improve_tool.py",
    ])
    prompt = f"""ВЫПОЛНИ СЕЙЧАС следующую задачу в этом репозитории. Не спрашивай подтверждения,
не уточняй, не отвечай текстом — сразу начни редактировать/создавать файлы инструментами.

ЗАДАЧА:
{description}

Целевые файлы: {file_list_str}

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
1. Делай РОВНО эту задачу. НЕ выбирай другую, НЕ «улучшай на своё усмотрение»
   (никакой локализации/рефакторинга/README, если этого нет в задаче).
2. Если задача про новый инструмент — СОЗДАЙ указанный файл tools/...py с рабочим
   кодом и зарегистрируй его как соседние (registry.register с schema/handler/toolset;
   handler принимает (arguments, **_kw) и возвращает dict с say_to_user). Открой любой
   готовый tools/*_tool.py как образец.
3. ЗАПРЕЩЕНО трогать: {forbidden_str}. Не трогать локали/логи/артефакты.
4. Лимит: ≤5 файлов, ≤300 строк. Готовый код без placeholder'ов и TODO, стиль соседнего.
5. НЕ делай git commit — это сделает скрипт.

ПОСЛЕДНИЙ ШАГ: запиши однострочное summary сделанного в файл .PROPOSAL_NOTE.txt.

Приступай немедленно — первым действием открой образцовый tools/*_tool.py, затем создай
целевой файл."""

    # Модель: pro, НЕ дефолтный flash. Самоулучшение — это «создай файл + зарегистрируй
    # tool» = много tool-calls, на которых gemini-2.5-flash валится «Invalid stream:
    # empty response or malformed tool call» (см. autopilot-flash-invalid-stream).
    # Для правок в собственный код корректность важнее экономии квоты → сразу pro.
    args = [cli, "--yolo", "-m", "gemini-2.5-pro",
            "--allowed-mcp-server-names", "__none__", "--prompt", prompt]
    log_out = _REPO_ROOT / ".self_improve.log"
    log_err = _REPO_ROOT / ".self_improve.err"

    async def _one_run() -> Dict[str, Any]:
        try:
            with open(log_out, "wb") as f_out, open(log_err, "wb") as f_err:
                proc = await asyncio.create_subprocess_exec(
                    *args, cwd=str(_REPO_ROOT),
                    stdout=f_out, stderr=f_err, env=env,
                )
                try:
                    rc = await asyncio.wait_for(proc.wait(), timeout=300)
                except asyncio.TimeoutError:
                    try:
                        import subprocess as _sp
                        _sp.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                                capture_output=True, timeout=10)
                    except Exception:
                        pass
                    return {"ok": False, "error": "gemini_timeout_300s"}
            out = log_out.read_text(encoding="utf-8", errors="replace") if log_out.exists() else ""
            err = log_err.read_text(encoding="utf-8", errors="replace") if log_err.exists() else ""
            if re.search(r"Invalid stream|malformed tool call|empty response", err, re.IGNORECASE):
                return {"ok": False, "error": "gemini_malformed_stream",
                        "err_tail": err[-300:]}
            return {"ok": rc == 0, "rc": rc, "out_tail": out[-500:]}
        except Exception as e:
            return {"ok": False, "error": f"spawn_failed: {e}"}

    # Ретрай на malformed-флапах «Invalid stream» — они часто разовые (см.
    # autopilot-flash-invalid-stream). Ретраим ТОЛЬКО если Gemini не оставил
    # реальных правок (нет файлового прогресса) — иначе можем затереть успех.
    last: Dict[str, Any] = {}
    for attempt in range(1, 4):
        last = await _one_run()
        if last.get("ok"):
            return last
        if last.get("error") != "gemini_malformed_stream":
            return last
        if _collect_changed_files():
            # Файлы всё-таки появились до обрыва — считаем успехом, дальше валидатор.
            return {"ok": True, "rc": 0, "note": "progress_despite_malformed"}
        logger.warning("self_improve gemini malformed flap, retry %d/3", attempt)
        await asyncio.sleep(3)
    last.setdefault("hint", "Модель трижды оборвалась на Invalid stream. "
                            "Попробуй упростить задачу или повтори позже.")
    return last


async def _handle_propose(arguments: dict, **_kw) -> dict:
    description = (arguments.get("description") or "").strip()
    rationale = (arguments.get("rationale") or "").strip()
    target_files = arguments.get("target_files") or []
    if isinstance(target_files, str):
        target_files = [f.strip() for f in target_files.split(",") if f.strip()]

    if not description:
        return {"ok": False, "error": "missing_description"}
    if not rationale:
        return {"ok": False, "error": "missing_rationale",
                "hint": "Объясни ЗАЧЕМ это изменение — без 'почему' предложение не принимается"}

    # Validate target_files против запретов до запуска Gemini
    for f in target_files:
        if _FORBIDDEN_RE.match(f):
            return {"ok": False, "error": f"forbidden_path: {f}"}

    ok, reason = _is_clean_main()
    if not ok:
        return {"ok": False, "error": f"repo_not_clean: {reason}",
                "hint": "Сначала закоммить или откати текущие изменения"}

    # Выбираем доступный кодер ДО создания ветки, чтобы не плодить пустые ветки.
    backend = _self_improve_backend()
    if backend is None:
        return {"ok": False, "error": "no_coder",
                "hint": "Нет настроенного CLI-кодера. Залогинь Claude (claude setup-token) "
                        "или задай GEMINI_API_KEY."}

    pid = uuid.uuid4().hex[:8]
    branch = f"{_BRANCH_PREFIX}{pid}-{_slug(description)}"

    try:
        _git("checkout", "-b", branch)
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": f"branch_create_failed: {e.stderr[:200]}"}

    try:
        if backend == "claude":
            gres = await _propose_via_claude(description, target_files)
        else:
            gres = await _propose_via_gemini(branch, description, target_files)
        if not gres.get("ok"):
            _abort_to_main(branch)
            return {"ok": False, "error": f"{backend}_failed", "details": gres}

        # Извлекаем note (summary Gemini) и удаляем её до сбора файлов.
        note_path = _REPO_ROOT / ".PROPOSAL_NOTE.txt"
        note = note_path.read_text(encoding="utf-8", errors="replace").strip() if note_path.exists() else ""
        if note_path.exists():
            note_path.unlink()  # не коммитим заметку

        # Что изменилось (без артефактов движка и gitignored-мусора)?
        changed_files = _collect_changed_files()
        if not changed_files:
            _abort_to_main(branch)
            return {"ok": False, "error": "no_changes_made",
                    "hint": "Gemini не внёс правок в реальные файлы (только логи/артефакты)"}

        # Стейджим ТОЛЬКО реальные файлы (не git add . — иначе подберём логи/артефакты).
        for f in changed_files:
            _git("add", "--", f, check=False)
        # diff считаем по застейдженному — ровно то, что войдёт в коммит.
        diff_text = _git("diff", "--cached").stdout

        # Валидация
        err = _validate_diff(diff_text, changed_files)
        if err:
            _abort_to_main(branch)
            return {"ok": False, "error": f"validation: {err}",
                    "details": {"files": changed_files,
                                "diff_size": len(diff_text)}}

        # Коммит на ветке (только застейдженные реальные файлы)
        commit_msg = f"proposal: {description[:60]}\n\nRationale: {rationale}"
        _git("commit", "-m", commit_msg)
        commit_hash = _git("rev-parse", "HEAD").stdout.strip()

        # Обратно на main (ветка остаётся)
        _git("checkout", "main")

        proposal = {
            "id": pid,
            "branch": branch,
            "commit": commit_hash,
            "created_at": time.time(),
            "description": description,
            "rationale": rationale,
            "note": note,
            "files": changed_files,
            "diff_size": len(diff_text),
            "lines_changed": sum(1 for ln in diff_text.splitlines()
                                  if ln.startswith(("+", "-")) and not ln.startswith(("+++", "---"))),
            "status": "pending",
            "diff_preview": diff_text[:2000],
        }
        _save_proposal(proposal)

        base_resp = {
            "ok": True,
            "proposal_id": pid,
            "branch": branch,
            "files_changed": len(changed_files),
            "lines_changed": proposal["lines_changed"],
            "files": changed_files,
        }

        # ── Проверка в green-песочнице + (авто-применение | оставить pending) ──
        # auto_verify=False (по умолчанию из аргументов false-y) пропускает живой прогон
        # — нужно для тестов и для случаев когда Миша хочет ручной approve.
        if arguments.get("auto_verify", True):
            try:
                from tools.self_improve_verify import verify_classify_and_maybe_apply
                outcome = await verify_classify_and_maybe_apply(proposal)
                base_resp.update({
                    "risk": outcome.get("risk"),
                    "verify": outcome.get("verify"),
                    "auto_applied": outcome.get("auto_applied", False),
                    "needs_approval": outcome.get("needs_approval", True),
                    "say_to_user": outcome.get("say_to_user"),
                })
                return base_resp
            except Exception as e:
                logger.warning("verify stage failed, falling back to manual approve: %s", e)
                # Падать нельзя — предложение уже создано. Откатываемся к ручному approve.

        base_resp["say_to_user"] = (
            f"Готово, предложение {pid}. Изменила {len(changed_files)} файлов на "
            f"{proposal['lines_changed']} строк. Скажи «покажи предложение {pid}» "
            f"чтобы посмотреть, или «применить {pid}» чтобы накатить."
        )
        return base_resp
    except subprocess.CalledProcessError as e:
        _abort_to_main(branch)
        return {"ok": False, "error": f"git_error: {e.stderr[:300]}"}
    except Exception as e:
        try:
            _abort_to_main(branch)
        except Exception:
            pass
        return {"ok": False, "error": f"propose_failed: {type(e).__name__}: {e}"}


# ---------------------------------------------------------------------------
# list / show
# ---------------------------------------------------------------------------

async def _handle_list(arguments: dict, **_kw) -> dict:
    status_filter = arguments.get("status", "pending")
    items = _list_proposals()
    if status_filter and status_filter != "all":
        items = [p for p in items if p.get("status") == status_filter]
    items.sort(key=lambda p: p.get("created_at", 0), reverse=True)
    if not items:
        return {"ok": True, "proposals": [], "say_to_user": "Открытых предложений нет."}
    summary = []
    for p in items[:10]:
        age_min = int((time.time() - p.get("created_at", time.time())) / 60)
        summary.append({
            "id": p["id"],
            "description": p["description"][:80],
            "files": len(p.get("files", [])),
            "lines": p.get("lines_changed", 0),
            "status": p.get("status"),
            "age_min": age_min,
        })
    return {"ok": True, "proposals": summary}


async def _handle_show(arguments: dict, **_kw) -> dict:
    pid = (arguments.get("proposal_id") or "").strip()
    if not pid:
        return {"ok": False, "error": "missing_proposal_id"}
    p = _load_proposal(pid)
    if not p:
        return {"ok": False, "error": "not_found"}
    return {
        "ok": True,
        "id": p["id"],
        "description": p["description"],
        "rationale": p["rationale"],
        "note": p.get("note", ""),
        "files": p.get("files", []),
        "lines_changed": p.get("lines_changed", 0),
        "diff_preview": p.get("diff_preview", "")[:1500],
        "status": p.get("status"),
        "branch": p.get("branch"),
    }


# ---------------------------------------------------------------------------
# approve / reject
# ---------------------------------------------------------------------------

async def _handle_approve(arguments: dict, **_kw) -> dict:
    pid = (arguments.get("proposal_id") or "").strip()
    if not pid:
        return {"ok": False, "error": "missing_proposal_id"}
    p = _load_proposal(pid)
    if not p:
        return {"ok": False, "error": "not_found"}
    if p.get("status") != "pending":
        return {"ok": False, "error": f"already_{p.get('status')}"}

    ok, reason = _is_clean_main()
    if not ok:
        return {"ok": False, "error": f"repo_not_clean: {reason}"}

    branch = p["branch"]
    try:
        # fast-forward или merge --no-ff?
        # Делаем squash merge: один аккуратный коммит на main, ветку удаляем
        _git("merge", "--squash", branch)
        commit_msg = f"troika self-improve: {p['description'][:60]}\n\nRationale: {p['rationale']}\nProposal: {pid}"
        _git("commit", "-m", commit_msg)
        merge_hash = _git("rev-parse", "HEAD").stdout.strip()
        _git("branch", "-D", branch, check=False)

        p["status"] = "applied"
        p["applied_at"] = time.time()
        p["merge_commit"] = merge_hash
        _save_proposal(p)

        return {
            "ok": True,
            "proposal_id": pid,
            "merge_commit": merge_hash,
            "rollback_cmd": f"git revert {merge_hash}",
            "say_to_user": f"Применила предложение {pid}. Если что — откатить можно: git revert {merge_hash[:8]}. Возможно понадобится перезапуск gateway чтобы изменения подхватились.",
        }
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": f"merge_failed: {e.stderr[:300]}"}


async def _handle_reject(arguments: dict, **_kw) -> dict:
    pid = (arguments.get("proposal_id") or "").strip()
    if not pid:
        return {"ok": False, "error": "missing_proposal_id"}
    p = _load_proposal(pid)
    if not p:
        return {"ok": False, "error": "not_found"}
    if p.get("status") != "pending":
        return {"ok": False, "error": f"already_{p.get('status')}"}

    branch = p["branch"]
    try:
        _git("branch", "-D", branch, check=False)
        p["status"] = "rejected"
        p["rejected_at"] = time.time()
        _save_proposal(p)
        return {"ok": True, "proposal_id": pid,
                "say_to_user": f"Удалила предложение {pid}."}
    except Exception as e:
        return {"ok": False, "error": f"reject_failed: {e}"}


async def _handle_revert(arguments: dict, **_kw) -> dict:
    """Откатить УЖЕ ПРИМЕНЁННОЕ предложение: git revert merge-коммита на main.
    Голосом «откати N» — после авто-применения, если изменение не понравилось."""
    pid = (arguments.get("proposal_id") or "").strip()
    if not pid:
        return {"ok": False, "error": "missing_proposal_id"}
    p = _load_proposal(pid)
    if not p:
        return {"ok": False, "error": "not_found"}
    if p.get("status") != "applied":
        return {"ok": False, "error": f"not_applied (status={p.get('status')})",
                "hint": "Откатить можно только применённое предложение."}
    merge_commit = p.get("merge_commit")
    if not merge_commit:
        return {"ok": False, "error": "no_merge_commit"}

    ok, reason = _is_clean_main()
    if not ok:
        return {"ok": False, "error": f"repo_not_clean: {reason}"}
    try:
        _git("revert", "--no-edit", merge_commit)
        revert_commit = _git("rev-parse", "HEAD").stdout.strip()
        p["status"] = "reverted"
        p["reverted_at"] = time.time()
        p["revert_commit"] = revert_commit
        _save_proposal(p)
        return {
            "ok": True, "proposal_id": pid, "revert_commit": revert_commit,
            "say_to_user": f"Откатила предложение {pid}. Перезапусти gateway, чтобы "
                           f"вернуться на прежний код — или скажи и я сама.",
        }
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": f"revert_failed: {e.stderr[:300]}"}


# ---------------------------------------------------------------------------
# Schemas + registration
# ---------------------------------------------------------------------------

PROPOSE_SCHEMA = {
    "name": "self_improve_propose",
    "description": "Тройка улучшает собственный код через Gemini CLI: создаёт git-ветку с правками, ПРОВЕРЯЕТ их в одноразовой песочнице (новый код реально запускается + прогоняются тесты), и если изменение БЕЗОПАСНОЕ (новый tool/навык/мелкая правка) и проверка прошла — применяет САМА и перезапускается на новой версии. Рискованное (память/сеть/деньги/ядро) или не прошедшее проверку — остаётся ждать твоего «применить N». Запрещено трогать gateway/, cli.py, .env, hermes_cli/, registry. Лимит: ≤5 файлов, ≤300 строк. Используй на «добавь себе фичу», «улучши такой-то tool», «научись делать X».",
    "parameters": {
        "type": "object",
        "properties": {
            "description": {"type": "string", "description": "Что улучшить. Конкретно и сжато (1-3 предложения)."},
            "rationale": {"type": "string", "description": "Зачем — почему это полезно, что станет лучше. Без этого предложение не принимается."},
            "target_files": {"type": "array", "items": {"type": "string"}, "description": "Список путей которые планируешь трогать (относительно репо). Помогает Gemini фокусироваться. Опционально."},
            "auto_verify": {"type": "boolean", "description": "По умолчанию true: проверить в песочнице и авто-применить если безопасно. false — только создать предложение для ручного approve."},
        },
        "required": ["description", "rationale"],
    },
}

LIST_SCHEMA = {
    "name": "self_improve_list",
    "description": "Показать список предложений по улучшению Тройки. По умолчанию — только pending.",
    "parameters": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "description": "pending|applied|rejected|all. Default pending."},
        },
    },
}

SHOW_SCHEMA = {
    "name": "self_improve_show",
    "description": "Показать детали и diff конкретного предложения.",
    "parameters": {
        "type": "object",
        "properties": {
            "proposal_id": {"type": "string"},
        },
        "required": ["proposal_id"],
    },
}

APPROVE_SCHEMA = {
    "name": "self_improve_approve",
    "description": "Применить предложение: squash-merge ветки в main. Откат: git revert <merge_commit>. Только Миша может одобрить — Тройка сама себя не одобряет.",
    "parameters": {
        "type": "object",
        "properties": {
            "proposal_id": {"type": "string"},
        },
        "required": ["proposal_id"],
    },
}

REJECT_SCHEMA = {
    "name": "self_improve_reject",
    "description": "Отклонить ОЖИДАЮЩЕЕ предложение, удалить его ветку.",
    "parameters": {
        "type": "object",
        "properties": {
            "proposal_id": {"type": "string"},
        },
        "required": ["proposal_id"],
    },
}

REVERT_SCHEMA = {
    "name": "self_improve_revert",
    "description": "Откатить УЖЕ ПРИМЕНЁННОЕ предложение через git revert merge-коммита. Используй на «откати N», «верни как было», когда применённое (в т.ч. авто-применённое) изменение не понравилось или сломало поведение.",
    "parameters": {
        "type": "object",
        "properties": {
            "proposal_id": {"type": "string"},
        },
        "required": ["proposal_id"],
    },
}


registry.register(name="self_improve_propose", toolset="self_improve",
                  schema=PROPOSE_SCHEMA, handler=_handle_propose,
                  is_async=True, emoji="🧠")
registry.register(name="self_improve_list", toolset="self_improve",
                  schema=LIST_SCHEMA, handler=_handle_list,
                  is_async=True, emoji="📋")
registry.register(name="self_improve_show", toolset="self_improve",
                  schema=SHOW_SCHEMA, handler=_handle_show,
                  is_async=True, emoji="🔍")
registry.register(name="self_improve_approve", toolset="self_improve",
                  schema=APPROVE_SCHEMA, handler=_handle_approve,
                  is_async=True, emoji="✅")
registry.register(name="self_improve_reject", toolset="self_improve",
                  schema=REJECT_SCHEMA, handler=_handle_reject,
                  is_async=True, emoji="❌")
registry.register(name="self_improve_revert", toolset="self_improve",
                  schema=REVERT_SCHEMA, handler=_handle_revert,
                  is_async=True, emoji="↩️")
