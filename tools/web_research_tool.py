"""
web_research — голосовой «разберись и ответь коротко».

Зачем отдельный tool, если есть web_search + web_extract: на голосе (Gemini Flash
Lite) каждый шаг = отдельный turn модели, а multi-turn — главный убийца латентности
(см. troika-latency-round2). Чтобы ответить на «что там с курсом биткоина / кто
выиграл вчера / разберись про X» Тройке иначе надо: web_search → прочитать выдачу →
web_extract нескольких ссылок → синтез. 4+ turn'а по 10-25с каждый.

web_research делает весь цикл ОДНИМ серверным вызовом:
  1. web_search(question) → топ результаты (title/url/snippet);
  2. web_extract(топ 2-3 url) → суммаризованный контент страниц;
  3. один LLM-синтез → короткий УСТНЫЙ ответ (3-5 предложений, без markdown) +
     названия источников;
  4. возвращает {ok, answer, sources, say_to_user} — Тройка озвучивает say_to_user.

Никакого нового стека: переиспользует web_search_tool / web_extract_tool и тот же
вспомогательный LLM, что web_extract (auxiliary.web_extract в config.yaml).

Деградация без регрессии:
  • нет ключа web-API → понятная ошибка с say_to_user «не настроен веб-поиск»;
  • extract упал/пусто → синтез из одних сниппетов выдачи;
  • LLM-синтеза нет → отдаём топ-сниппеты как есть (хоть что-то).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from tools.registry import registry
from tools.web_tools import (
    web_search_tool,
    web_extract_tool,
    check_web_api_key,
    _web_requires_env,
    _resolve_web_extract_auxiliary,
    async_call_llm,
    extract_content_or_reasoning,
)

logger = logging.getLogger(__name__)

# Сколько ссылок реально читаем (extract медленный — больше 3 не нужно для устного
# ответа и только растит латентность).
_MAX_EXTRACT = 3
# Размер контента на страницу, который скармливаем синтезу (extract уже
# суммаризует крупные страницы до ~5k; ещё подрежем, чтобы prompt был лёгким).
_PER_PAGE_CHARS = 3500


def _parse_search(raw: str) -> Tuple[List[Dict[str, str]], Optional[str]]:
    """JSON выдачи web_search → (список {title,url,description}, error|None).

    Различаем ДВА разных «пусто»:
      • success:false / error → провайдер не настроен или упал → возвращаем
        текст ошибки, чтобы НЕ маскировать это под «ничего не нашлось»;
      • success:true, но web=[] → честно ноль результатов (error=None).
    """
    try:
        data = json.loads(raw)
    except Exception as e:
        return [], f"bad_search_response: {e}"
    if not isinstance(data, dict):
        return [], "bad_search_response"
    if data.get("success") is False:
        return [], (data.get("error") or "search_provider_error")
    web = (data.get("data") or {}).get("web") or []
    out: List[Dict[str, str]] = []
    for r in web:
        if not isinstance(r, dict):
            continue
        url = (r.get("url") or "").strip()
        if not url:
            continue
        out.append({
            "title": (r.get("title") or "").strip(),
            "url": url,
            "description": (r.get("description") or "").strip(),
        })
    return out, None


def _parse_extract(raw: str) -> List[Dict[str, str]]:
    """JSON web_extract → список {url,title,content}. [] при сбое."""
    try:
        data = json.loads(raw)
    except Exception:
        return []
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []
    out: List[Dict[str, str]] = []
    for r in results:
        if not isinstance(r, dict) or r.get("error"):
            continue
        content = (r.get("content") or "").strip()
        if not content:
            continue
        out.append({
            "url": (r.get("url") or "").strip(),
            "title": (r.get("title") or "").strip(),
            "content": content[:_PER_PAGE_CHARS],
        })
    return out


def _domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        host = urlparse(url).netloc or url
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return url


async def _synthesize(question: str, pages: List[Dict[str, str]],
                      snippets: List[Dict[str, str]]) -> Optional[str]:
    """Один LLM-вызов: вопрос + контент → короткий устный ответ. None при сбое."""
    aux_client, model, extra_body = _resolve_web_extract_auxiliary(None)
    if aux_client is None or not model:
        logger.info("web_research: no auxiliary model for synthesis")
        return None

    # Собираем контекст: реальный контент страниц, иначе — сниппеты выдачи.
    blocks: List[str] = []
    if pages:
        for p in pages:
            src = p["title"] or _domain(p["url"])
            blocks.append(f"ИСТОЧНИК: {src} ({_domain(p['url'])})\n{p['content']}")
    else:
        for s in snippets[:5]:
            src = s["title"] or _domain(s["url"])
            blocks.append(f"ИСТОЧНИК: {src} ({_domain(s['url'])})\n{s['description']}")
    if not blocks:
        return None
    context = "\n\n---\n\n".join(blocks)

    system_prompt = (
        "Ты помощник, который отвечает на вопрос пользователя ГОЛОСОМ по материалам "
        "из интернета. Ответ будет ОЗВУЧЕН вслух, поэтому:\n"
        "- 3-5 коротких предложений, разговорно, по-русски;\n"
        "- НИКАКОГО markdown, списков, заголовков, ссылок, URL — только живая речь;\n"
        "- сразу суть, без воды «по данным источников...»;\n"
        "- если материалы противоречат или вопрос не раскрыт — честно скажи что "
        "нашёл, не выдумывай;\n"
        "- числа/даты/имена приводи точно, как в источниках."
    )
    user_prompt = (
        f"ВОПРОС: {question}\n\n"
        f"МАТЕРИАЛЫ ИЗ ИНТЕРНЕТА:\n{context}\n\n"
        "Дай короткий устный ответ на вопрос по этим материалам."
    )

    try:
        call_kwargs = {
            "task": "web_extract",  # переиспользуем тот же auxiliary-профиль
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 600,
        }
        if extra_body:
            call_kwargs["extra_body"] = extra_body
        response = await async_call_llm(**call_kwargs)
        answer = extract_content_or_reasoning(response)
        return (answer or "").strip() or None
    except Exception as e:
        logger.warning("web_research synthesis failed: %s", e)
        return None


def _fallback_answer(snippets: List[Dict[str, str]]) -> str:
    """Без LLM — склеиваем 2-3 сниппета в подобие ответа."""
    parts = []
    for s in snippets:
        d = s["description"] or s["title"]
        if d:
            parts.append(d)
    return " ".join(parts)[:600] or "Ничего внятного по этому запросу не нашлось."


async def _handle(args: Dict[str, Any], **_kw) -> str:
    question = (args.get("question") or args.get("query") or args.get("q") or "").strip()
    if not question:
        return json.dumps(
            {"ok": False, "error": "missing 'question'",
             "say_to_user": "Не понял, что именно поискать."},
            ensure_ascii=False,
        )

    if not check_web_api_key():
        return json.dumps(
            {"ok": False, "error": "web_api_not_configured",
             "say_to_user": "Веб-поиск не настроен — нет ключа поискового API."},
            ensure_ascii=False,
        )

    # 1. Поиск
    try:
        raw_search = web_search_tool(question, limit=5)
    except Exception as e:
        logger.warning("web_research search failed: %s", e)
        return json.dumps(
            {"ok": False, "error": f"search_failed: {e}",
             "say_to_user": "Не получилось выполнить поиск в интернете."},
            ensure_ascii=False,
        )
    snippets, search_err = _parse_search(raw_search)
    if search_err:
        # Провайдер не настроен/упал — это НЕ «ничего не нашлось».
        low = search_err.lower()
        if "provider" in low or "not configured" in low or "api" in low or "key" in low:
            say = "Веб-поиск не настроен — нужно подключить поисковый провайдер."
        else:
            say = "Поиск в интернете сейчас недоступен."
        return json.dumps(
            {"ok": False, "error": search_err, "say_to_user": say},
            ensure_ascii=False,
        )
    if not snippets:
        return json.dumps(
            {"ok": True, "answer": "", "sources": [],
             "say_to_user": f"По запросу «{question}» ничего не нашёл."},
            ensure_ascii=False,
        )

    # 2. Читаем топ-N ссылок (extract сам суммаризует крупные страницы)
    top_urls = [s["url"] for s in snippets[:_MAX_EXTRACT]]
    pages: List[Dict[str, str]] = []
    try:
        raw_extract = await web_extract_tool(top_urls, "markdown")
        pages = _parse_extract(raw_extract)
    except Exception as e:
        logger.info("web_research extract failed (синтез из сниппетов): %s", e)

    # 3. Синтез устного ответа
    answer = await _synthesize(question, pages, snippets)
    used_llm = bool(answer)
    if used_llm:
        src_pool = pages or snippets[:5]
    else:
        src_pool = snippets[:3]
        answer = _fallback_answer(src_pool)
    source_status = "read" if used_llm and pages else "found"
    sources = []
    seen = set()
    for r in src_pool:
        d = _domain(r["url"])
        if d and d not in seen:
            seen.add(d)
            sources.append(d)

    return json.dumps(
        {
            "ok": True,
            "question": question,
            "answer": answer,
            "sources": sources,
            "source_details": [
                {"url": r["url"], "title": r.get("title", ""),
                 "status": source_status}
                for r in src_pool
            ],
            "pages_read": len(pages),
            "synthesized": used_llm,
            # Тройка озвучивает это дословно. Источники не диктуем по буквам —
            # одним словом-доменом, и только если их немного.
            "say_to_user": answer,
        },
        ensure_ascii=False,
    )


WEB_RESEARCH_SCHEMA = {
    "name": "web_research",
    "description": (
        "Ответить на вопрос пользователя, разобравшись в интернете — ОДНИМ вызовом. "
        "Делает поиск, читает несколько лучших страниц и возвращает короткий "
        "готовый устный ответ (3-5 предложений, без markdown) плюс источники. "
        "Используй для голосовых «что там с X / кто выиграл / разберись про Y / "
        "что пишут про Z / актуально ли ещё ...» — когда нужен сжатый ответ, а не "
        "сырая выдача. НЕ дёргай web_search+web_extract вручную для устного ответа — "
        "это медленнее (несколько ходов модели). Для одной конкретной страницы по "
        "известному URL используй web_extract; для глубокого многошагового "
        "исследования с отчётом — delegate_task."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "Вопрос на естественном языке, как его задал пользователь. "
                    "Например «какой сейчас курс биткоина», «кто выиграл лигу "
                    "чемпионов вчера», «правда ли что X»."
                ),
            },
        },
        "required": ["question"],
    },
}


registry.register(
    name="web_research",
    toolset="web",
    schema=WEB_RESEARCH_SCHEMA,
    handler=_handle,
    check_fn=check_web_api_key,
    requires_env=_web_requires_env(),
    is_async=True,
    emoji="🔎",
    max_result_size_chars=20_000,
)
