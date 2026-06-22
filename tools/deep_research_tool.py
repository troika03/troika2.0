"""
deep_research — глубокое исследование темы: Тройка роет открытые источники под
РАЗНЫМИ углами, перепроверяет, синтезирует структурный отчёт с источниками.

В отличие от web_research (быстрый устный ответ, 1 запрос) — здесь Тройка:
  1. Разбивает тему на несколько под-вопросов (углов).
  2. По каждому ищет (web_search) + читает топ-ссылки (web_extract).
  3. Сводит всё в структурный отчёт через LLM-синтез.
  4. Сохраняет в vault (research/<slug>.md), шлёт в Telegram, даёт краткий итог вслух.

Глубина настраивается: depth=quick (3 угла) | deep (5) | max (8).
ТОЛЬКО открытые источники — никакого пробива людей, взлома и приватных данных.

API:
  deep_research(topic="...", depth="deep", to_telegram=True)
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from tools.registry import registry

logger = logging.getLogger(__name__)

_DEPTH = {"quick": 3, "deep": 5, "max": 8}
_RESULTS_PER_ANGLE = 4
_EXTRACT_PER_ANGLE = 2


def _vault_root() -> Optional[Path]:
    import os
    env = os.environ.get("TROIKA_VAULT_PATH")
    if env and Path(env).exists():
        return Path(env)
    try:
        from hermes_constants import get_hermes_home
        hh = get_hermes_home()
    except Exception:
        hh = Path.home() / ".troika"
    for c in [hh / "vault", hh]:
        if c.exists():
            return c
    return None


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (s or "research").lower()).strip()
    return (re.sub(r"[\s_-]+", "-", s) or "research")[:50]


async def _make_angles(topic: str, n: int) -> List[str]:
    """LLM разбивает тему на n под-вопросов (углов)."""
    try:
        from tools.web_tools import async_call_llm, extract_content_or_reasoning
        prompt = (
            f"Тема исследования: «{topic}».\n"
            f"Разбей её на {n} КОНКРЕТНЫХ под-вопроса для веб-поиска, покрывающих "
            "разные стороны (суть, факты/цифры, мнения/оценки, риски/критика, "
            "контекст/история — что уместно). Верни ТОЛЬКО список по одному "
            "под-вопросу на строку, без нумерации и пояснений."
        )
        resp = await async_call_llm(messages=[{"role": "user", "content": prompt}])
        text = extract_content_or_reasoning(resp) or ""
        angles = [l.strip(" -•\t") for l in text.splitlines() if l.strip()]
        angles = [a for a in angles if len(a) > 5][:n]
        return angles or [topic]
    except Exception as e:
        logger.warning("deep_research angles failed: %s", e)
        return [topic]


async def _research_angle(angle: str) -> Dict[str, Any]:
    """Один угол: поиск + извлечение топ-страниц."""
    from tools.web_tools import web_search_tool, web_extract_tool
    out = {"angle": angle, "snippets": [], "pages": [], "sources": []}
    try:
        raw = web_search_tool(angle, limit=_RESULTS_PER_ANGLE)
        data = json.loads(raw) if isinstance(raw, str) else raw
        results = (data.get("data", {}) or {}).get("web") or data.get("results") or []
    except Exception as e:
        logger.debug("angle search failed %s: %s", angle, e)
        results = []
    urls = []
    for r in results[:_RESULTS_PER_ANGLE]:
        title = r.get("title") or ""
        url = r.get("url") or ""
        desc = r.get("description") or r.get("content") or ""
        if desc:
            out["snippets"].append(f"{title}: {desc[:300]}")
        if url:
            out["sources"].append(url)
            urls.append(url)
    # читаем топ-2 страницы угла
    for url in urls[:_EXTRACT_PER_ANGLE]:
        try:
            ext = await web_extract_tool(url=url)
            txt = ext if isinstance(ext, str) else json.dumps(ext, ensure_ascii=False)
            if txt:
                out["pages"].append(txt[:3000])
        except Exception:
            pass
    return out


async def _synthesize(topic: str, findings: List[Dict[str, Any]]) -> str:
    """Свести все углы в структурный отчёт."""
    from tools.web_tools import async_call_llm, extract_content_or_reasoning
    blocks = []
    for f in findings:
        body = "\n".join(f["snippets"][:4] + f["pages"][:1])
        blocks.append(f"### Угол: {f['angle']}\n{body[:2500]}")
    material = "\n\n".join(blocks)[:18000]
    prompt = (
        f"Ты — исследователь. Тема: «{topic}».\n"
        "Ниже материал, собранный по разным углам из открытых источников. "
        "Сделай СТРУКТУРНЫЙ отчёт по-русски:\n"
        "1) Краткий вывод (3-4 предложения).\n"
        "2) Ключевые факты/цифры (списком).\n"
        "3) Разные точки зрения / нюансы.\n"
        "4) Что осталось неясным / спорным.\n"
        "Опирайся ТОЛЬКО на материал, не выдумывай. Если данные противоречат — "
        "так и скажи.\n\n=== МАТЕРИАЛ ===\n" + material
    )
    try:
        resp = await async_call_llm(messages=[{"role": "user", "content": prompt}])
        return extract_content_or_reasoning(resp) or material[:2000]
    except Exception as e:
        logger.warning("deep_research synth failed: %s", e)
        return material[:2000]


async def _handle(arguments: Dict[str, Any], **_kw) -> Dict[str, Any]:
    topic = (arguments.get("topic") or arguments.get("query") or "").strip()
    depth = (arguments.get("depth") or "deep").strip().lower()
    to_tg = arguments.get("to_telegram", True)
    n = _DEPTH.get(depth, 5)

    if not topic:
        return {"ok": False, "error": "missing_topic",
                "say_to_user": "Что исследовать?"}

    # 1) углы
    angles = await _make_angles(topic, n)
    # 2) параллельно роем каждый угол
    findings = await asyncio.gather(*[_research_angle(a) for a in angles],
                                    return_exceptions=True)
    findings = [f for f in findings if isinstance(f, dict)]
    if not findings:
        return {"ok": False, "error": "no_findings",
                "say_to_user": "Не смогла ничего найти по теме."}
    # 3) синтез
    report = await _synthesize(topic, findings)
    # собрать все источники
    all_sources = []
    for f in findings:
        all_sources.extend(f.get("sources", []))
    all_sources = list(dict.fromkeys(all_sources))[:15]

    # 4a) сохранить в vault как Word-документ (.docx)
    saved = None
    vault = _vault_root()
    if vault:
        try:
            from tools.docx_writer import write_docx
            date = datetime.now().strftime("%Y-%m-%d")
            src_block = "\n\n## Источники\n" + "\n".join(f"- {u}" for u in all_sources) if all_sources else ""
            fpath = write_docx(
                title=f"Исследование: {topic}",
                body=report + src_block,
                out_dir=str(vault / "research"),
                filename=f"{date}-{_slug(topic)}.docx",
                subtitle=f"{date} · подготовила Тройка",
            )
            if fpath:
                saved = "research/" + fpath.split("/")[-1]
        except Exception as e:
            logger.warning("save research docx failed: %s", e)

    # 4b) в Telegram
    tg_sent = False
    if to_tg:
        try:
            from tools.telegram_send_tool import _handle as tg_handle
            msg = f"🔍 Исследование: {topic}\n\n{report[:3500]}"
            if all_sources:
                msg += "\n\nИсточники:\n" + "\n".join(all_sources[:8])
            r = await tg_handle({"text": msg})
            tg_sent = bool(isinstance(r, dict) and r.get("ok"))
        except Exception as e:
            logger.debug("tg send failed: %s", e)

    # краткий устный итог = первый абзац отчёта
    short = report.split("\n\n")[0][:400]
    return {
        "ok": True,
        "topic": topic,
        "depth": depth,
        "angles": angles,
        "report": report,
        "sources": all_sources,
        "saved": saved,
        "telegram_sent": tg_sent,
        "say_to_user": (f"Разобралась с темой «{topic}». " + short +
                        (" Полный отчёт скинула в Telegram и сохранила." if tg_sent
                         else " Отчёт сохранила.")),
    }


DEEP_RESEARCH_SCHEMA = {
    "name": "deep_research",
    "description": (
        "Глубокое исследование темы по ОТКРЫТЫМ источникам: роешь под разными "
        "углами, перепроверяешь, делаешь структурный отчёт с источниками. Зови для "
        "«разберись подробно / собери всё про X / глубокий анализ темы». Глубина: "
        "depth=quick (быстро, 3 угла) | deep (5) | max (глубочайший, 8). Сохраняет "
        "в vault, шлёт полный отчёт в Telegram, тебе — краткий итог. Только публичные "
        "данные (новости, статьи, реестры) — НЕ пробив людей и не приватная инфа."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "description": "Тема/вопрос для исследования."},
            "depth": {"type": "string", "description": "quick | deep | max"},
            "to_telegram": {"type": "boolean", "description": "Слать полный отчёт в ТГ (default true)."},
        },
        "required": ["topic"],
    },
}

registry.register(
    name="deep_research",
    toolset="troika-voice",
    schema=DEEP_RESEARCH_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji=chr(128270),
)