"""
learn — быстрое обучение: Тройка изучает материал (ссылку/текст/файл) один раз,
сжимает в конспект и сохраняет, чтобы потом обсуждать его НЕ перечитывая.

Идея самой Тройки (20.06): «скинул книгу или статью — я прочитала и сразу могу
обсуждать, не переспрашивая что там было».

Поток:
  1. Получить материал: url → web_extract; иначе берём text как есть.
  2. Сжать в структурный конспект (тезисы, факты, выводы) через summarizer-LLM.
  3. Сохранить конспект в vault (learned/<slug>.md) + краткий вывод в SOMA,
     чтобы он всплывал в контексте. Вернуть конспект Тройке для обсуждения.

API:
  learn(url=..., topic=...)        — изучить статью/страницу по ссылке
  learn(text="...", topic=...)     — изучить присланный текст
"""
from __future__ import annotations
import logging
import re
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from tools.registry import registry

logger = logging.getLogger(__name__)


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
    for c in [hh / "vault", Path.home() / ".troika" / "vault", hh]:
        if c.exists():
            return c
    return None


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (s or "material").lower()).strip()
    s = re.sub(r"[\s_-]+", "-", s)
    return (s or "material")[:50]


async def _extract(url: Optional[str], text: Optional[str]) -> str:
    if text and text.strip():
        return text.strip()
    if url and url.strip():
        try:
            from tools.web_tools import web_extract_tool
            res = await web_extract_tool(url=url.strip())
            return res if isinstance(res, str) else str(res)
        except Exception as e:
            logger.warning("learn extract failed: %s", e)
            return f"[не удалось извлечь {url}: {e}]"
    return ""


async def _summarize(content: str, topic: str) -> str:
    """Сжать материал в структурный конспект через summarizer-LLM."""
    if len(content) < 50:
        return content
    try:
        from tools.web_tools import process_content_with_llm
        instruction = (
            f"Сделай ПЛОТНЫЙ конспект материала на тему «{topic}» для запоминания. "
            "Формат: 1) суть в 2-3 предложениях; 2) ключевые тезисы/факты списком; "
            "3) выводы или что важно запомнить. По-русски, без воды."
        )
        out = await process_content_with_llm(content, instruction)
        return out if isinstance(out, str) and out.strip() else content[:4000]
    except Exception as e:
        logger.warning("learn summarize failed: %s", e)
        # деградация: грубая обрезка
        return content[:4000]


async def _handle(arguments: Dict[str, Any], **_kw) -> Dict[str, Any]:
    url = (arguments.get("url") or "").strip() or None
    text = (arguments.get("text") or "").strip() or None
    topic = (arguments.get("topic") or "").strip() or (url or "материал")

    if not url and not text:
        return {"ok": False, "error": "missing_input",
                "say_to_user": "Дай ссылку или текст, что изучить."}

    raw = await _extract(url, text)
    if not raw or raw.startswith("[не удалось"):
        return {"ok": False, "error": "extract_failed",
                "say_to_user": "Не смогла прочитать материал.", "detail": raw[:200]}

    summary = await _summarize(raw, topic)

    # сохранить конспект в vault
    saved_path = None
    vault = _vault_root()
    if vault:
        try:
            d = vault / "learned"
            d.mkdir(parents=True, exist_ok=True)
            date = datetime.now().strftime("%Y-%m-%d")
            fname = f"{date}-{_slug(topic)}.md"
            body = (f"---\ntopic: {topic}\nsource: {url or 'text'}\ndate: {date}\n"
                    f"type: learned\n---\n\n# {topic}\n\n{summary}\n")
            (d / fname).write_text(body, encoding="utf-8")
            saved_path = f"learned/{fname}"
        except Exception as e:
            logger.warning("learn save failed: %s", e)

    # короткий вывод в SOMA чтобы всплывал в контексте
    try:
        from tools.soma_tool import soma_remember
        head = summary.split("\n")[0][:200]
        soma_remember({"text": f"Изучила про «{topic}»: {head}", "salience": 0.6})
    except Exception:
        pass

    return {
        "ok": True,
        "topic": topic,
        "summary": summary,
        "saved": saved_path,
        "say_to_user": (f"Изучила «{topic}». " +
                        ("Сохранила конспект, готова обсуждать." if saved_path
                         else "Готова обсуждать.")),
    }


LEARN_SCHEMA = {
    "name": "learn",
    "description": (
        "Изучи материал ОДИН раз и запомни, чтобы потом обсуждать не перечитывая. "
        "Зови когда Миша говорит «прочитай это / разберись в статье / изучи книгу» "
        "и даёт ссылку или текст. Ты вытянешь содержимое, сожмёшь в конспект и "
        "сохранишь — дальше можешь обсуждать по сути."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Ссылка на статью/страницу."},
            "text": {"type": "string", "description": "Или текст материала напрямую."},
            "topic": {"type": "string", "description": "О чём материал (для названия конспекта)."},
        },
        "required": [],
    },
}

registry.register(
    name="learn",
    toolset="memory",
    schema=LEARN_SCHEMA,
    handler=_handle,
    is_async=True,
    emoji=chr(128218),
)