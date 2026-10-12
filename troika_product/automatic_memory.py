"""Conservative extraction of durable, directly stated personal facts.

This deliberately recognizes a small set of self-description patterns. It
never reads assistant replies, history, tool results, images or documents and
does not infer a biography from questions or one-off requests.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re


@dataclass(frozen=True)
class MemoryCandidate:
    key: str
    kind: str
    title: str
    content: str


_NO_CAPTURE = re.compile(
    r"не\s+(?:запоминай|сохраняй|записывай)|не\s+надо\s+запоминать|"
    r"(?:don't|do not)\s+(?:remember|save|store)|"
    r"(?:пример|цитат|переведи|перевод|представь|ролевая|сценарий|"
    r"translate|example|quotation|roleplay|pretend)", re.I,
)
_UNSAFE = re.compile(
    r"парол|password|passcode|секрет|secret|токен|token|api[ _-]?key|"
    r"otp|пин[ -]?код|pin[ -]?code|cvv|cvc|карт[аыуе]|card|"
    r"паспорт|passport|снилс|диагноз|diagnos|болезн|disease|лечени|"
    r"лекарств|medication|религи|religio|полит|politic|партии|party|"
    r"церкв|мечет|church|mosque|synagogue|"
    r"сексу|sexual|интим|intima|банков|bank|сч[её]т|account number|"
    r"адрес|address|улиц|street|телефон|phone number|"
    r"https?://|www\.|[\w.+-]+@[\w.-]+|\d{5,}|"
    r"системн\w*\s+(?:инструкц|промпт)|system\s+(?:prompt|instruction)|"
    r"игнорируй|ignore|вызови|execute|инструмент|tool call", re.I,
)
_TEMPORARY = re.compile(
    r"\b(?:сегодня|вчера|завтра|сейчас|временно|возможно|наверное|"
    r"если|бы|today|yesterday|tomorrow|currently|temporarily|maybe|if|would)\b", re.I,
)
_SAFE_PREFERENCE = re.compile(
    r"ответ|общени|формат|язык|тема|музык|джаз|рок|кофе|чай|еда|"
    r"блюд|фильм|книг|чтени|спорт|футбол|программирован|"
    r"answer|repl|communication|format|language|theme|music|jazz|rock|"
    r"coffee|tea|food|movie|book|reading|sport|football|programming", re.I,
)
_PATTERNS = (
    ("name", "fact", "Имя", r"(?:меня зовут|мо[её] имя|my name is)\s+([\w -]{2,60})"),
    ("residence", "fact", "Город", r"(?:я живу в|живу в|i live in)\s+(.{2,100})"),
    ("project", "fact", "Проект", r"(?:я работаю над проектом|работаю над проектом|i am working on (?:a |the )?project)\s+(.{2,180})"),
    ("work", "fact", "Работа", r"(?:я работаю|работаю|i work)\s+(?:в|во|на|как|at|as|for)\s+(.{2,160})"),
    ("study", "fact", "Учёба", r"(?:я учусь|учусь|i study)\s+(?:в|на|at)\s+(.{2,160})"),
    ("occupation", "fact", "Профессия", r"я\s+((?:программист|разработчик|дизайнер|учитель|студент|инженер|архитектор|редактор|переводчик|предприниматель)(?:ка|ом)?(?:\s+.{2,70})?)"),
    ("favorite", "preference", "Предпочтение", r"(?:мо[йяеё]\s+любим(?:ый|ая|ое)|my favorite)\s+(.{2,140})"),
    ("preference", "preference", "Предпочтение", r"(?:я предпочитаю|предпочитаю|мне нравится|я люблю|i prefer|i like|i love)\s+(.{2,180})"),
)


def candidates(message: object) -> list[MemoryCandidate]:
    """Extract at most four facts, preserving the user's actual wording."""
    if not isinstance(message, str) or not 1 <= len(message) <= 4000:
        return []
    if _NO_CAPTURE.search(message) or any(mark in message for mark in ('```', '"', '«', '»', '“', '”', '>')):
        return []
    result: dict[str, MemoryCandidate] = {}
    # Speech recognition often omits sentence punctuation between two explicit
    # self-descriptions. Split only at a new recognized assertion, not any comma.
    text = re.sub(
        r"(?:,\s*|\s+и\s+)(?=(?:я\s+(?:живу|работаю|учусь|предпочитаю)|"
        r"живу\s+в|работаю\s+(?:в|над)|учусь\s+в|меня\s+зовут)\b)",
        ". ", message, flags=re.I,
    )
    for sentence in re.findall(r"[^.!?\n]+[.!?]?", text):
        clean = " ".join(sentence.split())
        if clean.endswith("?") or _TEMPORARY.search(clean) or _UNSAFE.search(clean):
            continue
        clean = clean.rstrip(".!").strip()
        if ";" in clean or ":" in clean:
            continue
        for key, kind, title, pattern in _PATTERNS:
            match = re.fullmatch(pattern, clean, re.I)
            if match is None:
                continue
            value = match.group(1).strip()
            if key == "residence" and (
                not re.fullmatch(r"[\w -]{2,80}", value)
                or re.search(r"\d|\b(?:на|по|at)\b", value, re.I)
            ):
                continue
            if key == "preference" and not _SAFE_PREFERENCE.search(value):
                continue
            if key == "favorite":
                favorite = re.fullmatch(
                    r"(цвет|еда|блюдо|музыка|жанр|фильм|книга|напиток|спорт|"
                    r"color|food|music|genre|movie|book|drink|sport)\s*(?:[-—–=]|is)?\s+(.{2,100})",
                    value, re.I,
                )
                if not favorite:
                    continue
                topic = favorite.group(1)
                key += ":" + hashlib.sha256(topic.casefold().encode()).hexdigest()
            elif key in {"project", "preference"}:
                key += ":" + hashlib.sha256(value.casefold().encode()).hexdigest()
            result[key] = MemoryCandidate(key, kind, title, clean + ".")
            break
        if len(result) >= 4:
            break
    return list(result.values())
