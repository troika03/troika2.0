"""
run_tool — универсальный диспетчер: вызывает ЛЮБОЙ инструмент из registry
напрямую, в обход активного набора модели (valid_tool_names).

ЗАЧЕМ: голосовой набор Тройки мал ради скорости (~8 tools). Остальные ~170
инструментов модель НЕ может вызвать напрямую — их нет в valid_tool_names
(«вижу но не могу»). run_tool решает это: Тройка всегда видит ОДИН этот
диспетчер, а через него исполняет любой инструмент по имени.

Связка с find_tool: find_tool находит имя+схему нужного инструмента →
Тройка зовёт run_tool(name=..., args={...}) → он исполняется из registry.

API:
  run_tool(name="android_calendar_create_event", args={"title": "...", ...})
    name — точное имя инструмента (из find_tool или известное).
    args — словарь аргументов для этого инструмента.

Возвращает результат целевого инструмента (dict), либо ошибку с подсказкой.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Dict, Optional
from tools.registry import registry

logger = logging.getLogger(__name__)


async def _invoke(name: str, args: Dict[str, Any], kw: Dict[str, Any]) -> Any:
    entry = registry.get_entry(name)
    if entry is None:
        # подскажем похожие имена
        try:
            allnames = list(getattr(registry, "_tools", {}).keys())
        except Exception:
            allnames = []
        near = [n for n in allnames if name.lower() in n.lower() or n.lower() in name.lower()][:5]
        return {"ok": False, "error": "tool_not_found",
                "name": name,
                "hint": ("Нет такого инструмента. Похожие: " + ", ".join(near)
                         if near else "Проверь имя через find_tool.")}
    handler = getattr(entry, "handler", None)
    if handler is None:
        return {"ok": False, "error": "no_handler", "name": name}
    # check_fn — доступность (env/требования). Не блокируем жёстко, но предупредим.
    check = getattr(entry, "check_fn", None)
    if check is not None:
        try:
            res = check()
            ok = res[0] if isinstance(res, (tuple, list)) else res
            if ok is False:
                reason = res[1] if isinstance(res, (tuple, list)) and len(res) > 1 else "недоступен"
                return {"ok": False, "error": "tool_unavailable", "name": name, "hint": str(reason)}
        except Exception:
            pass  # check упал — пробуем вызвать всё равно
    try:
        if getattr(entry, "is_async", False) or asyncio.iscoroutinefunction(handler):
            raw = await handler(args, **kw)
        else:
            raw = handler(args, **kw)
            if asyncio.iscoroutine(raw):
                raw = await raw
    except TypeError:
        # handler без **kw — пробуем без kwargs
        try:
            raw = handler(args)
            if asyncio.iscoroutine(raw):
                raw = await raw
        except Exception as e:
            return {"ok": False, "error": "call_failed", "name": name, "detail": str(e)[:200]}
    except Exception as e:
        logger.warning("run_tool %s failed: %s", name, e)
        return {"ok": False, "error": "call_failed", "name": name, "detail": str(e)[:200]}
    # нормализуем результат
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": True, "result": raw}
    return raw if isinstance(raw, dict) else {"ok": True, "result": raw}


async def _handle(arguments: Dict[str, Any], **_kw) -> Any:
    name = (arguments.get("name") or arguments.get("tool") or "").strip()
    if not name:
        return {"ok": False, "error": "missing_name",
                "hint": "Укажи name — точное имя инструмента (узнай через find_tool)."}
    args = arguments.get("args") or arguments.get("arguments") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    # не даём вызвать сам себя/роутеры рекурсивно
    if name in ("run_tool", "find_tool"):
        return {"ok": False, "error": "no_recursion", "hint": "Вызови целевой инструмент, не роутер."}
    return await _invoke(name, args, _kw)


RUN_TOOL_SCHEMA = {
    "name": "run_tool",
    "description": (
        "Универсальный вызов ЛЮБОГО инструмента по имени — даже если его нет в "
        "твоём активном наборе. Сначала find_tool подскажет имя и параметры "
        "нужного инструмента, затем вызови его так: run_tool(name='имя', "
        "args={параметры}). Через это ты можешь сделать ВСЁ что умеешь — "
        "календарь, документы, картинки, видео, делегирование и т.д. Никогда не "
        "говори «не могу вызвать» — вызывай через run_tool."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Точное имя инструмента (из find_tool)."},
            "args": {"type": "object", "description": "Аргументы для этого инструмента (словарь)."},
        },
        "required": ["name"],
    },
}

registry.register(
    name="run_tool",
    toolset="troika-voice",
    schema=RUN_TOOL_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji=chr(9889),
)