"""
SOMA — Self-Organizing Memory Architecture (вдохновлено droidclaw/Kira).

Память Тройки с эмоциональным весом и байесовской уверенностью. В отличие от
project-памяти (голые факты в vault) и diary (поток событий), SOMA хранит
выводы О ПОЛЬЗОВАТЕЛЕ с метаданными:

  • salience   — насколько это эмоционально/практически важно (0..1)
  • confidence — насколько Тройка уверена что это правда (0..1, растёт при
                 повторном подтверждении по байесовскому обновлению)
  • theme      — психологический кластер ('привычки', 'настроение', 'работа',
                 'предпочтения', 'отношения', ...), а не лог активности
  • reinforced — сколько раз наблюдение подтверждалось

Хранение: SQLite ~/.troika/soma.db (как jobs.db). Дублирующиеся наблюдения не
плодятся — похожее усиливает существующую запись (confidence↑). Recall ранжирует
по salience × confidence × свежесть, группируя по темам.

Зеркало для чтения человеком пишется в vault/soma/<theme>.md (best-effort).

Tools:
  • soma_remember — записать/усилить вывод о пользователе
  • soma_recall   — вспомнить релевантное (по запросу или теме)
  • soma_forget   — удалить ошибочное наблюдение
"""

from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TROIKA = Path.home() / ".troika"
_DB_PATH = _TROIKA / "soma.db"

# Зеркало в vault (для чтения человеком). Берём тот же vault что и diary.
_DEFAULT_VAULT = Path("C:/Users/kiqu/.claude/projects/d--troikahermes/memory")
_VAULT = Path(os.environ.get("HERMES_MEMORY_VAULT") or _DEFAULT_VAULT)
_SOMA_DIR = _VAULT / "soma"

# Полупериод «забывания»: за сколько секунд свежесть падает вдвое (~30 дней).
_RECENCY_HALFLIFE_SEC = 30 * 24 * 3600
# Порог похожести (доля общих значимых слов), выше которого считаем «то же наблюдение».
_SIMILARITY_THRESHOLD = 0.55

_KNOWN_THEMES = (
    "привычки", "настроение", "работа", "предпочтения",
    "отношения", "здоровье", "цели", "быт", "прочее",
)


# --- БД ----------------------------------------------------------------------

