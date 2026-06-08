"""
Tool `project` — управление проектами Тройки.

Концепция: один активный проект за раз. Все вызовы project/build идут в активный.
Тройка узнаёт о нём через context-injection в начале каждого turn.

Структура проекта:
  d:/troika-projects/<slug>-<timestamp>/
    .project.json        — метаданные (name, phase, created, summary)
    README.md            — короткое описание
    docs/
      01-vision.md
      02-requirements.md
      03-architecture.md
      04-tasks.md
      decisions.md       — ADR-style решения по ходу
    product/             — здесь код (фаза building)

Под-агент: gemini-cli с системным промптом ~/.gemini/GEMINI-PM.md
(senior PM/Tech Lead style, не AI-туман).

Actions:
  start(name, summary?)        — создать проект, сделать активным
  open(name)                   — переключить активный
  close()                      — выйти из активного
  status()                     — что сейчас активно
  list()                       — все проекты
  add_note(text)               — записать идею в current doc
  next_phase()                 — discovery → requirements → architecture → tasks → building
  generate_doc()               — попросить PM-агента написать/обновить doc для текущей фазы (async)
  build(task)                  — фаза building: gemini_code create/iterate в product/ (async)
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.registry import registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths & state
# ---------------------------------------------------------------------------

_PROJECTS_ROOT = Path("D:/troika-projects")
_TROIKA = Path.home() / ".troika"
_ACTIVE_FILE = _TROIKA / "active_project.json"

_PHASES = ["discovery", "requirements", "architecture", "tasks", "building"]
_PHASE_DOCS = {
    "discovery": "docs/01-vision.md",
    "requirements": "docs/02-requirements.md",
    "architecture": "docs/03-architecture.md",
    "tasks": "docs/04-tasks.md",
    "building": None,  # код, не доки
}
_PHASE_LABELS_RU = {
    "discovery": "обсуждение идеи",
    "requirements": "требования",
    "architecture": "архитектура",
    "tasks": "планирование задач",
    "building": "написание кода",
}


def _slugify(text: str) -> str:
    text = text.lower().strip()
    # Транслит для cyrillic
    table = str.maketrans({
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    })
    text = text.translate(table)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")[:50]
    return text or "project"


# ---------------------------------------------------------------------------
# Active project state
# ---------------------------------------------------------------------------

def _load_active() -> Optional[Dict[str, Any]]:
    if not _ACTIVE_FILE.exists():
        return None
    try:
        data = json.loads(_ACTIVE_FILE.read_text(encoding="utf-8"))
        # Sanity: путь существует?
        if data.get("path") and not Path(data["path"]).exists():
            logger.warning("active project path missing, clearing: %s", data["path"])
            _ACTIVE_FILE.unlink(missing_ok=True)
            return None
        return data
    except Exception as e:
        logger.warning("load_active failed: %s", e)
        return None


def _save_active(data: Optional[Dict[str, Any]]) -> None:
    _TROIKA.mkdir(parents=True, exist_ok=True)
    if data is None:
        _ACTIVE_FILE.unlink(missing_ok=True)
        return
    _ACTIVE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_active_project_summary() -> Optional[str]:
    """Краткая сводка для context-injection в gateway. Возвращает строку или None."""
    data = _load_active()
    if not data:
        return None
    phase_ru = _PHASE_LABELS_RU.get(data.get("phase", ""), data.get("phase", ""))
    base = (
        f"[ACTIVE_PROJECT name=\"{data.get('name')}\" phase=\"{phase_ru}\" "
        f"path=\"{data.get('path')}\"] "
        f"Все обращения 'этот проект' / 'наш проект' / build / add_note → в этот проект. "
        f"Если Миша явно зовёт другой проект, спроси и переключи через project(action=open)."
    )
    # Авто-саммари последнего прогона (B2) — актуальное «где мы сейчас».
    try:
        brief = _read_project_state_brief(Path(data["path"]))
        if brief:
            base += f" Состояние: {brief}"
    except Exception:
        pass
    return base


# ---------------------------------------------------------------------------
# Project metadata
# ---------------------------------------------------------------------------

def _read_meta(project_path: Path) -> Dict[str, Any]:
    meta_file = project_path / ".project.json"
    if not meta_file.exists():
        return {}
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_meta(project_path: Path, meta: Dict[str, Any]) -> None:
    meta_file = project_path / ".project.json"
    meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _list_all_projects() -> List[Dict[str, Any]]:
    if not _PROJECTS_ROOT.exists():
        return []
    items = []
    for p in sorted(_PROJECTS_ROOT.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_dir():
            continue
        meta = _read_meta(p)
        if not meta:
            continue
        items.append({
            "id": p.name,
            "path": str(p),
            "name": meta.get("name", p.name),
            "phase": meta.get("phase", "?"),
            "summary": meta.get("summary", ""),
            "created_at": meta.get("created_at"),
        })
    return items


def _find_project_by_name(query: str) -> Optional[Path]:
    """Поиск проекта по name (fuzzy) или по id slug."""
    query_lower = query.lower().strip()
    if not _PROJECTS_ROOT.exists():
        return None
    candidates: List[tuple] = []
    for p in _PROJECTS_ROOT.iterdir():
        if not p.is_dir():
            continue
        meta = _read_meta(p)
        name = meta.get("name", "").lower()
        slug = p.name.lower()
        if query_lower == name or query_lower == slug:
            return p  # точное совпадение
        if query_lower in name or query_lower in slug:
            candidates.append((len(name) - len(query_lower), p))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

async def _action_start(args: Dict[str, Any]) -> Dict[str, Any]:
    name = (args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "missing 'name'",
                "say_to_user": "Скажи название проекта."}
    slug = _slugify(name)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    project_id = f"{slug}-{timestamp}"
    project_path = _PROJECTS_ROOT / project_id
    project_path.mkdir(parents=True, exist_ok=True)
    (project_path / "docs").mkdir(exist_ok=True)
    (project_path / "product").mkdir(exist_ok=True)

    meta = {
        "id": project_id,
        "name": name,
        "summary": (args.get("summary") or "").strip(),
        "phase": "discovery",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "notes": [],  # буфер мыслей пока doc не сгенерирован
    }
    _write_meta(project_path, meta)

    # README заглушка
    readme = (
        f"# {name}\n\n"
        f"_Создан: {meta['created_at']}_\n\n"
        f"{meta['summary'] or 'Описание будет добавлено в фазе vision.'}\n\n"
        f"## Структура\n"
        f"- `docs/01-vision.md` — зачем и для кого\n"
        f"- `docs/02-requirements.md` — TЗ, user stories, acceptance criteria\n"
        f"- `docs/03-architecture.md` — стек, диаграммы, ADR\n"
        f"- `docs/04-tasks.md` — разбиение на задачи с estimate\n"
        f"- `docs/decisions.md` — решения по ходу\n"
        f"- `product/` — код (фаза building)\n\n"
        f"## Текущая фаза\n"
        f"**discovery** — обсуждаем vision\n"
    )
    (project_path / "README.md").write_text(readme, encoding="utf-8")
    (project_path / "docs" / "decisions.md").write_text(
        f"# Decisions log — {name}\n\n_Каждое важное решение пишем сюда с датой._\n",
        encoding="utf-8",
    )

    # Делаем активным
    _save_active({
        "project_id": project_id,
        "path": str(project_path),
        "name": name,
        "phase": "discovery",
        "switched_at": datetime.now().isoformat(timespec="seconds"),
        "summary": meta["summary"],
    })

    return {
        "ok": True, "action": "start", "project_id": project_id,
        "path": str(project_path), "phase": "discovery",
        "say_to_user": (
            f"Создал проект «{name}». Сейчас мы на фазе обсуждения идеи. "
            f"Расскажи: для кого это и какую задачу решает?"
        ),
    }


async def _action_open(args: Dict[str, Any]) -> Dict[str, Any]:
    name = (args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "missing 'name'",
                "say_to_user": "Скажи название проекта который открыть."}
    project_path = _find_project_by_name(name)
    if not project_path:
        return {"ok": False, "error": "not_found",
                "say_to_user": f"Не нашёл проект «{name}». Скажи 'список проектов' чтобы увидеть все."}
    meta = _read_meta(project_path)
    _save_active({
        "project_id": project_path.name,
        "path": str(project_path),
        "name": meta.get("name", project_path.name),
        "phase": meta.get("phase", "discovery"),
        "switched_at": datetime.now().isoformat(timespec="seconds"),
        "summary": meta.get("summary", ""),
    })
    phase_ru = _PHASE_LABELS_RU.get(meta.get("phase", ""), meta.get("phase", ""))
    return {
        "ok": True, "action": "open", "project_id": project_path.name,
        "phase": meta.get("phase"),
        "say_to_user": f"Открыл проект «{meta.get('name')}». Сейчас фаза: {phase_ru}.",
    }


async def _action_close(args: Dict[str, Any]) -> Dict[str, Any]:
    active = _load_active()
    if not active:
        return {"ok": True, "say_to_user": "Активного проекта и так не было."}
    name = active.get("name", "проект")
    _save_active(None)
    return {"ok": True, "action": "close",
            "say_to_user": f"Закрыл проект «{name}». Дальше — общий режим."}


async def _action_status(args: Dict[str, Any]) -> Dict[str, Any]:
    active = _load_active()
    if not active:
        return {"ok": True, "active": None,
                "say_to_user": "Сейчас активного проекта нет."}
    project_path = Path(active["path"])
    meta = _read_meta(project_path)
    phase = meta.get("phase", active.get("phase", "?"))
    phase_ru = _PHASE_LABELS_RU.get(phase, phase)
    notes_count = len(meta.get("notes", []))
    docs_present = []
    for ph, rel in _PHASE_DOCS.items():
        if rel and (project_path / rel).exists():
            docs_present.append(ph)

    # Состояние сборки: есть ли product/ и dist/
    product_dir = project_path / "product"
    has_product = product_dir.exists() and any(product_dir.iterdir())
    dist_dir = product_dir / "dist"
    has_build = dist_dir.exists() and any(dist_dir.glob("*.html"))

    # Активные фоновые задачи на этот проект
    bg_jobs: List[Dict[str, Any]] = []
    try:
        from tools.job_runner import list_active as _list_jobs
        for j in _list_jobs():
            label = (j.get("short_label") or "")
            if active.get("name", "")[:20].lower() in label.lower() or active.get("project_id", "") in label:
                bg_jobs.append({"id": j["id"], "kind": j["kind"], "label": label, "status": j["status"]})
    except Exception as _e:
        logger.debug("list_active failed: %s", _e)

    say_parts = [f"Активный проект: «{active['name']}»", f"фаза {phase_ru}"]
    if notes_count: say_parts.append(f"заметок {notes_count}")
    if docs_present: say_parts.append(f"документов {len(docs_present)}")
    if has_product:
        say_parts.append("код есть" + (", билд собран" if has_build else ""))
    if bg_jobs:
        say_parts.append(f"в работе {len(bg_jobs)} задач{'а' if len(bg_jobs)==1 else ''}")
    say = ". ".join(say_parts) + "."

    return {
        "ok": True, "active": active, "meta": meta,
        "phase": phase, "notes_count": notes_count, "docs_present": docs_present,
        "has_product": has_product, "has_build": has_build,
        "bg_jobs": bg_jobs,
        "say_to_user": say,
    }


async def _action_list(args: Dict[str, Any]) -> Dict[str, Any]:
    items = _list_all_projects()
    if not items:
        return {"ok": True, "items": [], "say_to_user": "Проектов пока нет."}
    say = f"Проектов: {len(items)}. " + "; ".join(
        f"«{i['name']}» ({_PHASE_LABELS_RU.get(i['phase'], i['phase'])})"
        for i in items[:5]
    )
    if len(items) > 5:
        say += f"; ещё {len(items) - 5}."
    return {"ok": True, "items": items, "say_to_user": say}


async def _action_add_note(args: Dict[str, Any]) -> Dict[str, Any]:
    text = (args.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "missing 'text'"}
    active = _load_active()
    if not active:
        return {"ok": False, "error": "no_active_project",
                "say_to_user": "Сначала открой или создай проект."}
    project_path = Path(active["path"])
    meta = _read_meta(project_path)
    notes = meta.get("notes", [])
    notes.append({"text": text, "phase": meta.get("phase"), "at": datetime.now().isoformat(timespec="seconds")})
    meta["notes"] = notes
    _write_meta(project_path, meta)
    return {"ok": True, "action": "add_note",
            "say_to_user": "Записал."}


async def _action_next_phase(args: Dict[str, Any]) -> Dict[str, Any]:
    active = _load_active()
    if not active:
        return {"ok": False, "error": "no_active_project",
                "say_to_user": "Сначала открой или создай проект."}
    project_path = Path(active["path"])
    meta = _read_meta(project_path)
    cur = meta.get("phase", "discovery")
    try:
        idx = _PHASES.index(cur)
    except ValueError:
        idx = 0
    if idx >= len(_PHASES) - 1:
        return {"ok": True, "say_to_user": f"Мы уже на последней фазе ({_PHASE_LABELS_RU[cur]})."}
    new_phase = _PHASES[idx + 1]
    meta["phase"] = new_phase
    _write_meta(project_path, meta)

    # Обновляем active
    active["phase"] = new_phase
    active["switched_at"] = datetime.now().isoformat(timespec="seconds")
    _save_active(active)

    phase_ru = _PHASE_LABELS_RU[new_phase]
    hint = ""
    if new_phase == "requirements":
        hint = " Расскажи какие фичи нужны в первой версии."
    elif new_phase == "architecture":
        hint = " Подумаем о стеке. Какая платформа: веб, мобайл, десктоп?"
    elif new_phase == "tasks":
        hint = " Скажи 'сгенерируй задачи' и PM-агент разобьёт работу на части."
    elif new_phase == "building":
        hint = " Можно начинать писать код: скажи 'делай' и Gemini возьмётся за первую задачу."
    return {"ok": True, "action": "next_phase", "new_phase": new_phase,
            "say_to_user": f"Переход в фазу: {phase_ru}.{hint}"}


async def _action_generate_doc(args: Dict[str, Any]) -> Dict[str, Any]:
    """Попросить PM-агента написать (или обновить) документ текущей фазы."""
    active = _load_active()
    if not active:
        return {"ok": False, "error": "no_active_project",
                "say_to_user": "Сначала открой или создай проект."}
    project_path = Path(active["path"])
    meta = _read_meta(project_path)
    phase = meta.get("phase", "discovery")
    doc_rel = _PHASE_DOCS.get(phase)
    if not doc_rel:
        return {"ok": False, "error": "no_doc_for_phase",
                "say_to_user": f"На фазе {phase} документы не пишутся, тут уже код."}

    # Собираем контекст: meta + notes + предыдущие готовые доки
    notes_text = "\n".join(f"- {n['text']}" for n in meta.get("notes", []))
    prior_docs = []
    for ph in _PHASES[:_PHASES.index(phase)]:
        rel = _PHASE_DOCS.get(ph)
        if rel and (project_path / rel).exists():
            prior_docs.append(f"## {ph}\n" + (project_path / rel).read_text(encoding="utf-8")[:3000])

    task = (
        f"PROJECT: {meta.get('name')}\n"
        f"PHASE: {phase}\n"
        f"BRIEF SUMMARY: {meta.get('summary') or '(нет)'}\n\n"
        f"NOTES FROM USER (мысли которые Миша записывал голосом):\n{notes_text or '(нет)'}\n\n"
        f"PRIOR DOCS (для контекста, не дублировать):\n{chr(10).join(prior_docs) or '(нет)'}\n\n"
        f"TASK: Напиши/обнови документ '{doc_rel}' для фазы '{phase}'. "
        f"Структура по шаблону из GEMINI-PM.md. На русском. "
        f"ВАЖНО: пиши прямо в файл {doc_rel}, не выводи в чат."
    )

    # Submit в job_runner с PM системным промптом
    from tools import job_runner
    if job_runner.active_count() >= 6:
        return {"ok": False, "error": "too_many_active",
                "say_to_user": "У меня уже шесть задач в работе, подожди."}
    payload = {
        "project_path": str(project_path),
        "task": task,
        "use_pm_prompt": True,
        "timeout": 1800,
    }
    label = f"документ {doc_rel} ({meta.get('name')})"
    session_id = args.get("_session_id") or "phone-misha-main"
    task_id = job_runner.submit("project_pm_doc", payload, session_id=session_id, short_label=label)
    return {"ok": True, "action": "generate_doc", "task_id": task_id,
            "say_to_user": f"PM-агент пишет {doc_rel}. Скажу когда готово."}


async def _action_build(args: Dict[str, Any]) -> Dict[str, Any]:
    """Запустить кодинг через gemini_code create/iterate в product/ активного проекта."""
    active = _load_active()
    if not active:
        return {"ok": False, "error": "no_active_project",
                "say_to_user": "Сначала открой или создай проект."}
    project_path = Path(active["path"])
    product_dir = project_path / "product"
    product_dir.mkdir(exist_ok=True)
    meta = _read_meta(project_path)

    task = (args.get("task") or "").strip()
    if not task:
        # Если нет явной task — берём из tasks.md первую невыполненную
        tasks_md = project_path / "docs" / "04-tasks.md"
        if tasks_md.exists():
            content = tasks_md.read_text(encoding="utf-8")
            m = re.search(r"- \[ \] \*?\*?(.+?)\*?\*? — ", content)
            if m:
                task = m.group(1).strip()
        if not task:
            return {"ok": False, "error": "no_task",
                    "say_to_user": "Скажи что именно делать, или сгенерируй tasks.md сначала."}

    # Контекст из готовых doc'ов записываем в файл рядом с product/,
    # чтобы НЕ передавать его через --prompt (Windows cmdline limit ~32K chars).
    # Gemini-CLI прочитает файл через read_file tool.
    doc_context_parts = []
    for ph in ["discovery", "requirements", "architecture", "tasks"]:
        rel = _PHASE_DOCS.get(ph)
        if rel and (project_path / rel).exists():
            doc_context_parts.append(f"## {ph}\n" + (project_path / rel).read_text(encoding="utf-8"))
    doc_context = "\n\n".join(doc_context_parts)

    if doc_context:
        # Кладём контекст в .PROJECT_CONTEXT.md прямо в product/ —
        # gemini увидит файл и прочитает.
        ctx_file = product_dir / ".PROJECT_CONTEXT.md"
        ctx_file.write_text(
            f"# Project context for coding\n\n"
            f"Project: {meta.get('name')}\n"
            f"Phase: building\n\n"
            f"---\n\n{doc_context}\n",
            encoding="utf-8",
        )
        full_task = (
            f"BEFORE CODING: read .PROJECT_CONTEXT.md in current directory — "
            f"it has vision, requirements, architecture, tasks of this project. "
            f"Use it to make right tech choices.\n\n"
            f"CODING TASK: {task}\n"
            f"Working directory: {product_dir}. Create code files there. "
            f"Do NOT delete .PROJECT_CONTEXT.md (it's reference doc, not part of product)."
        )
    else:
        full_task = task

    # Используем существующий gemini_code create через job_runner напрямую
    from tools import job_runner
    if job_runner.active_count() >= 6:
        return {"ok": False, "error": "too_many_active",
                "say_to_user": "У меня уже шесть задач в работе, подожди."}

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    iterate = bool(list(product_dir.iterdir()))  # если есть файлы → iterate
    payload = {
        "task": full_task,
        "workspace": str(product_dir),
        "slug": meta.get("id", "project"),
        "timestamp": timestamp,
        "timeout": 3600,
        "use_mcp": False,
        "deliver": "phone",
        "want_preview": None,
    }
    kind = "gemini_code_iterate" if iterate else "gemini_code_create"
    label = f"{'правка' if iterate else 'код'} {meta.get('name')[:30]}"
    session_id = args.get("_session_id") or "phone-misha-main"
    task_id = job_runner.submit(kind, payload, session_id=session_id, short_label=label)
    return {"ok": True, "action": "build", "task_id": task_id,
            "say_to_user": f"Принял, кодинг идёт в фоне для «{meta.get('name')}». Скажу когда готово."}


# ---------------------------------------------------------------------------
# Autopilot: пройти весь 04-tasks.md сам (build → verify → mark done → отчёт)
# ---------------------------------------------------------------------------

_UNCHECKED_RE = re.compile(r"^\s*[-*]\s*\[ \]\s*(.+)$")


def _next_unchecked_task(tasks_md: Path):
    """Вернуть (raw_line, task_text) первой невыполненной задачи или (None, None)."""
    try:
        content = tasks_md.read_text(encoding="utf-8")
    except Exception:
        return None, None
    for line in content.splitlines():
        m = _UNCHECKED_RE.match(line)
        if m:
            raw = m.group(1).strip()
            title = raw
            mm = re.match(r"\*?\*?(.+?)\*?\*? — ", raw)
            if mm:
                title = mm.group(1).strip()
            # Возвращаем полный текст задачи (для контекста) + короткий title
            return line, raw, title
    return None, None, None


def _mark_task_checked(tasks_md: Path, raw_line: str) -> bool:
    """Заменить '- [ ]' → '- [x]' в конкретной строке. Идемпотентно."""
    try:
        content = tasks_md.read_text(encoding="utf-8")
    except Exception:
        return False
    if raw_line not in content:
        return False
    checked = raw_line.replace("[ ]", "[x]", 1)
    content = content.replace(raw_line, checked, 1)
    try:
        tasks_md.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def _count_tasks(tasks_md: Path):
    """Вернуть (done, total) по чекбоксам."""
    try:
        content = tasks_md.read_text(encoding="utf-8")
    except Exception:
        return 0, 0
    total = len(re.findall(r"^\s*[-*]\s*\[[ xX]\]", content, re.MULTILINE))
    done = len(re.findall(r"^\s*[-*]\s*\[[xX]\]", content, re.MULTILINE))
    return done, total


def _write_project_state(project_path: Path, *, done: List[str], failed: List[str],
                         remaining: int, build: Optional[Dict[str, Any]] = None,
                         deploy_url: Optional[str] = None,
                         paused_network: bool = False) -> None:
    """Авто-саммари хода проекта → <project>/.STATE.md (B2, память/контекст).

    Сжатый «где мы сейчас» после прогона автопилота: фаза, прогресс задач,
    последние сделанные, статус сборки, деплой. Читается в
    get_active_project_summary() и инжектится в system prompt — чтобы Тройка
    знала текущее состояние проекта без расспросов и без чтения всего docs/.
    Идемпотентно: каждый прогон перезаписывает файл целиком.
    """
    try:
        meta = _read_meta(project_path)
        name = meta.get("name", project_path.name)
        lines = [
            f"# .STATE.md — {name}",
            f"_обновлено: {datetime.now():%Y-%m-%d %H:%M}_",
            "",
            f"- фаза: {meta.get('phase', '—')}",
            f"- сделано задач за последний прогон: {len(done)}",
            f"- осталось задач: {remaining}",
        ]
        if failed:
            lines.append(f"- не вышли: {len(failed)} ({', '.join(failed[:3])[:120]})")
        if done:
            lines.append(f"- последние сделанные: {', '.join(done[-3:])[:160]}")
        if build and build.get("checked"):
            lines.append("- сборка: "
                         + ("ОК" + (" (правил ошибки)" if build.get("fixed") else "")
                            if build.get("ok") else "ЕСТЬ ОШИБКИ — нужна доработка"))
        if deploy_url:
            lines.append(f"- деплой: {deploy_url}")
        if paused_network:
            lines.append("- статус: на паузе (сеть нестабильна)")
        (project_path / ".STATE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        logger.debug("write .STATE.md failed: %s", e)


def _read_project_state_brief(project_path: Path, max_chars: int = 360) -> str:
    """Компактная выжимка .STATE.md для инжекта (без заголовка/служебных строк)."""
    f = project_path / ".STATE.md"
    if not f.exists():
        return ""
    try:
        txt = f.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    bullets = [ln.strip() for ln in txt.splitlines()
               if ln.strip().startswith("- ")]
    brief = " ".join(b.lstrip("- ") for b in bullets)
    return brief[:max_chars]


async def _notify_progress(session_id: Optional[str], text: str, task_id: str = "") -> None:
    """Промежуточный голосовой отчёт автопилота (как heartbeat — не дублируется в историю).

    КРИТИЧНО: уведомление НЕОБЯЗАТЕЛЬНО и НЕ должно блокировать сборку. У phone_bridge
    .send_command нет таймаута на сам ws.send_json — если телефон «connected», но сокет
    мёртв, send_json виснет навсегда и вешает весь автопилот ещё до запуска gemini.
    Поэтому жёстко ограничиваем всю отправку через wait_for.
    """
    import asyncio as _aio

    async def _send() -> None:
        try:
            from gateway.platforms.phone_bridge import bridge
            if bridge.is_connected():
                await _aio.wait_for(
                    bridge.send_command("notify_voice", {
                        "text": text[:200],
                        "task_id": task_id,
                        "kind": "project_autopilot",
                        "is_heartbeat": True,
                    }, timeout=5),
                    timeout=8,
                )
        except Exception as e:
            logger.debug("autopilot notify failed/skip: %s", e)

    # Fire-and-forget: уведомление НИКОГДА не должно блокировать проход автопилота.
    # Планируем отправку фоном и сразу выходим — даже если bridge висит, сборка идёт.
    try:
        _aio.get_running_loop().create_task(_send())
    except Exception:
        pass


def _build_context_file(project_path: Path, product_dir: Path, meta: Dict[str, Any]) -> None:
    """Собрать .PROJECT_CONTEXT.md из готовых доков (один раз перед циклом)."""
    parts = []
    for ph in ["discovery", "requirements", "architecture", "tasks"]:
        rel = _PHASE_DOCS.get(ph)
        if rel and (project_path / rel).exists():
            parts.append(f"## {ph}\n" + (project_path / rel).read_text(encoding="utf-8"))
    if not parts:
        return
    ctx_file = product_dir / ".PROJECT_CONTEXT.md"
    ctx_file.write_text(
        f"# Project context for coding\n\nProject: {meta.get('name')}\nPhase: building\n\n"
        f"---\n\n" + "\n\n".join(parts) + "\n",
        encoding="utf-8",
    )


def _stitch_mcp_call(method: str, params: Dict[str, Any], key: str, timeout: int = 150) -> Dict[str, Any]:
    """Один JSON-RPC вызов к Stitch MCP (streamable HTTP). Синхронный — звать через to_thread."""
    import urllib.request
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        "https://stitch.googleapis.com/mcp", data=body,
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "X-Goog-Api-Key": key})
    raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    if "data:" in raw[:20]:  # SSE-обёртка
        for ln in raw.splitlines():
            if ln.startswith("data:"):
                raw = ln[5:].strip()
                break
    return json.loads(raw)


async def _maybe_stitch_design(product_dir: Path, name: str, summary: str,
                               device: str = "MOBILE") -> bool:
    """Если есть STITCH_API_KEY — генерим дизайн в Google Stitch ПРЯМЫМ вызовом
    API (не через MCP-тулзы gemini, на которых flash падает) и кладём текстовый
    спек в .STITCH_DESIGN.md. Кодер читает его как обычный контекст.
    Best-effort: любая ошибка → просто пропускаем (работаем по anti-AI-slop).
    """
    import os
    key = os.environ.get("STITCH_API_KEY")
    if not key:
        return False
    design_file = product_dir / ".STITCH_DESIGN.md"
    if design_file.exists() and design_file.stat().st_size > 200:
        return True  # уже сгенерён в прошлом проходе
    import asyncio as _aio
    try:
        cp = await _aio.to_thread(_stitch_mcp_call, "tools/call",
                                  {"name": "create_project", "arguments": {"title": name[:80]}}, key, 40)
        pid = cp.get("result", {}).get("structuredContent", {}).get("name", "")
        pid = pid.split("/")[-1]  # 'projects/123' -> '123'
        if not pid:
            return False
        prompt = (f"{name}. {summary}".strip() or name)[:1500]
        gs = await _aio.to_thread(_stitch_mcp_call, "tools/call",
                                  {"name": "generate_screen_from_text",
                                   "arguments": {"projectId": pid, "prompt": prompt, "deviceType": device}}, key, 150)
        res = gs.get("result", {})
        if res.get("isError"):
            logger.warning("stitch generate error: %s", str(res)[:200])
            return False
        data = json.loads(res["content"][0]["text"])
        # Достаём дизайн-систему из первого компонента, где она есть.
        ds = None
        for comp in data.get("outputComponents", []):
            d = (comp.get("designSystem") or {}).get("designSystem")
            if d and d.get("styleGuidelines"):
                ds = d
                break
        if not ds:
            return False
        theme = ds.get("theme", {})
        colors = theme.get("namedColors", {})
        color_lines = "\n".join(f"- {k}: {v}" for k, v in sorted(colors.items()))
        md = (
            f"# Google Stitch design spec — «{name}»\n"
            f"(Сгенерировано Stitch на Gemini 3. РЕАЛИЗУЙ этот дизайн точно: палитра, "
            f"шрифты, отступы, скругления. Это source of truth для визуала.)\n\n"
            f"## Design system: {ds.get('displayName','')}\n"
            f"- colorMode: {theme.get('colorMode','')}\n"
            f"- headlineFont: {theme.get('headlineFont','')}\n"
            f"- bodyFont: {theme.get('bodyFont','')}\n"
            f"- labelFont: {theme.get('labelFont','')}\n"
            f"- roundness: {theme.get('roundness','')}\n\n"
            f"## Style guidelines\n{ds.get('styleGuidelines','')}\n\n"
            f"## Color palette (Material 3 named colors)\n{color_lines}\n"
        )
        design_file.write_text(md, encoding="utf-8")
        logger.info("stitch design written: %d chars, %d colors", len(md), len(colors))
        return True
    except Exception as e:
        logger.warning("stitch design skipped: %s", e)
        return False


async def _static_check(product_dir: Path, timeout: int = 240) -> Dict[str, Any]:
    """Локальная статическая проверка по типу проекта. Возвращает
    {ran, ok, kind, errors}. Команды локальные (не жгут сетевой бюджет)."""
    import asyncio as _aio
    import shutil as _sh

    names = {p.name for p in product_dir.iterdir()} if product_dir.exists() else set()

    cmd = None
    kind = None
    if "pubspec.yaml" in names:
        flutter = _sh.which("flutter") or _sh.which("flutter.bat")
        dart = _sh.which("dart")
        if flutter:
            cmd, kind = [flutter, "analyze", "--no-pub"], "flutter"
        elif dart:
            cmd, kind = [dart, "analyze"], "dart"
    elif "package.json" in names:
        try:
            import json as _json
            pj = _json.loads((product_dir / "package.json").read_text(encoding="utf-8"))
            scripts = pj.get("scripts", {})
        except Exception:
            scripts = {}
        npm = _sh.which("npm") or _sh.which("npm.cmd")
        npx = _sh.which("npx") or _sh.which("npx.cmd")
        if "build" in scripts and npm:
            cmd, kind = [npm, "run", "build", "--if-present"], "node-build"
        elif "tsconfig.json" in names and npx:
            cmd, kind = [npx, "tsc", "--noEmit"], "tsc"
    elif any(n.endswith(".py") for n in names) or "requirements.txt" in names:
        py = _sh.which("python") or _sh.which("python3")
        if py:
            cmd, kind = [py, "-m", "compileall", "-q", "."], "python"

    if not cmd:
        return {"ran": False, "ok": True, "kind": "none", "errors": ""}

    log = product_dir / ".verify_check.log"
    try:
        f = open(log, "wb")
    except Exception as e:
        return {"ran": False, "ok": True, "kind": kind, "errors": f"log_open: {e}"}
    try:
        proc = await _aio.create_subprocess_exec(
            *cmd, cwd=str(product_dir), stdout=f, stderr=f,
        )
        from tools.gemini_code_tool import _wait_proc_or_kill
        rc = await _wait_proc_or_kill(proc, timeout)
        if rc is None:
            return {"ran": True, "ok": True, "kind": kind, "errors": "",
                    "note": "check_timed_out"}
    finally:
        try: f.close()
        except Exception: pass

    out = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    return {"ran": True, "ok": rc == 0, "kind": kind, "errors": out[-3000:]}


async def _verify_and_fix(product_dir: Path, timeout: int) -> Dict[str, Any]:
    """Самопроверка по типу проекта: web → playwright-консоль; flutter/dart/node/py →
    статический анализ/сборка. Ошибки скармливаем gemini для точечной починки."""
    from tools.gemini_code_tool import _run_gemini
    from tools.gemini_code_tool import _list_files as _lf

    # Веб-проект: проверяем рантайм через playwright MCP (как раньше).
    if "index.html" in _lf(product_dir):
        verify_task = (
            "VERIFY & FIX MODE (do NOT redesign, do NOT add features).\n"
            "A site/app was just built in this directory. Your job is quality control:\n"
            "1. Use the 'playwright' MCP server to open the built result "
            "(open index.html via file:// URL, or start a quick static server if needed).\n"
            "2. Read the browser console. Look for JS exceptions, 404s, failed fetches, "
            "broken images, and obviously broken/empty layout.\n"
            "3. If you find real errors — FIX them directly in the code files. "
            "Apply HTTP-by-IP fallbacks (crypto.randomUUID, navigator.clipboard) if missing.\n"
            "4. If everything renders and console is clean — change nothing.\n"
            "Report in 1-2 lines what you found and fixed. Do NOT delete .PROJECT_CONTEXT.md."
        )
        return await _run_gemini(product_dir, verify_task, timeout, iterate=True, use_mcp=True)

    # Прочие типы: локальная статическая проверка → при ошибках один fix-pass.
    check = await _static_check(product_dir, timeout=min(timeout, 300))
    if not check.get("ran") or check.get("ok"):
        return {"ok": True, "verified": check.get("kind"), "fixed": False}

    errors = (check.get("errors") or "")[-2500:]
    fix_task = (
        "FIX-COMPILE MODE (do NOT redesign, do NOT add features).\n"
        f"The {check.get('kind')} static check FAILED in this directory. "
        "Fix ONLY the compile/analyzer errors below — edit the code files in place, "
        "do not delete unrelated files, do not run servers or watchers.\n\n"
        f"=== CHECK OUTPUT (tail) ===\n{errors}\n=== END ==="
    )
    fix = await _run_gemini(product_dir, fix_task, timeout, iterate=True, use_mcp=False)
    return {"ok": fix.get("ok", False), "verified": check.get("kind"), "fixed": True}


async def _final_build_gate(product_dir: Path, timeout: int) -> Dict[str, Any]:
    """Финальный gate перед деплоем: «проект реально собирается».

    После цикла задач один раз гоняем статическую сборку/анализ по типу проекта
    (для flutter — `flutter analyze`). Если красный — ОДИН fix-pass и на pro
    (malformed-устойчивая модель), затем перепроверка. Возвращаем строгий
    статус, чтобы итог честно говорил «собирается / есть ошибки сборки», а не
    рапортовал «готово» поверх несобираемого кода (как в тестах 2-5 июня).

    Возвращает {checked: bool, ok: bool, kind, fixed: bool, errors_tail}.
    `checked=False` — для типа проекта нет локальной проверки (напр. чистый
    web/index.html): тогда не блокируем и не врём про статус сборки.
    """
    from tools.gemini_code_tool import _run_gemini_resilient

    check = await _static_check(product_dir, timeout=min(timeout, 300))
    if not check.get("ran"):
        return {"checked": False, "ok": True, "kind": check.get("kind", "none"),
                "fixed": False, "errors_tail": ""}
    if check.get("ok"):
        return {"checked": True, "ok": True, "kind": check.get("kind"),
                "fixed": False, "errors_tail": ""}

    # Красный анализ → один прицельный fix-pass на pro (flash валит сложные правки).
    errors = (check.get("errors") or "")[-2500:]
    fix_task = (
        "FINAL BUILD-GATE FIX (do NOT redesign, do NOT add features).\n"
        f"The {check.get('kind')} build/analyze FAILED. Fix ONLY the errors below — "
        "edit code files in place so the project compiles/analyzes cleanly. "
        "Do not delete unrelated files, do not run servers or watchers.\n\n"
        f"=== BUILD OUTPUT (tail) ===\n{errors}\n=== END ==="
    )
    try:
        await _run_gemini_resilient(
            product_dir, fix_task, timeout, iterate=True, use_mcp=False,
            stall_timeout=180, escalate_model="gemini-2.5-pro", max_attempts=2,
        )
    except Exception as e:
        logger.debug("build-gate fix-pass failed: %s", e)

    recheck = await _static_check(product_dir, timeout=min(timeout, 300))
    return {
        "checked": True,
        "ok": bool(recheck.get("ok")),
        "kind": recheck.get("kind"),
        "fixed": True,
        "errors_tail": (recheck.get("errors") or "")[-1200:] if not recheck.get("ok") else "",
    }


async def _deploy_product(project_path: Path, *, git: bool = True, vercel: bool = True,
                          timeout: int = 300) -> Dict[str, Any]:
    """git init+commit и/или vercel --prod для product/ проекта. Возвращает dict с url."""
    import asyncio as _asyncio
    import shutil as _shutil
    product_dir = project_path / "product"
    if not product_dir.exists() or not any(product_dir.iterdir()):
        return {"ok": False, "error": "no_product"}

    out: Dict[str, Any] = {"ok": True, "git": None, "url": None}

    # --- git init + commit (короткие команды, PIPE безопасен) ---
    if git:
        git_cli = _shutil.which("git")
        if not git_cli:
            out["git"] = {"ok": False, "error": "git_not_found"}
        else:
            async def _git(*cmd) -> int:
                try:
                    proc = await _asyncio.create_subprocess_exec(
                        git_cli, *cmd, cwd=str(product_dir),
                        stdout=_asyncio.subprocess.PIPE, stderr=_asyncio.subprocess.PIPE,
                    )
                    await _asyncio.wait_for(proc.communicate(), timeout=60)
                    return proc.returncode or 0
                except Exception as e:
                    logger.debug("git %s failed: %s", cmd, e)
                    return 1
            if not (product_dir / ".git").exists():
                await _git("init")
                await _git("config", "user.email", "troika@local")
                await _git("config", "user.name", "Troika")
                # .gitignore чтобы не коммитить служебные файлы
                gi = product_dir / ".gitignore"
                if not gi.exists():
                    gi.write_text(
                        ".PROJECT_CONTEXT.md\n.CODE_TASK.md\n.PM_TASK.md\n.STITCH_DESIGN.md\n"
                        ".gemini_run.log\n.gemini_run.err\n.vercel_deploy.log\n"
                        ".vercel_deploy.err\nnode_modules/\n.vercel/\n",
                        encoding="utf-8",
                    )
            await _git("add", "-A")
            rc = await _git("commit", "-m", f"autopilot build {datetime.now():%Y-%m-%d %H:%M}")
            out["git"] = {"ok": rc == 0}

    # --- vercel deploy (длинный CLI — стрим в файл, через gemini_code хелпер) ---
    if vercel:
        try:
            from tools.gemini_code_tool import _deploy_vercel, _save_deploy_url
            res = await _deploy_vercel(product_dir, timeout=timeout)
            if res.get("ok") and res.get("url"):
                out["url"] = res["url"]
                try:
                    _save_deploy_url(product_dir, res["url"])
                except Exception:
                    pass
            else:
                out["vercel_error"] = res.get("error")
        except Exception as e:
            out["vercel_error"] = str(e)

    return out


async def _do_autopilot_work(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Проходит весь 04-tasks.md: build → (verify) → mark done → отчёт. В конце опц. deploy."""
    import time as _time
    from tools.gemini_code_tool import (
        _run_gemini_resilient, _list_files, _reap_orphan_gemini,
    )

    project_path = Path(payload["project_path"])
    product_dir = project_path / "product"
    product_dir.mkdir(exist_ok=True)
    meta = _read_meta(project_path)
    name = meta.get("name", project_path.name)
    session_id = payload.get("session_id")
    verify = bool(payload.get("verify", True))
    deploy = bool(payload.get("deploy", False))
    per_task_timeout = int(payload.get("per_task_timeout", 1800))
    overall_timeout = int(payload.get("timeout", 21600))
    max_tasks = int(payload.get("max_tasks", 30))

    tasks_md = project_path / "docs" / "04-tasks.md"
    if not tasks_md.exists():
        return {"ok": False, "error": "no_tasks",
                "say_to_user": f"В проекте «{name}» нет 04-tasks.md."}

    _build_context_file(project_path, product_dir, meta)

    # Дизайн от Google Stitch (один раз, прямым вызовом API — не через MCP-тулзы,
    # на которых flash падает). Кладёт .STITCH_DESIGN.md, кодер читает как текст.
    stitch_ok = False
    try:
        await _notify_progress(session_id, f"«{name}»: генерю дизайн в Stitch…")
        # Жёсткий общий таймаут: urllib.timeout — это таймаут на сокет, не на
        # всю операцию. Stitch генерит через Gemini 3 медленно и может висеть,
        # блокируя автопилот ДО сборки. Не даём дизайн-шагу повесить весь job.
        import asyncio as _aio
        stitch_ok = await _aio.wait_for(
            _maybe_stitch_design(product_dir, name, meta.get("summary", "")),
            timeout=150,
        )
    except Exception as e:
        logger.info("stitch design step skipped (%s) — строю по anti-AI-slop", e)

    start = _time.time()
    done_tasks: List[str] = []
    failed_tasks: List[str] = []
    attempted: set = set()          # raw_line задач, которые уже брали (анти-зацикливание)
    consecutive_net_fail = 0        # подряд идущих сетевых стопоров → ранний аборт
    net_aborted = False

    for i in range(max_tasks):
        # Бюджет времени: оставляем место хотя бы на одну задачу + verify
        elapsed = _time.time() - start
        if elapsed > overall_timeout - per_task_timeout:
            logger.info("autopilot time budget exhausted after %ds", int(elapsed))
            break

        raw_line, task_text, title = _next_unchecked_task(tasks_md)
        if not task_text:
            break  # всё выполнено

        # Анти-зацикливание: если _mark_task_checked не сработал и нам вернули ту же
        # строку повторно — принудительно отмечаем её и идём дальше, не зависаем.
        if raw_line in attempted:
            if not _mark_task_checked(tasks_md, raw_line):
                logger.warning("autopilot: cannot advance past task, breaking: %r", title)
                failed_tasks.append(title)
                break
            continue
        attempted.add(raw_line)

        done_n, total_n = _count_tasks(tasks_md)
        await _notify_progress(
            session_id,
            f"«{name}»: задача {done_n + 1} из {total_n} — {title[:50]}",
        )

        stitch_line = (
            "DESIGN: read .STITCH_DESIGN.md — it's the Google Stitch design spec "
            "(palette, fonts, spacing). Implement the UI to match it exactly. "
            if stitch_ok else ""
        )
        full_task = (
            f"BEFORE CODING: read .PROJECT_CONTEXT.md in current directory — "
            f"it has vision, requirements, architecture, full task list.\n"
            f"{stitch_line}\n"
            f"CODING TASK (one item from the plan): {task_text}\n"
            f"Working directory: {product_dir}. Build/extend the product here, "
            f"integrating with code already present. "
            f"Do NOT delete .PROJECT_CONTEXT.md or .STITCH_DESIGN.md."
        )
        files_before = set(_list_files(product_dir))
        iterate = bool([p for p in product_dir.iterdir()
                        if p.is_file() and not p.name.startswith(".")])
        # stall_timeout=180: при реальной работе gemini постоянно стримит вывод/
        # пишет файлы (это сбрасывает счётчик простоя), так что 3 мин полной тишины
        # = либо headless-зависание после завершения, либо обрыв сети. Не ждём 7 мин.
        # ВАЖНО: НЕ даём gemini сами MCP-тулзы Stitch — gemini-2.5-flash на их
        # сложных схемах выдаёт malformed tool call и падает ([ERROR] Invalid
        # stream), что валит весь шаг сборки. Поэтому кодер работает без MCP.
        # TODO(stitch): дизайн от Stitch генерить ДО цикла прямым вызовом API
        # (см. _maybe_stitch_design) и класть в .STITCH_DESIGN.md как контекст —
        # flash читает текстовый спек нормально, ломается только на tool-call.
        # resilient-обёртка: на «Invalid stream» (malformed tool call) flash без
        # файлового прогресса — ретраим, на последней попытке эскалируем на
        # gemini-2.5-pro. Сетевые стопоры наверх не ретраятся (их ловит
        # consecutive_net_fail ниже). См. autopilot-flash-invalid-stream.
        res = await _run_gemini_resilient(product_dir, full_task, per_task_timeout,
                                          iterate=iterate, use_mcp=False,
                                          stall_timeout=180)
        files_after = set(_list_files(product_dir))
        # Прогресс = реально новые файлы ЛИБО чистый ok (НЕ malformed). rc==0 при
        # malformed-обрыве ≠ код написан — иначе задача ложно списывается как
        # сделанная (та же ловушка, что чинил resilient). См. autopilot-flash-invalid-stream.
        new_files = bool(files_after - files_before)
        made_progress = new_files or (res.get("ok") and not res.get("malformed"))

        # Сетевой/стоп-детектор: gemini завис без активности или сеть рвётся.
        # Несколько таких подряд = сеть лежит → нет смысла крутить вхолостую.
        net_failed = (not res.get("ok")) and (
            res.get("stalled")
            or "ECONNRESET" in (res.get("stderr_tail") or "")
            or "ETIMEDOUT" in (res.get("stderr_tail") or "")
            or "RESOURCE_EXHAUSTED" in (res.get("stderr_tail") or "")
            or "429" in (res.get("stderr_tail") or "")
        )
        if net_failed and not made_progress:
            consecutive_net_fail += 1
        else:
            consecutive_net_fail = 0
        if consecutive_net_fail >= 3:
            net_aborted = True
            logger.warning("autopilot aborting: %d network stalls in a row", consecutive_net_fail)
            await _notify_progress(
                session_id,
                f"«{name}»: сеть нестабильна, ставлю автопилот на паузу. "
                f"Скажи «продолжай», когда сеть будет получше.",
            )
            break

        if not res.get("ok") and not made_progress:
            failed_tasks.append(title)
            await _notify_progress(session_id,
                                   f"Задача «{title[:40]}» не пошла, перехожу к следующей.")
            # не зацикливаемся: помечаем чтобы не брать снова
            _mark_task_checked(tasks_md, raw_line)
            continue

        # Самопроверка + починка (Direction 3) — для любого типа проекта
        if verify:
            try:
                await _verify_and_fix(product_dir, min(per_task_timeout, 900))
            except Exception as e:
                logger.debug("verify pass failed: %s", e)

        _mark_task_checked(tasks_md, raw_line)
        done_tasks.append(title)

    # Финальный build-gate (B1): «проект реально собирается» перед деплоем/итогом.
    # Один проход статической сборки по типу проекта; красный flutter analyze →
    # fix-pass на pro → перепроверка. Не блокируем деплой жёстко (web-проекты
    # выкатываются и с ворнингами), но статус сборки честно уходит в say_to_user.
    build = {"checked": False, "ok": True}
    if done_tasks and not net_aborted:
        try:
            await _notify_progress(session_id, f"«{name}»: проверяю, что собирается…")
            build = await _final_build_gate(product_dir, min(per_task_timeout, 900))
        except Exception as e:
            logger.warning("autopilot build-gate failed: %s", e)
            build = {"checked": False, "ok": True, "error": str(e)}

    # Финальный деплой (Direction 4)
    deploy_url = None
    if deploy and done_tasks:
        await _notify_progress(session_id, f"«{name}»: задачи готовы, деплою.")
        try:
            dep = await _deploy_product(project_path, git=True, vercel=True, timeout=300)
            deploy_url = dep.get("url")
        except Exception as e:
            logger.warning("autopilot deploy failed: %s", e)

    # Watchdog (B1): добить осиротевшие gemini/node-деревья этого workspace.
    # taskkill /T в _wait_proc_or_kill не всегда достаёт ConPTY-внуков — зомби
    # 5 июня. Чистим по командной строке, безопасно (старше 30с, только наш ws).
    try:
        _reap_orphan_gemini(product_dir, min_age_s=30.0)
    except Exception as e:
        logger.debug("orphan reaper at job end skipped: %s", e)

    done_n, total_n = _count_tasks(tasks_md)
    remaining = total_n - done_n

    # Авто-саммари хода проекта → .STATE.md (B2): инжектится в system prompt,
    # чтобы Тройка знала текущее состояние без расспросов.
    _write_project_state(
        project_path, done=done_tasks, failed=failed_tasks, remaining=remaining,
        build=build, deploy_url=deploy_url, paused_network=net_aborted,
    )

    if net_aborted:
        say = (f"Автопилот по «{name}» на паузе: сеть нестабильна. "
               f"Сделал {len(done_tasks)} задач, осталось {remaining}. "
               f"Скажи «продолжай», когда сеть будет получше.")
    else:
        parts = [f"Автопилот по «{name}» завершён", f"сделал {len(done_tasks)} задач"]
        if failed_tasks:
            parts.append(f"{len(failed_tasks)} не вышли")
        if remaining > 0:
            parts.append(f"осталось {remaining} (запусти ещё раз)")
        # Статус сборки из build-gate — честно, а не «готово» поверх несобираемого.
        if build.get("checked"):
            if build.get("ok"):
                parts.append("проект собирается" + (" (поправил ошибки)"
                             if build.get("fixed") else ""))
            else:
                parts.append("но есть ошибки сборки — нужна доработка")
        if deploy_url:
            parts.append("сайт задеплоен")
        say = ". ".join(parts) + "."

    return {
        "ok": True, "action": "autopilot",
        "project_path": str(project_path),
        "done": done_tasks, "failed": failed_tasks,
        "remaining": remaining, "deploy_url": deploy_url,
        "paused_network": net_aborted,
        "build_ok": bool(build.get("ok")) if build.get("checked") else None,
        "build_kind": build.get("kind"),
        "workspace": str(product_dir),
        "say_to_user": say,
        "next_action_hint": "open" if deploy_url else None,
    }


