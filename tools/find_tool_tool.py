"""
find_tool — мета-инструмент для голосовой Тройки.

Цель: дать Тройке доступ ко всем зарегистрированным tools (137+), но при
этом держать system prompt лёгким. В базовом наборе troika-voice
схема Тройки содержит ~25 ходовых tools + один find_tool. Когда ей нужно
что-то редкое (kanban, spotify, computer_use, mcp_*, exotic skill_*),
она зовёт find_tool — он возвращает schema подходящих инструментов в
тексте, и Тройка использует их в следующем сообщении.

API:
  find_tool(query="...", limit=3)
    query — что нужно сделать (на русском или английском),
            например "запустить kanban-задачу", "поставить трек spotify",
            "поискать в почте gmail".
    limit — сколько top-N кандидатов вернуть (default 3, max 10).

Возвращает:
  {
    "ok": true,
    "query": "...",
    "matches": [
      {"name": "kanban_create", "toolset": "kanban",
       "description": "...full schema description...",
       "parameters": {...full schema parameters...}},
      ...
    ]
  }

Тройка должна:
  1. Прочитать `name`, `description`, `parameters` из ответа.
  2. Вызвать выбранный tool по имени с правильными параметрами.
  3. Если ни один не подходит — переспросить пользователя или сказать
     что задача невыполнима.

Ранжирование: substring/token-overlap по полю description tool'а
(простое, без embeddings — этот инструмент сам по себе должен быть
быстрым и не тащить sentence-transformers). Учитываем также имя
tool'а и имя toolset'а. Совпадение в имени даёт больший вес чем в
описании.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Tuple

from tools.registry import registry

logger = logging.getLogger(__name__)


# Стоп-слова: одни буквы, союзы, предлоги — не помогают ранжировать
_STOP = frozenset(
    [
        "и", "в", "на", "по", "с", "для", "от", "до", "из", "о", "об",
        "что", "как", "это", "так", "а", "но", "же", "или", "не", "ни",
        "the", "a", "an", "to", "of", "for", "in", "on", "and", "or",
        "is", "it", "be", "by", "at", "with", "as",
    ]
)


# RU↔EN синонимы для частых доменов. При токенизации добавляем
# соответствующий перевод. Тройка говорит по-русски, а tool-имена
# и описания — часто на английском.
_SYNONYMS = {
    # время / даты
    "погода": "weather", "weather": "погода",
    "время": "time", "time": "время",
    "дата": "date", "date": "дата",
    "календарь": "calendar", "calendar": "календарь",
    "напоминание": "reminder", "напомни": "reminder",
    # звонки / связь
    "позвони": "call", "звонок": "call",
    "сообщение": "sms message",
    "смс": "sms", "месседж": "message",
    # медиа (spotify-tools в этой сборке нет — музыка живёт в приложении на телефоне)
    "музыка": "music player open app", "музыку": "music player open app",
    "music": "player app",
    "плеер": "player open app",
    "видео": "video youtube",
    "youtube": "youtube",
    "трек": "track",
    # файлы / док
    "файл": "file", "file": "файл",
    "документ": "document",
    "презентация": "pptx presentation",
    "таблица": "xlsx spreadsheet",
    "архив": "zip archive",
    # дом
    "свет": "light hass home", "лампа": "light",
    "температура": "temperature thermostat",
    # почта
    "почта": "mail email gmail",
    "письмо": "mail message email",
    "gmail": "mail email",
    # деньги
    "финансы": "finance money",
    "потратил": "finance expense",
    "купил": "finance expense buy",
    "расход": "finance expense",
    "расходы": "finance expense",
    "трата": "finance expense",
    "траты": "finance expense",
    "доход": "finance income",
    "зарплата": "salary income",
    # обсидиан / память
    "заметка": "obsidian note",
    "obsidian": "note",
    "память": "memory note",
    # перевод
    "переведи": "translate", "перевод": "translate",
    "переводчик": "translate",
    # веб
    "поиск": "search", "search": "поиск",
    "браузер": "browser web",
    "google": "search web",
    # карта
    "карта": "map navigate",
    "навигация": "navigate map",
    # фоновые
    "фон": "background bg_task kanban",
    "research": "delegate task bg_task",
    "исследование": "research delegate bg_task",
    # экран
    "скриншот": "screenshot screen",
    "экран": "screen screenshot",
    # GROUND — фоновое наблюдение за экраном
    "следи": "ground screen observe наблюдай",
    "следить": "ground screen observe",
    "наблюдай": "ground screen observe",
    "наблюдать": "ground screen observe",
    # DAEMON — автономный/проактивный режим
    "активнее": "daemon proactive autonomous",
    "сама": "daemon proactive",
    "инициатива": "daemon proactive",
    "проактивн": "daemon proactive",
    "автономн": "daemon autonomous",
    # SOMA — память о пользователе
    "запомни": "soma remember memory обо мне",
    "вспомни": "soma recall memory",
    "забудь": "soma forget",
    "обо": "soma about me",
    # Самоулучшение — self_improve_* (имена английские, форм «улучши/улучшить» нет)
    "улучши": "self_improve propose improve",
    "улучшить": "self_improve propose improve",
    "улучшение": "self_improve improve",
    "самоулучшение": "self_improve improve",
    "себя": "self_improve self propose",
    "научись": "self_improve propose improve skill",
    "доработай": "self_improve propose improve",
    "fix": "self_improve propose",
    # vision
    "картинка": "image vision",
    "фото": "photo image camera",
    # MCP
    "сервер": "mcp server",
    "интеграция": "mcp",
}


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    text = text.lower()
    # Сохраняем буквы (русские/латинские) и цифры
    tokens = re.findall(r"[a-zа-яё0-9_]+", text, flags=re.IGNORECASE)
    return [t for t in tokens if len(t) >= 2 and t not in _STOP]


def _expand_query(tokens: List[str]) -> List[str]:
    """Добавляет переводы/синонимы для русских и английских токенов."""
    out: List[str] = list(tokens)
    seen = set(tokens)
    for t in tokens:
        syn = _SYNONYMS.get(t)
        if not syn:
            continue
        for s in syn.split():
            s = s.lower()
            if s and s not in seen:
                out.append(s)
                seen.add(s)
    return out


def _score_entry(name_tokens: List[str], toolset_tokens: List[str],
                 desc_tokens: List[str], query_tokens: List[str]) -> float:
    if not query_tokens:
        return 0.0
    name_set = set(name_tokens)
    ts_set = set(toolset_tokens)
    desc_set = set(desc_tokens)

    score = 0.0
    for q in query_tokens:
        if q in name_set:
            score += 4.0
        if q in ts_set:
            score += 2.5
        if q in desc_set:
            score += 1.0
        # Подстрочные совпадения (частичный фрагмент имени) дешевле
        for nt in name_tokens:
            if q != nt and len(q) >= 4 and q in nt:
                score += 1.5
                break
        for dt in desc_tokens:
            if q != dt and len(q) >= 4 and q in dt:
                score += 0.5
                break
    return score


def _strip_function_wrap(schema: Any) -> Dict[str, Any]:
    """get_definitions возвращает [{"type":"function","function":{...}}];
    при работе напрямую с entry.schema у нас уже плоский dict."""
    if isinstance(schema, dict):
        if schema.get("type") == "function" and isinstance(schema.get("function"), dict):
            return dict(schema["function"])
        return dict(schema)
    return {}


async def _handle(args: Dict[str, Any], **_kw) -> str:
    query = (args.get("query") or args.get("q") or "").strip()
    if not query:
        return json.dumps(
            {"ok": False, "error": "missing 'query'"}, ensure_ascii=False
        )
    try:
        limit = int(args.get("limit") or 3)
    except (TypeError, ValueError):
        limit = 3
    limit = max(1, min(limit, 10))

    exclude_self = "find_tool"
    raw_tokens = _tokenize(query)
    query_tokens = _expand_query(raw_tokens)
    if not query_tokens:
        return json.dumps(
            {"ok": False, "error": "query has no usable tokens"},
            ensure_ascii=False,
        )

    candidates: List[Tuple[float, str]] = []
    all_names = registry.get_all_tool_names()
    for name in all_names:
        if name == exclude_self:
            continue
        entry = registry.get_entry(name)
        if entry is None:
            continue
        schema = _strip_function_wrap(entry.schema)
        desc = (schema.get("description") or entry.description or "") if isinstance(schema, dict) else ""
        name_tokens = _tokenize(name)
        toolset_tokens = _tokenize(entry.toolset or "")
        desc_tokens = _tokenize(desc)
        score = _score_entry(name_tokens, toolset_tokens, desc_tokens, query_tokens)
        if score > 0:
            candidates.append((score, name))

    candidates.sort(key=lambda x: -x[0])
    top = candidates[:limit]

    if not top:
        return json.dumps(
            {
                "ok": True,
                "query": query,
                "matches": [],
                "hint": "Ничего не нашлось. Переформулируй запрос — что именно нужно сделать.",
            },
            ensure_ascii=False,
        )

    matches: List[Dict[str, Any]] = []
    for score, name in top:
        entry = registry.get_entry(name)
        if entry is None:
            continue
        schema = _strip_function_wrap(entry.schema)
        matches.append(
            {
                "name": name,
                "toolset": entry.toolset,
                "score": round(float(score), 2),
                "emoji": entry.emoji or "",
                "description": schema.get("description") or entry.description or "",
                "parameters": schema.get("parameters") or {},
            }
        )

    return json.dumps(
        {
            "ok": True,
            "query": query,
            "count": len(matches),
            "matches": matches,
            "usage_hint": (
                "Прочитай matches[*].description и parameters, выбери "
                "подходящий tool по name и вызови его на следующем шаге. "
                "Если ни один не подходит — попроси уточнить."
            ),
        },
        ensure_ascii=False,
    )


FIND_TOOL_SCHEMA = {
    "name": "find_tool",
    "description": (
        "Найти подходящий инструмент по описанию задачи. Используй когда "
        "среди уже видимых тебе tools нет нужного, но возможно есть "
        "среди остальных 100+ зарегистрированных. Примеры запросов: "
        "'управление spotify', 'kanban-задача', 'найти в gmail', "
        "'computer use на macOS', 'mcp filesystem'. Возвращает топ-N "
        "кандидатов с полными schema — вызывай выбранный на следующем "
        "шаге по имени. НЕ используй этот tool для того что у тебя уже "
        "видно (phone-управление, календарь, погода, obsidian, finance "
        "и т.п. — они в основном наборе)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Что нужно сделать одной короткой фразой. Лучше "
                    "включать ключевое слово домена: 'spotify', 'kanban', "
                    "'gmail', 'mcp', 'computer', 'docker', 'browser'."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Сколько кандидатов вернуть (1..10, default 3).",
            },
        },
        "required": ["query"],
    },
}


registry.register(
    name="find_tool",
    toolset="find_tool",
    schema=FIND_TOOL_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji="🔍",
)