@contextmanager
def _db():
    _TROIKA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                theme TEXT NOT NULL DEFAULT 'прочее',
                salience REAL NOT NULL DEFAULT 0.5,
                confidence REAL NOT NULL DEFAULT 0.5,
                reinforced INTEGER NOT NULL DEFAULT 0,
                created_ts REAL NOT NULL,
                last_seen_ts REAL NOT NULL
            )
            """
        )
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- утилиты -----------------------------------------------------------------

def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_STOP = {
    "и", "в", "на", "с", "что", "это", "он", "она", "его", "её", "как", "не",
    "а", "но", "по", "за", "то", "же", "бы", "к", "у", "о", "от", "для",
    "the", "a", "is", "to", "of", "and", "in", "he", "she", "it",
}


def _tokens(text: str) -> set:
    return {w.lower() for w in _WORD_RE.findall(text or "") if w.lower() not in _STOP and len(w) > 2}


def _similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return inter / min(len(ta), len(tb))


def _recency(last_seen_ts: float) -> float:
    age = max(0.0, time.time() - last_seen_ts)
    return math.pow(0.5, age / _RECENCY_HALFLIFE_SEC)


def _normalize_theme(theme: Optional[str]) -> str:
    t = (theme or "").strip().lower()
    return t if t in _KNOWN_THEMES else (t or "прочее")


def _bayes_reinforce(prior: float, observation_conf: float = 0.7) -> float:
    """Простое байесовское усиление: повторное подтверждение поднимает confidence,
    но с убывающей отдачей (не выходит за ~0.98)."""
    odds_prior = prior / max(1e-6, 1 - prior)
    odds_lr = observation_conf / max(1e-6, 1 - observation_conf)
    posterior_odds = odds_prior * odds_lr
    return _clamp(posterior_odds / (1 + posterior_odds), 0.02, 0.98)


def _mirror_to_vault(theme: str) -> None:
    """Best-effort: пишем человекочитаемое зеркало темы в vault."""
    try:
        _SOMA_DIR.mkdir(parents=True, exist_ok=True)
        with _db() as conn:
            rows = conn.execute(
                "SELECT text, salience, confidence, reinforced, last_seen_ts "
                "FROM memories WHERE theme=? ORDER BY salience*confidence DESC",
                (theme,),
            ).fetchall()
        path = _SOMA_DIR / f"{theme}.md"
        lines = [
            "---",
            f"name: soma-{theme}",
            f"description: SOMA-память Тройки, тема «{theme}»",
            "metadata:",
            "  node_type: memory",
            "  type: soma",
            "---",
            "",
            f"# SOMA · {theme}",
            "",
        ]
        for r in rows:
            stars = "★" * round(r["salience"] * 5)
            lines.append(
                f"- {r['text']}  ·  важность {stars or '·'} "
                f"уверенность {r['confidence']:.0%} (подтверждений: {r['reinforced']})"
            )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as e:
        logger.debug("SOMA vault mirror failed: %s", e)


# --- handlers ----------------------------------------------------------------

async def _handle_remember(args: Dict[str, Any], **_kw) -> Dict[str, Any]:
    text = (args.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "missing_text"}
    if len(text) > 400:
        text = text[:400] + "…"

    theme = _normalize_theme(args.get("theme"))
    try:
        salience = _clamp(float(args.get("salience", 0.5)))
    except (TypeError, ValueError):
        salience = 0.5

    with _db() as conn:
        # Ищем похожее в той же теме → усиливаем вместо дублирования
        candidates = conn.execute(
            "SELECT * FROM memories WHERE theme=?", (theme,),
        ).fetchall()
        match = None
        for row in candidates:
            if _similarity(text, row["text"]) >= _SIMILARITY_THRESHOLD:
                match = row
                break

        now = time.time()
        if match:
            new_conf = _bayes_reinforce(match["confidence"])
            new_sal = _clamp(max(match["salience"], salience) * 0.7 + salience * 0.3)
            conn.execute(
                "UPDATE memories SET confidence=?, salience=?, reinforced=reinforced+1, "
                "last_seen_ts=? WHERE id=?",
                (new_conf, new_sal, now, match["id"]),
            )
            result = {
                "ok": True, "action": "reinforced", "id": match["id"],
                "confidence": round(new_conf, 2), "reinforced": match["reinforced"] + 1,
                "say_to_user": "Это укрепило то, что я уже о тебе знаю.",
            }
        else:
            cur = conn.execute(
                "INSERT INTO memories (text, theme, salience, confidence, reinforced, "
                "created_ts, last_seen_ts) VALUES (?,?,?,?,0,?,?)",
                (text, theme, salience, 0.5, now, now),
            )
            result = {
                "ok": True, "action": "created", "id": cur.lastrowid,
                "theme": theme, "say_to_user": "Запомнила.",
            }

    _mirror_to_vault(theme)
    return result


async def _handle_recall(args: Dict[str, Any], **_kw) -> Dict[str, Any]:
    query = (args.get("query") or "").strip()
    theme = args.get("theme")
    limit = max(1, min(int(args.get("limit", 8) or 8), 25))

    with _db() as conn:
        if theme:
            rows = conn.execute(
                "SELECT * FROM memories WHERE theme=?", (_normalize_theme(theme),),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM memories").fetchall()

    if not rows:
        return {"ok": True, "memories": [], "say_to_user": "Пока ничего такого о тебе не помню."}

    scored = []
    q_tokens = _tokens(query) if query else set()
    for r in rows:
        rel = 1.0
        if q_tokens:
            rt = _tokens(r["text"])
            rel = (len(q_tokens & rt) / len(q_tokens)) if q_tokens else 0.0
            if rel == 0.0:
                continue  # запрос задан, но совпадений нет — пропускаем
        score = r["salience"] * r["confidence"] * _recency(r["last_seen_ts"]) * (0.4 + 0.6 * rel)
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    memories = [
        {
            "text": r["text"], "theme": r["theme"],
            "salience": round(r["salience"], 2),
            "confidence": round(r["confidence"], 2),
            "reinforced": r["reinforced"],
        }
        for _, r in top
    ]
    return {"ok": True, "count": len(memories), "memories": memories}


async def _handle_forget(args: Dict[str, Any], **_kw) -> Dict[str, Any]:
    mem_id = args.get("id")
    query = (args.get("query") or "").strip()
    with _db() as conn:
        if mem_id is not None:
            conn.execute("DELETE FROM memories WHERE id=?", (int(mem_id),))
            return {"ok": True, "deleted_by": "id", "id": mem_id, "say_to_user": "Забыла."}
        if query:
            rows = conn.execute("SELECT * FROM memories").fetchall()
            target = None
            best = 0.0
            for r in rows:
                s = _similarity(query, r["text"])
                if s > best:
                    best, target = s, r
            if target and best >= _SIMILARITY_THRESHOLD:
                conn.execute("DELETE FROM memories WHERE id=?", (target["id"],))
                return {"ok": True, "deleted_by": "match", "text": target["text"],
                        "say_to_user": "Забыла."}
            return {"ok": False, "error": "no_match", "say_to_user": "Не нашла что забыть."}
    return {"ok": False, "error": "need_id_or_query"}


# --- schemas -----------------------------------------------------------------

REMEMBER_SCHEMA = {
    "name": "soma_remember",
    "description": (
        "Запомнить ВЫВОД о пользователе с эмоциональным весом (SOMA). Не голый факт "
        "(для фактов — obsidian_note), а наблюдение о его привычках, настроении, "
        "предпочтениях. Например: 'Миша нервничает когда код не компилится', 'любит "
        "работать ночью', 'радуется когда с первого раза'. Если похожее уже знаю — "
        "это усилит уверенность, а не создаст дубль."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Наблюдение о пользователе, 1-2 фразы."},
            "theme": {
                "type": "string",
                "description": "Тема-кластер: привычки|настроение|работа|предпочтения|отношения|здоровье|цели|быт|прочее.",
            },
            "salience": {
                "type": "number",
                "description": "Эмоциональная/практическая важность 0..1 (0.8+ для сильных, 0.3 для проходных). Default 0.5.",
            },
        },
        "required": ["text"],
    },
}

RECALL_SCHEMA = {
    "name": "soma_recall",
    "description": (
        "Вспомнить что Тройка знает о пользователе (SOMA), ранжируя по важности, "
        "уверенности и свежести. Используй чтобы персонализировать ответ: перед "
        "советом, реакцией, при вопросах 'что ты обо мне знаешь', 'какой я по-твоему'. "
        "Можно фильтровать по теме или искать по запросу."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "О чём вспомнить (опц.). Пусто = самое важное в целом."},
            "theme": {"type": "string", "description": "Ограничить темой (опц.)."},
            "limit": {"type": "integer", "description": "Сколько вернуть (1..25, default 8)."},
        },
    },
}

FORGET_SCHEMA = {
    "name": "soma_forget",
    "description": "Удалить ошибочное наблюдение из SOMA. Используй когда пользователь говорит 'это неправда', 'забудь что я...'. Укажи id (из soma_recall) или query с текстом наблюдения.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "ID наблюдения из soma_recall."},
            "query": {"type": "string", "description": "Текст наблюдения для поиска и удаления."},
        },
    },
}


# --- context hint (авто-инжект памяти в промпт) ------------------------------


# Параметры авто-инжекта памяти в промпт. Урезаны намеренно: на слабой модели
# дамп всех выводов о Мише в КАЖДЫЙ запрос растаскивает внимание («путается,
# когда всё в одном месте»). Меньше, но увереннее — лучше держит фокус.
# Всё переопределяемо через env, старое поведение восстановимо.
_CTX_LIMIT = int(os.environ.get("SOMA_CONTEXT_LIMIT", "3"))            # было 6
_CTX_MIN_CONF = float(os.environ.get("SOMA_CONTEXT_MIN_CONF", "0.55")) # было 0.45
# Порог релевантности к текущей реплике (если она передана). Ниже — вывод
# считаем не относящимся к делу и не подмешиваем.
_CTX_MIN_REL = float(os.environ.get("SOMA_CONTEXT_MIN_REL", "0.15"))


def soma_context_hint(limit: Optional[int] = None, query: Optional[str] = None) -> str:
    """Топ выводов о Мише для подмешивания в system prompt.

    Это Этап «память→мнения»: Тройка не ждёт явного soma_recall, а держит в
    голове самое весомое о Мише (привычки, предпочтения, настроение).

    Два режима:
      • query задан → ранжируем по РЕЛЕВАНТНОСТИ к текущей реплике (как
        soma_recall): salience × confidence × свежесть × релевантность.
        Выводы, никак не пересекающиеся с репликой, отбрасываем — память
        подмешивается только когда реально относится к делу. Это лечит
        «мозг путается, когда всё свалено в одно место»: служебные реплики
        («который час») не тащат за собой досье на Мишу.
      • query пуст (напр. кешируемый system prompt сессии) → старое поведение:
        топ по salience × confidence × свежесть, без фильтра релевантности.

    Берём только достаточно уверенные выводы (confidence ≥ _CTX_MIN_CONF),
    чтобы не тащить домыслы. Количество урезано до _CTX_LIMIT.
    """
    limit = _CTX_LIMIT if limit is None else limit
    try:
        with _db() as conn:
            rows = conn.execute("SELECT * FROM memories").fetchall()
    except Exception as e:  # БД может быть пустой/недоступной — не ломаем промпт
        logger.debug("soma_context_hint: %s", e)
        return ""
    if not rows:
        return ""

    q_tokens = _tokens(query) if query else set()
    scored = []
    for r in rows:
        if r["confidence"] < _CTX_MIN_CONF:
            continue
        rel = 1.0
        if q_tokens:
            rt = _tokens(r["text"])
            rel = (len(q_tokens & rt) / len(q_tokens)) if q_tokens else 0.0
            if rel < _CTX_MIN_REL:
                continue  # реплика задана, но этот вывод к ней не относится
        score = r["salience"] * r["confidence"] * _recency(r["last_seen_ts"]) * (0.4 + 0.6 * rel)
        scored.append((score, r))
    if not scored:
        return ""
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:limit]

    lines = []
    for _, r in top:
        # маркер уверенности: ↑ — твёрдо знаю, ~ — скорее так
        mark = "" if r["confidence"] >= 0.7 else "(возможно) "
        lines.append(f"• {mark}{r['text'].strip()}")

    body = "\n".join(lines)
    return (
        "\n\n## Что ты знаешь о Мише (из своей памяти)\n"
        "Это твои накопленные выводы о нём — пользуйся ими естественно, "
        "не зачитывай вслух и не ссылайся на «память», просто учитывай:\n"
        f"{body}"
    )


# --- registration ------------------------------------------------------------

from tools.registry import registry  # noqa: E402

registry.register(name="soma_remember", toolset="memory", schema=REMEMBER_SCHEMA,
                  handler=_handle_remember, is_async=True, emoji="🧠")
registry.register(name="soma_recall", toolset="memory", schema=RECALL_SCHEMA,
                  handler=_handle_recall, is_async=True, emoji="🧠")
registry.register(name="soma_forget", toolset="memory", schema=FORGET_SCHEMA,
                  handler=_handle_forget, is_async=True, emoji="🧠")
