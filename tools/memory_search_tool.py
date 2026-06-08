"""
memory_search — fuzzy-поиск по Obsidian-vault'у Тройки.

vault: C:/Users/kiqu/.claude/projects/d--troikahermes/memory/
       (или путь из HERMES_MEMORY_VAULT env)

Поиск:
  • по имени файла (fuzzy через difflib)
  • по описанию из frontmatter (`description:`)
  • по содержимому (substring + score)
Возвращает топ N с превью, без чтения целиком — экономит контекст LLM.

Используется когда Тройка хочет «вспомнить» что-то без линейного прохода
по MEMORY.md.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from tools.registry import registry

logger = logging.getLogger(__name__)


_DEFAULT_VAULT = Path("C:/Users/kiqu/.claude/projects/d--troikahermes/memory")
_VAULT = Path(os.environ.get("HERMES_MEMORY_VAULT") or _DEFAULT_VAULT)

_DESC_RE = re.compile(r'^description:\s*"?(.+?)"?\s*$', re.IGNORECASE | re.MULTILINE)
_TYPE_RE = re.compile(r'^\s*type:\s*(\w+)\s*$', re.IGNORECASE | re.MULTILINE)


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip()
    return text


def _parse_meta(text: str) -> Dict[str, str]:
    meta = {"description": "", "type": ""}
    if not text.startswith("---"):
        return meta
    end = text.find("\n---", 3)
    if end == -1:
        return meta
    header = text[3:end]
    m = _DESC_RE.search(header)
    if m:
        meta["description"] = m.group(1).strip()
    m = _TYPE_RE.search(header)
    if m:
        meta["type"] = m.group(1).strip()
    return meta


def _score(query: str, name: str, description: str, body: str) -> float:
    q = query.lower().strip()
    if not q:
        return 0.0
    # 1. Exact substring in name → max boost
    name_lower = name.lower()
    score = 0.0
    if q in name_lower:
        score += 50
    # 2. Fuzzy ratio of name
    score += difflib.SequenceMatcher(None, q, name_lower).ratio() * 30
    # 3. Substring in description
    if q in description.lower():
        score += 25
    # 4. Substring count in body (cap)
    body_hits = body.lower().count(q)
    if body_hits:
        score += min(body_hits * 3, 20)
    # 5. Per-word matches (when query is multi-word)
    if " " in q:
        words = [w for w in q.split() if len(w) > 2]
        for w in words:
            if w in name_lower:
                score += 5
            if w in description.lower():
                score += 3
            score += min(body.lower().count(w), 5) * 1
    return score


def _excerpt(body: str, query: str, max_chars: int = 200) -> str:
    q = query.lower().strip()
    body_lower = body.lower()
    idx = body_lower.find(q) if q else -1
    if idx == -1 and " " in q:
        # пробуем первое значащее слово
        for w in q.split():
            if len(w) > 2:
                idx = body_lower.find(w)
                if idx != -1:
                    break
    if idx == -1:
        # просто первые символы
        snip = body[:max_chars]
    else:
        start = max(0, idx - 50)
        snip = body[start:start + max_chars]
        if start > 0:
            snip = "…" + snip
    snip = re.sub(r"\s+", " ", snip).strip()
    if len(snip) > max_chars:
        snip = snip[:max_chars] + "…"
    return snip


async def _handle_search(arguments: dict, **_kw) -> dict:
    query = (arguments.get("query") or "").strip()
    if not query:
        return {"ok": False, "error": "missing_query"}
    type_filter = (arguments.get("type") or "").strip().lower()
    limit = int(arguments.get("limit", 5))
    limit = max(1, min(limit, 20))

    if not _VAULT.exists():
        return {"ok": False, "error": f"vault_not_found: {_VAULT}"}

    # Семантический слой (опциональное усиление). Возвращает rel_path → косинус
    # [0..1]; пустой dict, если sentence-transformers недоступен → чистый fuzzy.
    # Запрос «как починить зависший gemini» так находит заметку про taskkill,
    # даже без лексического пересечения слов. См. memory_semantic.
    sem: Dict[str, float] = {}
    try:
        from tools.memory_semantic import semantic_scores
        sem = semantic_scores(query)
    except Exception as e:
        logger.debug("semantic layer unavailable: %s", e)

    used_semantic = bool(sem)
    # Порог семантического вклада: ниже 0.30 близость = шум (multilingual MiniLM
    # держит несвязанные тексты в районе 0.1-0.25). Берём только реально похожее.
    SEM_FLOOR = 0.30

    results: List[Dict[str, Any]] = []
    for md_path in _VAULT.rglob("*.md"):
        if md_path.name == "MEMORY.md":  # index, не информативный
            continue
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        meta = _parse_meta(text)
        if type_filter and meta.get("type", "").lower() != type_filter:
            continue
        body = _strip_frontmatter(text)
        name = md_path.stem
        rel = md_path.relative_to(_VAULT).as_posix()

        fuzzy = _score(query, name, meta.get("description", ""), body)
        sim = sem.get(rel, 0.0)
        # Гибрид: семантика вносит до ~45 баллов (сопоставимо с substring-in-name=50),
        # но только выше шумового порога. Так смысловое совпадение конкурирует с
        # лексическим, не затирая его.
        sem_pts = (sim - SEM_FLOOR) / (1 - SEM_FLOOR) * 45 if sim >= SEM_FLOOR else 0.0
        sc = fuzzy + sem_pts

        # Порог попадания: лексический ≥5 ЛИБО уверенная семантика (≥0.45).
        if fuzzy < 5 and sim < 0.45:
            continue

        results.append({
            "name": name,
            "path": rel,
            "type": meta.get("type", ""),
            "description": meta.get("description", "")[:160],
            "excerpt": _excerpt(body, query),
            "score": round(sc, 1),
            "match": ("semantic" if fuzzy < 5 else
                      ("hybrid" if sem_pts > 0 else "lexical")),
        })

    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:limit]
    return {"ok": True, "query": query, "count": len(results),
            "semantic": used_semantic, "results": results}


SEARCH_SCHEMA = {
    "name": "memory_search",
    "description": "Поиск по Obsidian-памяти Тройки — лексический (имя/описание/содержимое) И семантический (по смыслу). Находит нужное, даже если слова в запросе и заметке разные («починить зависший gemini» → заметка про taskkill). Возвращает топ-N с превью без полного чтения. Используй когда нужно «вспомнить» прошлое — что было, кто что просил, как был настроен такой-то tool. Параметр type фильтрует по project/user/feedback/reference.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Что ищем. Можно несколько слов."},
            "type": {"type": "string", "description": "Опционально: project|user|feedback|reference|diary"},
            "limit": {"type": "integer", "description": "Максимум результатов, default 5, max 20"},
        },
        "required": ["query"],
    },
}


registry.register(
    name="memory_search", toolset="memory",
    schema=SEARCH_SCHEMA, handler=_handle_search,
    is_async=True, emoji="🧬",
)
