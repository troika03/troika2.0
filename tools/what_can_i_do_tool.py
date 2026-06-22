"""
what_can_i_do — внутренняя самосправка Тройки о собственных возможностях.

ЗАЧЕМ: голосовой toolset урезан до ~40 tools ради латентности (остальные ~120
спрятаны за find_tool). Из-за этого Тройка часто НЕ ВИДИТ своих способностей и
ошибочно говорит «не умею», хотя реально умеет. Этот tool читает ЖИВОЙ registry
и отдаёт Тройке честную карту — чтобы перед «не могу» она сверилась с собой.

ВАЖНО — справка ДЛЯ САМОЙ ТРОЙКИ, не лекция пользователю. Получив ответ, Тройка
отвечает Мише коротко («умею, да» / «многое — что конкретно?»), НЕ зачитывая
список вслух.
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional
from tools.registry import registry

logger = logging.getLogger(__name__)

_CATEGORIES: List[Dict[str, Any]] = [
    {"name": "Управление телефоном",
     "match_name": ["android_", "tap", "swipe", "screenshot", "alarm", "navigate",
                    "torch", "volume", "brightness", "clipboard", "battery", "camera"],
     "toolsets": ["android", "phone"]},
    {"name": "Зрение",
     "match_name": ["vision", "image_analyze", "ground"], "toolsets": ["vision", "ground"]},
    {"name": "Память и заметки",
     "match_name": ["soma_", "memory_", "diary_", "obsidian_", "note"],
     "toolsets": ["memory", "obsidian"]},
    {"name": "Написание кода",
     "match_name": ["claude_code", "gemini_code", "qwen_code", "coder", "code_review"],
     "toolsets": ["coding", "coder"]},
    {"name": "Самоулучшение", "match_name": ["self_improve"], "toolsets": ["self_improve"]},
    {"name": "Делегирование и фон",
     "match_name": ["delegate_task", "bg_task", "job", "mixture_of_agents", "task_status"],
     "toolsets": ["delegation", "background"]},
    {"name": "Проекты", "match_name": ["project"], "toolsets": ["project"]},
    {"name": "Документы",
     "match_name": ["create_pdf", "create_pptx", "create_docx", "create_xlsx",
                    "beautiful", "infographic"], "toolsets": ["documents"]},
    {"name": "Медиа",
     "match_name": ["create_image", "create_video", "image_hf", "flux", "video"],
     "toolsets": ["media"]},
    {"name": "Веб и информация",
     "match_name": ["web_research", "web_search", "weather", "wikipedia", "translate",
                    "currency", "crypto", "news", "youtube", "qr_", "world_time"],
     "toolsets": ["web", "info"]},
    {"name": "Связь",
     "match_name": ["telegram_send", "reminder", "push_to_user", "notify", "send_message"],
     "toolsets": ["messaging"]},
    {"name": "Местоположение",
     "match_name": ["location", "gps", "geocode"], "toolsets": ["location"]},
]

def _all_tools() -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    tools = getattr(registry, "_tools", {}) or {}
    for name, entry in tools.items():
        toolset = getattr(entry, "toolset", "") or ""
        schema = getattr(entry, "schema", None) or {}
        desc = schema.get("description", "") if isinstance(schema, dict) else ""
        out.append({"name": name, "toolset": toolset, "description": desc or ""})
    return out

def _belongs(tool: Dict[str, str], cat: Dict[str, Any]) -> bool:
    nm, ts = tool["name"].lower(), tool["toolset"].lower()
    if any(t in ts for t in cat.get("toolsets", [])):
        return True
    return any(frag in nm for frag in cat.get("match_name", []))

def _categorize() -> Dict[str, List[str]]:
    tools = _all_tools()
    cats: Dict[str, List[str]] = {}
    seen: set = set()
    for cat in _CATEGORIES:
        names = sorted({t["name"] for t in tools if _belongs(t, cat)})
        if names:
            cats[cat["name"]] = names
            seen.update(names)
    leftover = sorted({t["name"] for t in tools if t["name"] not in seen})
    if leftover:
        cats["Прочее"] = leftover
    return cats

def what_can_i_do(topic: Optional[str] = None) -> Dict[str, Any]:
    tools = _all_tools()
    total = len(tools)
    if topic and topic.strip():
        q = topic.strip().lower()
        matches = []
        for t in tools:
            if q in f"{t['name']} {t['toolset']} {t['description']}".lower():
                matches.append({"name": t["name"], "description": t["description"][:140]})
        if not matches:
            for cat in _CATEGORIES:
                if q in cat["name"].lower() or any(q in m for m in cat.get("match_name", [])):
                    for t in tools:
                        if _belongs(t, cat):
                            matches.append({"name": t["name"], "description": t["description"][:140]})
        matches = matches[:8]
        can = len(matches) > 0
        return {"ok": True, "topic": topic.strip(), "can": can, "matches": matches,
                "hint": ("Ты ЭТО УМЕЕШЬ — вызови нужный tool (через find_tool если он не в "
                         "активном наборе). НЕ говори «не умею»." if can else
                         "Прямого инструмента нет. Проверь через find_tool с другими словами "
                         "прежде чем сказать что не можешь.")}
    cats = _categorize()
    return {"ok": True, "total": total, "categories": cats,
            "summary": ", ".join(cats.keys()),
            "hint": ("Карта для САМОСВЕРКИ, не для зачитывания вслух. Ответь Мише коротко "
                     "(«умею многое — что конкретно надо?»). Многое доставай через find_tool.")}

def _handle(arguments: Dict[str, Any], **_kw) -> Dict[str, Any]:
    return what_can_i_do(topic=(arguments.get("topic") or "").strip() or None)

WHAT_CAN_I_DO_SCHEMA = {
    "name": "what_can_i_do",
    "description": ("Твоя самосправка: проверь что умеешь ПРЕЖДЕ чем сказать «не умею». "
                    "Голосовой набор урезан — многое спрятано за find_tool, ты часто "
                    "недооцениваешь себя. Зови когда сомневаешься можешь ли что-то "
                    "(передай topic) или нужен обзор (без topic). Ответ ДЛЯ ТЕБЯ, не для "
                    "зачитывания вслух — Мише отвечай коротко."),
    "parameters": {"type": "object", "properties": {
        "topic": {"type": "string", "description": "Что проверить: «видео», «код», "
                  "«делегировать», «проект». Пусто → общая карта."}}, "required": []},
}

registry.register(name="what_can_i_do", toolset="troika-voice",
                  schema=WHAT_CAN_I_DO_SCHEMA, handler=_handle, is_async=False, emoji=chr(129517))