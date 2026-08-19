"""
ensure_capability — «нет тула для задачи → сама пишу его и продолжаю задачу».

Идея. Когда Тройка в середине запроса Миши упирается в отсутствие инструмента
(нет `youtube_channel_recent_videos`, нет `hh_vacancy_search`, нет `pdf_ocr`
и т. п.) — она НЕ говорит «не могу». Она вызывает этот tool с описанием
исходной задачи и того, что нужно уметь. Дальше:

  1. Быстрая проверка: может, тул уже есть под похожим именем — не плодим дубли.
  2. Если правда нет — submit в job_runner: под-агент (Claude Code/Gemini CLI)
     пишет tool в git-ветке, green-песочница его проверяет, safe-предложение
     авто-мержится в main, gateway перезапускается.
  3. По готовности Тройка получает push «инструмент X готов — продолжаю задачу»
     + session inject с ОРИГИНАЛЬНЫМ описанием задачи Миши. Следующий turn
     Тройка выполняет исходное с новым tool'ом.

Это тонкий фасад над `self_improve_propose` + `job_runner`. Никакой своей магии —
только один атомарный вызов вместо трёх, чтобы слабая голосовая модель
(deepseek/kimi) не путалась в multi-step.

Anti-loop:
  • Не пропозим если уже есть tool с таким именем в registry.
  • Не пропозим если pending-предложение с тем же slug (это ловит уже
    self_improve_propose, но мы возвращаем понятную reason'у наверх).
  • Не рекурсим сам себя (внутри worker'а нельзя вызывать ensure_capability
    → второй job → и т. д. — это гарантируется тем, что ensure_capability
    не входит в toolset под-агента-кодера, он редактирует файлы напрямую).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

from tools.registry import registry
from tools import job_runner

logger = logging.getLogger(__name__)


def _slug(text: str, max_len: int = 30) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower())[:max_len].strip("-")
    return s or "capability"


def _find_existing_tool(hint: str) -> Optional[str]:
    """Возвращает имя тула из registry, если он уже покрывает нужное.

    Смотрим два случая: точное совпадение имени или подстрока в имени
    (грубая эвристика — 'youtube_channel_recent' поймает
    'youtube_channel_recent_videos'). LLM всё равно валидирует через
    описание, так что ложные срабатывания не критичны."""
    if not hint:
        return None
    norm = re.sub(r"[^a-z0-9_]+", "_", hint.lower()).strip("_")
    if not norm:
        return None
    with registry._lock:
        names = list(registry._tools.keys())
    if norm in names:
        return norm
    # Точное совпадение без tool-суффикса
    for n in names:
        if n == norm or n.rstrip("_tool") == norm:
            return n
    # Подстрока в обе стороны (короткая содержится в длинной, минимум 5 символов —
    # иначе 'note' поймает всё подряд).
    if len(norm) >= 5:
        for n in names:
            if norm in n or n in norm:
                return n
    return None


async def _do_ensure_capability_work(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Job-handler: делает полный self_improve_propose (с auto_verify+auto_apply).

    Возвращает dict, который job_runner положит в notify_voice и в session inject.
    say_to_user на голосе критичен: он и озвучится, и попадёт в history как
    справка для следующего turn."""
    task = (payload.get("task") or "").strip()
    capability = (payload.get("capability") or "").strip()
    spec = (payload.get("spec") or "").strip()
    tool_name = (payload.get("desired_tool_name") or "").strip()

    if not (task and capability):
        return {"ok": False, "error": "missing_task_or_capability",
                "say_to_user": "Не поняла, что именно нужно уметь."}

    # Формируем описание в стиле, который любит self_improve_propose.
    desc_parts = []
    if tool_name:
        desc_parts.append(f"Создай новый tool `{tool_name}`.")
    desc_parts.append(f"Умение: {capability}.")
    if spec:
        desc_parts.append(f"Спецификация: {spec}")
    desc_parts.append(
        "Требования: положить в tools/<name>_tool.py, зарегистрировать через "
        "registry.register (schema с type=object properties, async handler "
        "принимает (arguments, **_kw) и возвращает dict с ok+say_to_user), "
        "toolset='auto_generated'. Открой любой tools/*_tool.py как образец. "
        "Никаких placeholders или TODO — рабочий код с первого прогона."
    )
    description = " ".join(desc_parts)

    rationale = (
        f"Тройка не может выполнить запрос Миши без этого инструмента. "
        f"Исходная задача: {task[:200]}"
    )

    try:
        from tools.self_improve_tool import _handle_propose
    except Exception as e:
        return {"ok": False, "error": f"self_improve_unavailable: {e}",
                "say_to_user": "Не смогла загрузить механизм самоулучшения."}

    logger.info("ensure_capability: proposing %s for task=%r", tool_name or capability, task[:60])
    res = await _handle_propose({
        "description": description,
        "rationale": rationale,
        "auto_verify": True,
    })

    if not res.get("ok"):
        err = res.get("error", "unknown")
        hint = res.get("hint", "")
        # duplicate_proposal — не критично, значит уже пишется. Скажем спокойно.
        if err == "duplicate_proposal":
            return {"ok": True,
                    "already_in_progress": True,
                    "existing_id": res.get("existing_id"),
                    "say_to_user": f"Такой инструмент уже пишу. Проверю через минуту."}
        return {"ok": False, "error": err, "hint": hint,
                "say_to_user": (
                    f"Не получилось написать инструмент: {err}. "
                    f"{('Подсказка: ' + hint) if hint else ''}"
                )}

    pid = res.get("proposal_id")
    files = res.get("files") or []
    new_tool_hint = _guess_new_tool_from_files(files) or tool_name or capability[:30]

    if res.get("auto_applied"):
        # Инструмент в main, gateway перезапустился (self_improve_verify это делает).
        # Инжектим в session чёткую инструкцию «выполни исходную задачу с новым tool».
        say = (
            f"Готово, добавила `{new_tool_hint}`. Возвращаюсь к задаче."
        )
        return {
            "ok": True,
            "auto_applied": True,
            "proposal_id": pid,
            "new_tool": new_tool_hint,
            "files": files,
            "next_action_hint": (
                f"Инструмент `{new_tool_hint}` теперь доступен. "
                f"Выполни ИСХОДНУЮ задачу Миши: {task}. "
                f"Если tool не виден через 5 сек — подожди gateway restart и повтори."
            ),
            "say_to_user": say,
        }

    if res.get("needs_approval"):
        # Risky — Миша должен одобрить голосом «применить N».
        return {
            "ok": True,
            "needs_approval": True,
            "proposal_id": pid,
            "new_tool": new_tool_hint,
            "files": files,
            "say_to_user": (
                f"Написала инструмент {pid}, но правка задевает чувствительное — "
                f"нужно твоё «применить {pid}»."
            ),
        }

    # ok=true, но ни auto_applied ни needs_approval — значит verify упал.
    return {
        "ok": True,
        "verify_failed": True,
        "proposal_id": pid,
        "verify": res.get("verify"),
        "say_to_user": (
            f"Написала инструмент {pid}, но проверка в песочнице не прошла. "
            f"Посмотри через «покажи {pid}»."
        ),
    }