async def _do_deploy_work(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Фоновый деплой проекта: git commit + vercel --prod."""
    project_path = Path(payload["project_path"])
    meta = _read_meta(project_path)
    name = meta.get("name", project_path.name)
    dep = await _deploy_product(
        project_path,
        git=bool(payload.get("git", True)),
        vercel=bool(payload.get("vercel", True)),
        timeout=int(payload.get("timeout", 300)),
    )
    if not dep.get("ok"):
        return {"ok": False, "error": dep.get("error", "deploy_failed"),
                "say_to_user": f"Не получилось задеплоить «{name}»: код ещё не написан."}
    url = dep.get("url")
    if url:
        return {"ok": True, "action": "deploy", "url": url,
                "workspace": str(project_path / "product"),
                "say_to_user": f"Задеплоил «{name}». Открыть сайт?",
                "next_action_hint": "open"}
    return {"ok": True, "action": "deploy",
            "git": dep.get("git"), "vercel_error": dep.get("vercel_error"),
            "say_to_user": (
                f"Закоммитил «{name}» в git, но Vercel не дал ссылку — "
                f"возможно нужен vercel login."
            )}


# ---------------------------------------------------------------------------
# Actions: autopilot + deploy
# ---------------------------------------------------------------------------

async def _action_autopilot(args: Dict[str, Any]) -> Dict[str, Any]:
    """Запустить автономное прохождение всех задач проекта в фоне."""
    active = _load_active()
    if not active:
        return {"ok": False, "error": "no_active_project",
                "say_to_user": "Сначала открой или создай проект."}
    project_path = Path(active["path"])
    meta = _read_meta(project_path)
    name = meta.get("name", project_path.name)
    tasks_md = project_path / "docs" / "04-tasks.md"
    if not tasks_md.exists():
        return {"ok": False, "error": "no_tasks",
                "say_to_user": "Сначала сгенерируй задачи — скажи 'сгенерируй задачи'."}
    raw_line, task_text, _title = _next_unchecked_task(tasks_md)
    if not task_text:
        return {"ok": True, "say_to_user": f"В «{name}» все задачи уже выполнены."}

    from tools import job_runner
    if job_runner.active_count() >= 6:
        return {"ok": False, "error": "too_many_active",
                "say_to_user": "У меня уже шесть задач в работе, подожди."}

    # phase → building, раз пошёл код
    if meta.get("phase") != "building":
        meta["phase"] = "building"
        _write_meta(project_path, meta)
        active["phase"] = "building"
        _save_active(active)

    session_id = args.get("_session_id") or "phone-misha-main"
    verify = args.get("verify")
    verify = True if verify is None else bool(verify)
    deploy = bool(args.get("deploy", False))
    payload = {
        "project_path": str(project_path),
        "verify": verify,
        "deploy": deploy,
        "per_task_timeout": 1800,
        "timeout": 21600,
        "max_tasks": int(args.get("max_tasks", 30)),
        "session_id": session_id,
    }
    label = f"автопилот {name[:30]}"
    task_id = job_runner.submit("project_autopilot", payload,
                                session_id=session_id, short_label=label)
    done_n, total_n = _count_tasks(tasks_md)
    tail = " В конце задеплою." if deploy else ""
    return {"ok": True, "action": "autopilot", "task_id": task_id,
            "say_to_user": (
                f"Запускаю автопилот по «{name}»: пройду все {total_n} задач сам, "
                f"буду отчитываться по ходу.{tail} Скажу когда всё готово."
            )}


async def _action_deploy_project(args: Dict[str, Any]) -> Dict[str, Any]:
    """Задеплоить продукт активного проекта (git + vercel) в фоне."""
    active = _load_active()
    if not active:
        return {"ok": False, "error": "no_active_project",
                "say_to_user": "Сначала открой или создай проект."}
    project_path = Path(active["path"])
    meta = _read_meta(project_path)
    name = meta.get("name", project_path.name)
    product_dir = project_path / "product"
    if not product_dir.exists() or not any(
        p for p in product_dir.iterdir() if p.is_file() and not p.name.startswith(".")
    ):
        return {"ok": False, "error": "no_product",
                "say_to_user": f"В «{name}» ещё нет кода — нечего деплоить."}

    from tools import job_runner
    if job_runner.active_count() >= 6:
        return {"ok": False, "error": "too_many_active",
                "say_to_user": "У меня уже шесть задач в работе, подожди."}
    session_id = args.get("_session_id") or "phone-misha-main"
    payload = {
        "project_path": str(project_path),
        "git": True,
        "vercel": True,
        "timeout": 300,
    }
    label = f"деплой {name[:30]}"
    task_id = job_runner.submit("project_deploy", payload,
                                session_id=session_id, short_label=label)
    return {"ok": True, "action": "deploy", "task_id": task_id,
            "say_to_user": f"Деплою «{name}» в фоне — git коммит и Vercel. Скажу когда будет ссылка."}


# ---------------------------------------------------------------------------
# PM-доc handler (для job_runner)
# ---------------------------------------------------------------------------

async def _do_pm_doc_work(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Запуск PM-агента (Gemini-cli с GEMINI-PM.md) в папке проекта."""
    project_path = Path(payload["project_path"])
    task = payload["task"]
    timeout = int(payload.get("timeout", 600))

    # Используем env-var GEMINI_SYSTEM_MD на PM-промпт, и нашу обёртку запуска gemini-cli
    import asyncio as _asyncio
    import os as _os
    from tools.gemini_code_tool import _find_gemini_cli

    cli = _find_gemini_cli()
    if not cli:
        return {"ok": False, "error": "gemini_cli_not_found",
                "say_to_user": "Gemini CLI не найден."}

    env = _os.environ.copy()
    env["GEMINI_CLI_TRUST_WORKSPACE"] = "true"
    # node (gemini-cli) предпочитает IPv4 — обход мёртвого IPv6 на нестабильной сети.
    env["NODE_OPTIONS"] = (env.get("NODE_OPTIONS", "") + " --dns-result-order=ipv4first").strip()
    pm_md = Path.home() / ".gemini" / "GEMINI-PM.md"
    if pm_md.exists():
        env["GEMINI_SYSTEM_MD"] = str(pm_md)

    headless_rules = (
        "You are running HEADLESS as a Product Manager / Tech Lead. "
        "Follow ~/.gemini/GEMINI-PM.md for documentation standards. "
        "Do NOT output a plan. Write files directly using file-write tools. "
        "Use ASCII filenames (already structured). Write content in Russian if task is in Russian. "
        "When done — stop, do not summarize at length.\n\n"
    )
    wrapped = headless_rules + task

    # Windows command line ~32K char limit. Если task длинный — пишем в файл
    # и передаём только короткое указание прочитать его.
    if len(wrapped) > 8000:
        task_file = project_path / ".PM_TASK.md"
        task_file.write_text(wrapped, encoding="utf-8")
        wrapped = (
            "Read .PM_TASK.md in current directory — it contains your full instructions "
            "(project context, prior docs, exact task). Execute it. "
            "When done, delete .PM_TASK.md."
        )
        logger.info("PM-agent task written to file (%d chars original)", task_file.stat().st_size)

    logger.info("Spawning PM-agent in %s", project_path)
    # КРИТИЧНО: НЕ используем PIPE + communicate(). gemini-cli (node) держит
    # write-end пайпа открытым через grandchild-процессы (node-pty/conpty),
    # EOF не приходит → communicate() висит вечно, хотя документы уже записаны,
    # и job навсегда застревает в "running". Решение (как в gemini_code._run_gemini):
    # стримим stdout/stderr в файлы и ждём proc.wait() — он возвращается сразу
    # по выходу главного процесса, без ожидания EOF пайпа.
    log_out = project_path / ".pm_run.log"
    log_err = project_path / ".pm_run.err"
    try:
        f_out = open(log_out, "wb")
        f_err = open(log_err, "wb")
    except Exception as e:
        return {"ok": False, "error": f"cannot open log files: {e}",
                "say_to_user": "Не получилось запустить PM-агента."}

    # creationflags=0: child наследует консоль gateway. node-pty conpty-агент
    # пропатчен (не падает на AttachConsole), а CREATE_NO_WINDOW здесь ВРЕДЕН —
    # gemini-cli зависает headless (проверено). См. gemini_code_tool._run_gemini.
    creation_flags = 0
    try:
        proc = await _asyncio.create_subprocess_exec(
            cli, "--yolo", "--allowed-mcp-server-names", "__none__",
            "--prompt", wrapped,
            cwd=str(project_path),
            stdout=f_out, stderr=f_err,
            env=env,
            creationflags=creation_flags,
        )
        try:
            rc = await _asyncio.wait_for(proc.wait(), timeout=timeout)
        except _asyncio.TimeoutError:
            # proc.kill() убивает только верхушку; taskkill /T /F валит всё дерево.
            try:
                import subprocess as _sp
                _sp.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                        capture_output=True, timeout=10)
            except Exception:
                try: proc.kill()
                except Exception: pass
            try:
                await _asyncio.wait_for(proc.wait(), timeout=5)
            except Exception:
                pass
            return {"ok": False, "error": f"timed out after {timeout}s",
                    "say_to_user": "PM-агент не успел, попробуй ещё раз."}
        finally:
            try: f_out.close()
            except Exception: pass
            try: f_err.close()
            except Exception: pass
        if rc != 0:
            err = log_err.read_text(encoding="utf-8", errors="replace") if log_err.exists() else ""
            return {"ok": False, "error": f"gemini-cli exit {rc}",
                    "stderr_tail": err[-500:],
                    "say_to_user": "PM-агент упал. Попробуй переформулировать."}
    except Exception as e:
        try: f_out.close()
        except Exception: pass
        try: f_err.close()
        except Exception: pass
        return {"ok": False, "error": f"spawn failed: {e}",
                "say_to_user": "Не получилось запустить PM-агента."}

    # Узнаём какой doc был обновлён
    meta = _read_meta(project_path)
    phase = meta.get("phase", "discovery")
    doc_rel = _PHASE_DOCS.get(phase)
    doc_exists = doc_rel and (project_path / doc_rel).exists()
    return {
        "ok": True, "phase": phase, "doc": doc_rel,
        "project_path": str(project_path),
        "say_to_user": (
            f"Готов документ {doc_rel}. Прочитать или сразу идём дальше?"
            if doc_exists else
            "PM-агент завершил работу. Посмотри что вышло."
        ),
        "next_action_hint": "read_doc",
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_ACTIONS = {
    "start": _action_start,
    "open": _action_open,
    "close": _action_close,
    "status": _action_status,
    "list": _action_list,
    "add_note": _action_add_note,
    "next_phase": _action_next_phase,
    "generate_doc": _action_generate_doc,
    "build": _action_build,
    "autopilot": _action_autopilot,
    "deploy": _action_deploy_project,
}


async def _handle(args: Dict[str, Any], **_kw) -> str:
    action = (args.get("action") or "status").strip().lower()
    fn = _ACTIONS.get(action)
    if not fn:
        result = {"ok": False, "error": f"unknown action: {action}",
                  "allowed": list(_ACTIONS.keys())}
    else:
        try:
            result = await fn(args)
        except Exception as e:
            logger.exception("project action %s failed", action)
            result = {"ok": False, "error": str(e),
                      "say_to_user": "Что-то пошло не так с проектом."}
    return json.dumps(result, ensure_ascii=False)


SCHEMA = {
    "name": "project",
    "description": (
        "Управление проектами Тройки. Один активный проект за раз. "
        "Фазы: discovery → requirements → architecture → tasks → building. "
        "На фазах 1-4 PM-под-агент пишет документацию (vision, SRS, ADR, tasks). "
        "На building запускается обычный кодинг через gemini_code в product/. "
        "Все async-действия (generate_doc, build) запускаются в фоне с уведомлением голосом по готовности."
    ),
    "parameters": {
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {
                "type": "string",
                "enum": list(_ACTIONS.keys()),
                "description": (
                    "start — создать новый проект и сделать активным. "
                    "open — переключиться на существующий. "
                    "close — выйти из проекта (общий режим). "
                    "status — что сейчас активно. "
                    "list — все проекты. "
                    "add_note — записать идею/требование в notes текущего проекта. "
                    "next_phase — перейти на следующую фазу. "
                    "generate_doc — PM-агент пишет документ текущей фазы (async). "
                    "build — кодинг (async): gemini_code в product/ активного проекта (одна задача). "
                    "autopilot — АВТОНОМНО пройти ВЕСЬ 04-tasks.md по очереди (build→самопроверка→отметка), "
                    "с отчётами голосом по ходу. Используй когда Миша говорит 'делай всё сам', "
                    "'пройди все задачи', 'доведи проект'. Параметр deploy=true — задеплоить в конце. "
                    "deploy — задеплоить готовый продукт (git commit + vercel --prod), вернуть URL."
                ),
            },
            "name": {"type": "string", "description": "Для start/open."},
            "summary": {"type": "string", "description": "Краткое описание для start."},
            "text": {"type": "string", "description": "Текст заметки для add_note."},
            "task": {"type": "string", "description": "Описание кодинг-задачи для build. Если пусто — берёт первую невыполненную из 04-tasks.md."},
            "deploy": {"type": "boolean", "description": "Для autopilot: задеплоить (git+vercel) после всех задач. Default false."},
            "verify": {"type": "boolean", "description": "Для autopilot: самопроверка+починка через playwright после каждой задачи. Default true."},
            "max_tasks": {"type": "integer", "description": "Для autopilot: максимум задач за один прогон. Default 30."},
        },
    },
}


registry.register(
    name="project",
    toolset="gemini_code",  # тот же toolset (вместе с gemini_code, task_status)
    schema=SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="📋",
)


# Регистрация фоновых handler'ов в job_runner
try:
    from tools import job_runner as _job_runner
    _job_runner.register_handler("project_pm_doc", _do_pm_doc_work)
    _job_runner.register_handler("project_autopilot", _do_autopilot_work)
    _job_runner.register_handler("project_deploy", _do_deploy_work)
except Exception as _e:
    logger.warning("project job handlers registration failed: %s", _e)
