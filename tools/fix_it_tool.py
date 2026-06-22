"""
fix_it — ремонтная бригада Тройки. Когда ЧТО УГОДНО сломалось (инструмент завис,
данные не передались, что-то упало) — Тройка зовёт fix_it, а под-агент-ремонтник
находит причину, чинит и возвращает вердикт. Тройка не бросает своё дело.

Идея Миши (20.06): «вот баг/зависание — Тройка даёт задание под-агентам: вот баг,
найдите в чём проблема, почините и передайте мне, я продолжаю». Работает ВЕЗДЕ,
не только в проектах.

Gate по модели: ПОЧИНКУ КОДА (self_improve) запускаем только если активная модель
сильная (qwen/claude). На deepseek/бесплатных бригада только ДИАГНОСТИРУЕТ и
предлагает обход — свой код не трогает (слабая модель наломает дров).

API:
  fix_it(problem="phone_create_video завис, не вернул результат",
         context="что делала когда сломалось", tool="phone_create_video")
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict, Optional
from tools.registry import registry

logger = logging.getLogger(__name__)

# Модели, которым доверяем править собственный код.
_STRONG_MODELS = ("qwen3.7", "qwen3-max", "claude", "opus", "sonnet", "gpt-4", "gpt-5")


def _active_model() -> str:
    """Текущая модель из config (best-effort)."""
    try:
        import io
        for base in (os.environ.get("HERMES_HOME", ""), "/opt/data"):
            p = os.path.join(base, "config.yaml") if base else ""
            if p and os.path.exists(p):
                for line in io.open(p, encoding="utf-8"):
                    s = line.strip()
                    if s.startswith("default:") and not s.startswith("#"):
                        val = s.split("default:", 1)[1]
                        # отрезаем inline-комментарий (# ...)
                        return val.split("#", 1)[0].strip().lower()
    except Exception as e:
        logger.debug("active_model: %s", e)
    return ""


def _is_strong(model: str) -> bool:
    return any(m in model for m in _STRONG_MODELS)


async def _handle(arguments: Dict[str, Any], **_kw) -> Dict[str, Any]:
    problem = (arguments.get("problem") or "").strip()
    context = (arguments.get("context") or "").strip()
    tool = (arguments.get("tool") or "").strip()

    if not problem:
        return {"ok": False, "error": "missing_problem",
                "say_to_user": "Скажи что именно сломалось."}

    model = _active_model()
    can_fix_code = _is_strong(model)

    # Собираем цель для под-агента-ремонтника.
    tool_hint = f" Проблемный инструмент: {tool}." if tool else ""
    if can_fix_code:
        goal = (
            f"РЕМОНТ. Сломалось: {problem}.{tool_hint}\n"
            "Ты — ремонтник. Действуй сам, без вопросов:\n"
            "1. Найди ПРИЧИНУ: посмотри логи (/opt/data/logs/agent.log, errors.log), "
            "при необходимости код инструмента в tools/.\n"
            "2. Определи: это временный сбой (сеть/таймаут/внешний сервис) или "
            "реальный баг в коде?\n"
            "3. Если БАГ В КОДЕ — подготовь фикс через self_improve_propose. "
            "ПРОВЕРЬ свою гипотезу с разных сторон, прежде чем предлагать правку — "
            "не на угад. Если временный — опиши обходной путь.\n"
            "4. Верни КОРОТКИЙ вердикт: причина + что сделал (proposal_id если "
            "создал фикс) + можно ли продолжать."
        )
        toolsets = ["terminal", "self_improve", "delegation"]
    else:
        # слабая модель — НЕ трогаем код, только диагностика + обход
        goal = (
            f"ДИАГНОСТИКА (код НЕ трогать — модель слабая). Сломалось: {problem}.{tool_hint}\n"
            "1. Найди причину по логам (/opt/data/logs/agent.log, errors.log).\n"
            "2. Это временный сбой или баг? \n"
            "3. Предложи ОБХОДНОЙ путь, как сделать то же другим способом.\n"
            "НЕ создавай proposal — только диагноз + обход. Верни коротко."
        )
        toolsets = ["terminal", "delegation"]

    if context:
        goal += f"\n\nКонтекст что делала Тройка: {context}"

    # Делегируем ремонтнику. parent_agent прокидываем чтобы дочерний агент знал родителя.
    try:
        from tools.delegate_tool import delegate_task
        parent = _kw.get("parent_agent")
        result = delegate_task(
            goal=goal,
            toolsets=toolsets,
            role="worker",
            max_iterations=25,
            parent_agent=parent,
        )
        if hasattr(result, "__await__"):
            result = await result
    except Exception as e:
        logger.warning("fix_it delegate failed: %s", e)
        return {"ok": False, "error": "delegate_failed", "detail": str(e)[:200],
                "say_to_user": "Не смогла запустить ремонт."}

    return {
        "ok": True,
        "problem": problem,
        "model": model or "unknown",
        "code_fix_allowed": can_fix_code,
        "report": result if isinstance(result, str) else str(result),
        "say_to_user": (
            "Ремонтник разобрался — смотри вердикт." if can_fix_code else
            "Сейчас стоит слабая модель, код не трогала — нашла причину и обход. "
            "Для починки кода переключи на qwen или claude."
        ),
    }


FIX_IT_SCHEMA = {
    "name": "fix_it",
    "description": (
        "Ремонтная бригада. Зови когда ЧТО УГОДНО сломалось/зависло/не сработало "
        "(инструмент завис, данные не передались, ошибка) — не чини сама, делегируй "
        "ремонтнику: он найдёт причину, починит (если можно) и вернёт вердикт, а ты "
        "продолжишь своё дело. Работает всегда, не только в проектах. Починку КОДА "
        "запускает только на сильной модели (qwen/claude); на слабой — только "
        "диагностика и обход."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "problem": {"type": "string", "description": "Что именно сломалось/зависло."},
            "context": {"type": "string", "description": "Что ты делала когда это случилось."},
            "tool": {"type": "string", "description": "Имя проблемного инструмента, если известно."},
        },
        "required": ["problem"],
    },
}

registry.register(
    name="fix_it",
    toolset="troika-voice",
    schema=FIX_IT_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji=chr(128295),
)