def _guess_new_tool_from_files(files) -> Optional[str]:
    """Из списка изменённых файлов вытащить имя нового tool'а."""
    for f in files or []:
        f = f.replace("\\", "/")
        m = re.match(r"^tools/([a-z0-9_]+)_tool\.py$", f)
        if m:
            return m.group(1)
    return None


# Регистрируем handler в job_runner ДО регистрации самого tool'а —
# иначе submit() внутри _handle_ensure_capability упадёт "unknown job kind".
job_runner.register_handler("ensure_capability", _do_ensure_capability_work)


async def _handle_ensure_capability(arguments: dict, **_kw) -> dict:
    task = (arguments.get("task") or "").strip()
    capability = (arguments.get("capability") or "").strip()
    spec = (arguments.get("spec") or "").strip()
    desired_tool_name = (arguments.get("desired_tool_name") or "").strip()

    if not task:
        return {"ok": False, "error": "missing_task",
                "say_to_user": "Скажи, что именно ты пытаешься сделать — без этого я не пойму, какой инструмент нужен."}
    if not capability:
        return {"ok": False, "error": "missing_capability",
                "say_to_user": "Опиши коротко, что должен уметь новый инструмент."}

    # 1) Не дублируем существующий tool.
    hint = desired_tool_name or capability
    existing = _find_existing_tool(hint)
    if existing:
        return {
            "ok": True,
            "already_exists": True,
            "tool": existing,
            "say_to_user": (
                f"Такой инструмент уже есть — `{existing}`. Использую его."
            ),
        }

    # 2) Лимит параллельных jobs — не забиваем очередь ensure_capability'ями.
    if job_runner.active_count() >= 3:
        return {
            "ok": False,
            "error": "too_many_active_jobs",
            "say_to_user": "У меня уже три задачи в работе — подожди, пока одна освободится.",
        }

    # 3) Submit в job_runner. Возвращаем task_id мгновенно.
    session_id = _kw.get("session_id") or arguments.get("session_id")
    short_label = f"ensure {desired_tool_name or capability[:30]}"
    try:
        task_id = job_runner.submit(
            kind="ensure_capability",
            payload={
                "task": task,
                "capability": capability,
                "spec": spec,
                "desired_tool_name": desired_tool_name,
            },
            session_id=session_id,
            short_label=short_label,
        )
    except Exception as e:
        return {"ok": False, "error": f"submit_failed: {e}",
                "say_to_user": f"Не смогла поставить задачу: {e}"}

    return {
        "ok": True,
        "task_id": task_id,
        "async": True,
        "say_to_user": (
            f"Приняла — сейчас напишу нужный инструмент и продолжу задачу. "
            f"Скажу голосом когда готово, обычно минута-две."
        ),
    }


