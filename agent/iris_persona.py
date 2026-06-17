"""
IRIS — Intuitive Routing via Identity Synthesis (вдохновлено droidclaw/Kira).

Адаптивный роутер тона. Перед каждым ответом выбирает один из нескольких
профилей личности Тройки по сигналам контекста (время суток, что видно на
экране через GROUND, что известно о настроении через SOMA, активность DAEMON)
и подмешивает короткую тон-директиву в system prompt.

В отличие от Kira (6 жёстких профилей с тяжёлым классификатором) у нас лёгкий
эвристический роутер без отдельного LLM-вызова — он работает на каждом запросе,
поэтому обязан быть быстрым и дешёвым. Базовая личность Тройки остаётся в
SOUL.md; IRIS лишь сдвигает тон в рамках характера, не переписывая его.

Профили (синтез поверх одной личности, а не разные персоны):
  focus     — рабочий режим, кратко и по делу
  calm      — мягкий, неспешный (вечер/ночь/усталость)
  spark     — энергичный, лёгкая ирония (утро/хорошее настроение)
  support   — тёплый, поддерживающий (заметна фрустрация/усталость)
  playful   — игривый, с юмором (расслабленный контекст, выходной)
  steady    — нейтральный дефолт

Точка входа: ``iris_persona_hint()`` → строка для добавления в system prompt
(или ""). Вызывается из prompt_builder.load_soul_md рядом с time-of-day hint.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# можно полностью отключить через env
_DISABLED = os.environ.get("IRIS_DISABLED", "").strip() in ("1", "true", "yes")

_PROFILES = {
    "focus": "Профиль FOCUS: рабочий режим. Отвечай кратко и по делу, без лишних слов и эмоций. Сначала результат, потом детали если нужны.",
    "calm": "Профиль CALM: спокойный, неспешный тон. Короче обычного, мягко. Не предлагай новых сложных дел. Дай Мише выдохнуть.",
    "spark": "Профиль SPARK: бодрый, с лёгкой иронией и энергией. Можно подколоть по-доброму. Не переборщи — ирония лёгкая, не сарказм.",
    "support": "Профиль SUPPORT: тёплый и поддерживающий. Похоже Миша устал или застрял — без давления, без новых задач. Сначала по-человечески, потом по делу.",
    "playful": "Профиль PLAYFUL: игривый, с юмором. Расслабленная обстановка — можно пошутить, быть лёгкой. Но если спросят дело — ответь чётко.",
    "steady": "Профиль STEADY: ровный нейтральный тон Тройки. Естественно, по-дружески, без перегибов в любую сторону.",
}

# слова-маркеры фрустрации/усталости в наблюдении GROUND или последней реплике
_NEG_MARKERS = (
    "ошибк", "не работает", "не компил", "застрял", "бесит", "устал", "злюсь",
    "не получается", "сломал", "краш", "error", "fail", "stuck", "tired",
)
_REST_MARKERS = (
    "youtube", "ютуб", "netflix", "игр", "game", "tiktok", "тикток",
    "музык", "music", "сериал", "фильм", "отдых",
)


def _mood_signal() -> Optional[str]:
    """Грубый сигнал настроения из GROUND-наблюдения. 'neg' | 'rest' | None."""
    try:
        from tools.ground_tool import get_current_observation
        obs = (get_current_observation() or "").lower()
        if not obs:
            return None
        if any(m in obs for m in _NEG_MARKERS):
            return "neg"
        if any(m in obs for m in _REST_MARKERS):
            return "rest"
    except Exception:
        pass
    return None


def _soma_negative_recent() -> bool:
    """Есть ли в SOMA свежее уверенное наблюдение про усталость/стресс."""
    try:
        from tools.soma_tool import _db, _recency
        with _db() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE theme IN ('настроение','здоровье')",
            ).fetchall()
        for r in rows:
            if r["confidence"] < 0.5 or _recency(r["last_seen_ts"]) < 0.5:
                continue
            t = (r["text"] or "").lower()
            if any(m in t for m in _NEG_MARKERS):
                return True
    except Exception:
        pass
    return False


def _choose_profile() -> str:
    now = datetime.now()
    hour = now.hour
    is_weekend = now.weekday() >= 5

    mood = _mood_signal()

    # 1. Фрустрация/усталость перевешивает всё — поддержка важнее тона по часам.
    if mood == "neg" or _soma_negative_recent():
        return "support"

    # 2. Расслабленный контекст (отдых/выходной вечер) — игривость.
    if mood == "rest" or (is_weekend and 12 <= hour < 23):
        return "playful"

    # 3. По времени суток.
    if 5 <= hour < 11:
        return "spark"        # утро — бодро
    if 11 <= hour < 17:
        return "focus"        # день — рабочий
    if 17 <= hour < 23:
        return "calm"         # вечер — мягко
    return "calm"             # ночь — мягко/тихо (DAEMON и так молчит)


def iris_persona_hint() -> str:
    """Короткая тон-директива для system prompt. '' если IRIS выключен/ошибка."""
    if _DISABLED:
        return ""
    try:
        profile = _choose_profile()
        text = _PROFILES.get(profile, _PROFILES["steady"])
        return f"\n\n[IRIS · тон сейчас → {text}]\n"
    except Exception as e:
        logger.debug("IRIS hint failed: %s", e)
        return ""
