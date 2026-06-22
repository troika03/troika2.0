"""
business_analyst — Тройка как бизнес-консультант и аналитик.

Помогает бизнесу и стартапам ДУМАТЬ, а не просто болтать: анализ конкурентов,
рынка, стратегии и маркетинга — на реальных данных (web-поиск открытых
источников) + мышление через проверенные фреймворки (SWOT, Unit-экономика,
JTBD, AARRR, Lean Canvas, Porter). Выдаёт структурный разбор с выводами,
цифрами и конкретными рекомендациями — а не общие слова.

Режимы (mode):
  competitors — разбор конкурентов: УТП, цены, позиционирование, сильные/слабые,
                где их обойти. Нужен subject (компания/продукт) + опц. market.
  market      — анализ рынка/ниши: объём, тренды, барьеры, точки входа, риски.
  strategy    — стратегический разбор бизнес-идеи/компании: SWOT, гипотезы,
                unit-экономика (что проверить), риски, следующие шаги.
  marketing   — маркетинг: ЦА (JTBD), позиционирование, оффер, каналы, воронка.

Всё на ОТКРЫТЫХ данных. Сохраняет разбор в vault, шлёт в Telegram, даёт
краткий устный итог.

API:
  business_analyst(mode="competitors", subject="наш SaaS для барбершопов",
                   market="бьюти-индустрия РФ", to_telegram=True)
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_RESULTS_PER_QUERY = 4
_EXTRACT_PER_QUERY = 2

# Для каждого режима — какие под-вопросы искать в вебе и какой каркас разбора
# просить у LLM. Каркас = бизнес-фреймворк, чтобы вывод был структурным.
_MODES: Dict[str, Dict[str, Any]] = {
    "competitors": {
        "label": "Анализ конкурентов",
        "queries": [
            "{subject} конкуренты аналоги обзор",
            "{subject} цены тарифы стоимость",
            "{subject} отзывы преимущества недостатки",
            "{market} лидеры рынка кто основные игроки",
        ],
        "frame": (
            "Сделай разбор КОНКУРЕНТОВ по-русски, по структуре:\n"
            "1) Карта игроков — кто основные конкуренты, в 1 строке про каждого.\n"
            "2) Таблица сравнения: игрок | позиционирование/УТП | примерные цены | "
            "сильные стороны | слабые места.\n"
            "3) Свободные ниши и где конкурентов можно обойти (конкретно).\n"
            "4) Чего НЕ хватает на рынке — возможности для дифференциации.\n"
            "Опирайся на материал, цифры приводи где есть. Не выдумывай данные — "
            "если чего-то нет в источниках, отметь это."
        ),
    },
    "market": {
        "label": "Анализ рынка",
        "queries": [
            "{subject} объём рынка размер статистика",
            "{subject} тренды рост прогноз",
            "{subject} барьеры входа регулирование риски",
            "{subject} целевая аудитория спрос",
        ],
        "frame": (
            "Сделай анализ РЫНКА/НИШИ по-русски, по структуре:\n"
            "1) Краткий вывод: стоит ли входить и почему (3-4 предложения).\n"
            "2) Размер и динамика рынка (цифры, тренды).\n"
            "3) Сегменты и целевая аудитория.\n"
            "4) Барьеры входа и риски.\n"
            "5) Точки входа и возможности (где есть незакрытый спрос).\n"
            "Опирайся на материал. Где данных нет — честно отметь, не выдумывай цифры."
        ),
    },
    "strategy": {
        "label": "Стратегический разбор",
        "queries": [
            "{subject} бизнес-модель как зарабатывает",
            "{subject} рынок конкуренты тренды",
            "{subject} проблемы провалы ошибки кейсы",
        ],
        "frame": (
            "Ты — стратегический бизнес-консультант. Разбери идею/компанию по-русски:\n"
            "1) Суть и бизнес-модель (как создаётся и забирается ценность).\n"
            "2) SWOT: сильные, слабые, возможности, угрозы — по 2-3 пункта.\n"
            "3) Unit-экономика: какие метрики критичны (CAC, LTV, маржа, retention) "
            "и что обязательно проверить на цифрах перед масштабированием.\n"
            "4) Ключевые гипотезы и риски — что может убить проект.\n"
            "5) Конкретные следующие 3 шага.\n"
            "Будь прямым и честным, как консультант, которому платят за правду, "
            "а не за комплименты. Опирайся на материал."
        ),
    },
    "marketing": {
        "label": "Маркетинг",
        "queries": [
            "{subject} целевая аудитория кто покупает",
            "{subject} как продвигают маркетинг каналы",
            "{subject} позиционирование оффер уникальность",
        ],
        "frame": (
            "Ты — маркетолог-стратег. Разбери по-русски:\n"
            "1) ЦА через JTBD: какую «работу» клиент нанимает продукт сделать, "
            "сегменты, их боли.\n"
            "2) Позиционирование и УТП — как отстроиться от конкурентов.\n"
            "3) Оффер: что и как предлагать, чтобы цепляло.\n"
            "4) Каналы привлечения — где искать аудиторию (приоритезируй).\n"
            "5) Воронка AARRR: что мерить и где обычно теряются клиенты.\n"
            "Конкретика важнее общих слов. Опирайся на материал."
        ),
    },
}


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
    s = re.sub(r"[^\w\s-]", "", (s or "analysis").lower()).strip()
    return (re.sub(r"[\s_-]+", "-", s) or "analysis")[:50]


async def _gather_query(query: str) -> Dict[str, Any]:
    """Один поисковый под-вопрос: web_search + извлечение топ-страниц."""
    from tools.web_tools import web_search_tool, web_extract_tool
    out = {"query": query, "snippets": [], "pages": [], "sources": []}
    try:
        raw = web_search_tool(query, limit=_RESULTS_PER_QUERY)
        data = json.loads(raw) if isinstance(raw, str) else raw
        results = (data.get("data", {}) or {}).get("web") or data.get("results") or []
    except Exception as e:
        logger.debug("search failed %s: %s", query, e)
        results = []
    urls = []
    for r in results[:_RESULTS_PER_QUERY]:
        title = r.get("title") or ""
        url = r.get("url") or ""
        desc = r.get("description") or r.get("content") or ""
        if desc:
            out["snippets"].append(f"{title}: {desc[:300]}")
        if url:
            out["sources"].append(url)
            urls.append(url)
    for url in urls[:_EXTRACT_PER_QUERY]:
        try:
            ext = await web_extract_tool(url=url)
            txt = ext if isinstance(ext, str) else json.dumps(ext, ensure_ascii=False)
            if txt:
                out["pages"].append(txt[:3000])
        except Exception:
            pass
    return out


def _main_model_kwargs() -> Dict[str, Any]:
    """Прочитать основную модель из config.yaml, чтобы синтез шёл через неё,
    а не через auxiliary-клиент (который отдельно бывает 'exhausted')."""
    try:
        import os, yaml
        hh = os.environ.get("HERMES_HOME") or str(Path.home() / ".troika")
        cfg = yaml.safe_load((Path(hh) / "config.yaml").read_text(encoding="utf-8")) or {}
        m = cfg.get("model", {})
        if isinstance(m, str):
            return {"model": m}
        out = {}
        if m.get("default"):
            out["model"] = str(m["default"]).split("#")[0].strip()
        if m.get("provider"):
            out["provider"] = m["provider"]
        if m.get("base_url"):
            out["base_url"] = m["base_url"]
        return out
    except Exception:
        return {}


async def _synthesize(mode_cfg: Dict[str, Any], subject: str,
                      findings: List[Dict[str, Any]]) -> Optional[str]:
    """Свести материал в структурный бизнес-разбор по каркасу режима.

    Возвращает готовый разбор, либо None если синтез не удался (чтобы
    не сохранять документ с сырым материалом и не врать про результат).
    """
    from tools.web_tools import async_call_llm, extract_content_or_reasoning
    blocks = []
    for f in findings:
        body = "\n".join(f["snippets"][:4] + f["pages"][:1])
        if body.strip():
            blocks.append(f"### По запросу «{f['query']}»\n{body[:1800]}")
    # Урезаем материал, чтобы влезал даже в лимит бесплатной модели (~8k токенов).
    material = "\n\n".join(blocks)[:9000]
    style_rule = (
        "Пиши как живой эксперт-человек, НЕ как ИИ. Запрещены дежурные зачины "
        "(«в заключение», «важно отметить», «в современном мире»), пустые усилители, "
        "натужный энтузиазм, восклицания, симметричные причёсанные списки, вода и "
        "канцелярит. Сразу к сути, конкретика и цифры, живой неровный ритм, своё "
        "мнение и честная оценка. Так, будто несёшь ответственность за текст."
    )
    prompt = (
        f"Объект анализа: «{subject}».\n\n"
        f"{mode_cfg['frame']}\n\n"
        f"СТИЛЬ: {style_rule}\n\n"
        "=== СОБРАННЫЙ МАТЕРИАЛ (открытые источники) ===\n" + material
    )
    model_kwargs = _main_model_kwargs()
    try:
        resp = await async_call_llm(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            **model_kwargs,
        )
        out = extract_content_or_reasoning(resp)
        if out and out.strip() and not out.strip().startswith("###"):
            return out.strip()
        return None
    except Exception as e:
        logger.warning("business_analyst synth failed: %s", e)
        return None


async def _handle(arguments: Dict[str, Any], **_kw) -> Dict[str, Any]:
    mode = (arguments.get("mode") or "strategy").strip().lower()
    subject = (arguments.get("subject") or arguments.get("topic")
               or arguments.get("query") or "").strip()
    market = (arguments.get("market") or "").strip()
    to_tg = arguments.get("to_telegram", True)

    if mode not in _MODES:
        mode = "strategy"
    if not subject:
        return {"ok": False, "error": "missing_subject",
                "say_to_user": "Что разбираем? Назови компанию, продукт или нишу."}

    cfg = _MODES[mode]
    # подставить subject/market в шаблоны запросов
    queries = []
    for q in cfg["queries"]:
        qf = q.replace("{subject}", subject).replace("{market}", market or subject)
        queries.append(qf)

    # параллельно собираем материал по всем под-вопросам
    findings = await asyncio.gather(*[_gather_query(q) for q in queries],
                                    return_exceptions=True)
    findings = [f for f in findings if isinstance(f, dict)]
    if not findings:
        return {"ok": False, "error": "no_data",
                "say_to_user": "Не смогла собрать данные — похоже, поиск недоступен."}

    report = await _synthesize(cfg, subject, findings)
    if not report:
        # Синтез не удался (модель недоступна/лимит). НЕ врём про документ —
        # честно сообщаем, чтобы Тройка не выдумала готовый файл.
        return {"ok": False, "error": "synth_failed",
                "say_to_user": (
                    "Собрала данные, но не смогла свести их в разбор — модель сейчас "
                    "недоступна или превышен лимит. Документ не создавала. "
                    "Похоже, нужно пополнить OpenRouter.")}

    all_sources = []
    for f in findings:
        all_sources.extend(f.get("sources", []))
    all_sources = list(dict.fromkeys(all_sources))[:15]

    # сохранить в vault как Word-документ (.docx) — Миша открывает как обычный документ
    saved = None
    vault = _vault_root()
    if vault:
        try:
            from tools.docx_writer import write_docx
            date = datetime.now().strftime("%Y-%m-%d")
            src_block = "\n\n## Источники\n" + "\n".join(f"- {u}" for u in all_sources) if all_sources else ""
            doc_body = report + src_block
            fpath = write_docx(
                title=f"{cfg['label']}: {subject}",
                body=doc_body,
                out_dir=str(vault / "business"),
                filename=f"{date}-{mode}-{_slug(subject)}.docx",
                subtitle=f"{date} · подготовила Тройка",
            )
            if fpath:
                saved = "business/" + fpath.split("/")[-1]
        except Exception as e:
            logger.warning("save business docx failed: %s", e)

    # в Telegram
    tg_sent = False
    if to_tg:
        try:
            from tools.telegram_send_tool import _handle as tg_handle
            msg = f"📊 {cfg['label']}: {subject}\n\n{report[:3500]}"
            if all_sources:
                msg += "\n\nИсточники:\n" + "\n".join(all_sources[:8])
            r = await tg_handle({"text": msg})
            tg_sent = bool(isinstance(r, dict) and r.get("ok"))
        except Exception as e:
            logger.debug("tg send failed: %s", e)

    short = report.split("\n\n")[0][:400]
    return {
        "ok": True,
        "mode": mode,
        "subject": subject,
        "report": report,
        "sources": all_sources,
        "saved": saved,
        "telegram_sent": tg_sent,
        "say_to_user": (f"{cfg['label']} готов: «{subject}». " + short +
                        (" Полный разбор скинула в Telegram и сохранила."
                         if tg_sent else " Разбор сохранила.")),
    }


BUSINESS_ANALYST_SCHEMA = {
    "name": "business_analyst",
    "description": (
        "Бизнес-консультант и аналитик: помогает бизнесу/стартапу думать на РЕАЛЬНЫХ "
        "данных (web-поиск) через бизнес-фреймворки (SWOT, Unit-экономика, JTBD, AARRR). "
        "Зови когда Миша спрашивает про бизнес: «разбери конкурентов», «проанализируй "
        "рынок/нишу», «оцени бизнес-идею», «как продвигать», «стоит ли запускать». "
        "Режимы mode: competitors (конкуренты: УТП/цены/как обойти) | market (рынок: "
        "объём/тренды/риски) | strategy (SWOT, unit-экономика, гипотезы, шаги) | "
        "marketing (ЦА/позиционирование/оффер/каналы/воронка). subject — что разбираем "
        "(компания/продукт/ниша), market — опц. контекст рынка. Даёт структурный разбор "
        "с выводами, цифрами и конкретными рекомендациями, сохраняет и шлёт в Telegram. "
        "Только открытые источники."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["competitors", "market", "strategy", "marketing"],
                "description": "Режим разбора (по умолчанию strategy).",
            },
            "subject": {
                "type": "string",
                "description": "Что разбираем: компания, продукт, бизнес-идея или ниша.",
            },
            "market": {
                "type": "string",
                "description": "Опц. контекст рынка/отрасли/гео (например «бьюти РФ»).",
            },
            "to_telegram": {
                "type": "boolean",
                "description": "Слать полный разбор в Telegram (по умолчанию true).",
            },
        },
        "required": ["subject"],
    },
}


from tools.registry import registry

registry.register(
    name="business_analyst",
    toolset="business",
    schema=BUSINESS_ANALYST_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji=chr(128202),
)