ENSURE_CAPABILITY_SCHEMA = {
    "name": "ensure_capability",
    "description": (
        "Использовать когда ты упёрлась в ОТСУТСТВУЮЩИЙ инструмент посреди задачи Миши "
        "(нет tool'а для нужного действия — транскрибация ролика, парсинг сайта, "
        "работа с API и т. п.). НЕ говори «не могу» — вызови этот tool: он сам напишет "
        "нужный tool через self_improve_propose + green-песочницу + авто-мерж, потом "
        "перезапустит gateway и продолжит исходную задачу. Возвращает task_id "
        "мгновенно, готовность приходит push'ем на телефон через 1-2 минуты. "
        "НЕ вызывай на «улучши существующий tool» — там self_improve_propose напрямую."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Точная формулировка ИСХОДНОЙ задачи Миши, ради которой нужен новый tool. Именно её Тройка выполнит после того, как tool появится.",
            },
            "capability": {
                "type": "string",
                "description": "Что новый инструмент должен УМЕТЬ (1-2 предложения). Пример: 'взять handle YouTube-канала и вернуть N последних видео (id, title, длительность)'.",
            },
            "spec": {
                "type": "string",
                "description": "Опционально: детали спеки — какие поля/аргументы, откуда брать данные, ожидаемый формат ответа. Помогает под-агенту-кодеру не гадать.",
            },
            "desired_tool_name": {
                "type": "string",
                "description": "Опционально: желаемое snake_case имя нового tool'а (без суффикса _tool). Пример: 'youtube_channel_recent_videos'. Если не задано — под-агент придумает сам.",
            },
        },
        "required": ["task", "capability"],
    },
}


registry.register(
    name="ensure_capability",
    toolset="self_improve",
    schema=ENSURE_CAPABILITY_SCHEMA,
    handler=_handle_ensure_capability,
    is_async=True,
    emoji="🛠️",
)
