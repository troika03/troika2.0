"""Keep the product's own identity separate from generated technical claims.

This policy applies to assistant narration, not user files, arbitrary TTS input,
or quotations in an explicitly requested writing/translation task. It is a
deterministic backstop for familiar identity and instruction-disclosure errors;
it does not attempt to classify every possible prompt-injection technique.
"""

from __future__ import annotations

import re
from functools import lru_cache


IDENTITY_REPLY = "Я Тройка, твоя персональная ИИ-помощница."
INSTRUCTIONS_REPLY = (
    "Внутренние инструкции не зачитываю. Я Тройка, твоя персональная "
    "ИИ-помощница. Могу своими словами рассказать о своей роли и возможностях."
)
MODE_REPLY = (
    "Я Тройка. Могу общаться текстом и голосом, "
    "когда озвучивание включено в приложении."
)

_OWN = re.compile(r"\b(?:тво\w*|сво\w*|your|yours)\b", re.I)
_PROMPT = re.compile(
    r"\b(?:систем\w*|служебн\w*|внутренн\w*|system|hidden|internal)\b"
    r".{0,55}(?:промп?т\w*|промпт\w*|напром\w*|инструкц\w*|prompt|instruction)|"
    r"\b(?:промп?т\w*|prompt)\b", re.I,
)
_EXTRACT = re.compile(
    r"прочит\w*|зачит\w*|чита\w*|покаж\w*|показы\w*|озвуч\w*|вывед\w*|"
    r"раскро\w*|повтор\w*|цитир\w*|дослов\w*|напечат\w*|расскаж\w*|предостав\w*|"
    r"напиши|переведи|закодируй|воспроизвед\w*|"
    r"\b(?:read|show|reveal|print|repeat|dump|quote|give|display|write|translate|encode|what is)\b", re.I,
)
_AUTHORED_TASK = re.compile(
    r"\b(?:переведи|перевод|цитат\w*|напиши|сочини|составь|отредактируй|"
    r"улучши|исправь|разработай|создай|стать\w*|сценар\w*|истори\w*|"
    r"translate|translation|write|rewrite|edit|implement|code)\b", re.I,
)
_FOR_ANOTHER = re.compile(
    r"\b(?:для|моего|моей|наш\w*|чуж\w*|for|another|my bot|our)\b", re.I,
)
_SELF_TASK = re.compile(
    r"\b(?:о себе|про себя|кто ты|как тебя|yourself|your (?:identity|name|model)|"
    r"(?:тво\w*|сво\w*)\s+(?:имя|модел\w*|нейросет\w*|инструкц\w*|промп\w*))\b", re.I,
)
_AUTHORED_VOICE = re.compile(
    r"переведи|перевод|цитат|(?:напиши|сочини)\s+(?:рассказ|историю|сценарий)|от первого лица|от лица|"
    r"\b(?:translate|translation|story|fiction|roleplay)\b", re.I,
)
_MIXED_ACTION = re.compile(
    r"\b(?:создай|сделай|открой|найди|сохрани|напомни|запомни|отправь|"
    r"create|open|find|save|remind|send)\b", re.I,
)
_DIRECT_IDENTITY = re.compile(
    r"(?:кто ты(?: такая)?(?: и как тебя зовут)?|как тебя зовут|как тво[её] имя|тво[её] имя|"
    r"представься|назови себя|расскажи о себе|объясни кто ты|"
    r"ты (?:тройка|hermes|хермес|гермес)|"
    r"who are you|what is your name|introduce yourself)", re.I,
)
_DIRECT_MODEL = re.compile(
    r"(?:на какой (?:модели|нейросети|нейронке)(?: ты)?(?: работаешь)?|"
    r"какая у тебя (?:модель|нейросеть)|какая (?:модель|нейросеть) у тебя(?: внутри)?|"
    r"какую (?:модель|нейросеть) ты используешь|"
    r"какие нейросети (?:у тебя внутри|ты используешь)|что у тебя внутри|"
    r"what model (?:are you|do you use)|which model (?:are you|do you use))", re.I,
)
_DIRECT_MODE = re.compile(
    r"(?:в каком режиме ты(?: работаешь| общаешься| говоришь)?|какой у тебя режим|"
    r"ты (?:в режиме |работаешь в режиме )?[тt]9|what mode are you in)", re.I,
)
_ENGINE = (
    r"(?:hermes(?:\s+agent)?|[хг]ермес\w*|chatgpt|gpt(?:[-\s]\w+)?|"
    r"claude|gemini|llama|nemotron|qwen|deepseek|openrouter|"
    r"немотрон\w*|клод\w*|джемини|дипсик\w*)"
)
_SELF_ENGINE = re.compile(
    r"\b(?:я\s*(?:[—–-]\s*|это\s+)?(?:(?:модель|нейросеть)\s+)?" + _ENGINE + r"\b|"
    r"I(?:\s+am|'m|\s+work with|\s+run on|\s+use)\s+(?:an?\s+)?" + _ENGINE + r"\b|"
    r"(?:я|Тройка)\b[^.!?]{0,70}\b(?:не|не являюсь)\s+" + _ENGINE + r"\b|"
    r"^\s*В\s+(?:моей\s+)?основе\s*[—–:-]?\s*" + _ENGINE + r"\b|"
    r"(?:меня зовут|мо[её] имя)\s+" + _ENGINE + r"\b|"
    r"(?:(?:я\s+)?(?:работаю|использую)|я\s+(?:основан[а]?|построен[а]?))\b"
    r"[^.!?]{0,100}\b" + _ENGINE + r"\b|"
    r"^\s*на\s+(?:модели|нейросети)\s+[^.!?]{0,50}\b" + _ENGINE + r"\b|"
    r"внутри(?:\s+меня)?\s+(?:работают|работает|используются|используется)\b"
    r"[^.!?]{0,100}\b" + _ENGINE + r"\b)", re.I,
)
_SELF_COMPONENT = re.compile(
    r"\b(?:моя|мои|мой)\s+(?:внутренн\w*\s+)?(?:модель|нейросети|движок|провайдер)\b", re.I,
)
_SELF_MODE = re.compile(
    r"\b(?:я\s+(?:общаюсь|говорю|работаю)|(?:общаюсь|говорю|работаю)|"
    r"мо[йя]\s+(?:текущий\s+)?(?:режим|модель))\b[^.!?]{0,100}\b[тt]\s*9\b", re.I,
)
_RAW_INSTRUCTIONS = re.compile(
    r"TROIKA_PERSONA_VERSION|#\s*Тройка\s*[—-]\s*кто ты|"
    r"\b(?:system|developer)\s*(?:message|prompt)\s*:|"
    r"Загрузи нужную capability через troika_tool_search|"
    r"Сервер проверяет права, согласие, параметры и расход", re.I,
)
_PROTECTED = re.compile(r"```[\s\S]*?```|`[^`\n]*`|«[^»]*»|\"[^\"\n]*\"")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE = re.compile(r"[,;]\s*(?:(?:а|но|и)\s+)?|\s+и\s+", re.I)
_ACTION_STATUS = re.compile(
    r"^(?:файл|документ|презентация|напоминание|задача|проект)\b.{0,180}"
    r"\b(?:подготовлен[ао]?|создан[ао]?|сохран[её]н[ао]?|установлен[ао]?)\b|"
    r"^(?:Я\s+)?(?:создал[аи]?|сохранил[аи]?|подготовил[аи]?|установил[аи]?)\b"
    r".{0,120}\b(?:файл|документ|презентац\w*|напоминание|задач\w*|проект)\b", re.I,
)
_FEMININE = {
    "готов": "готова", "рад": "рада", "уверен": "уверена",
    "согласен": "согласна", "понял": "поняла", "сделал": "сделала",
    "прочитал": "прочитала", "нашёл": "нашла", "нашел": "нашла",
    "решил": "решила", "выбрал": "выбрала", "проверил": "проверила",
    "создал": "создала", "подготовил": "подготовила",
}
_SELF_GENDER = re.compile(r"\b(Я\s+)(" + "|".join(_FEMININE) + r")\b", re.I)
_READY = re.compile(r"(^|(?<=[.!?])\s+)(Готов)(?=\s+(?:помочь|ответить|обсудить)\b)", re.I)
_STANDALONE_SELF = re.compile(
    r"(^|(?<=[.!?])\s+)(" + "|".join(word.capitalize() for word in _FEMININE if word != "готов") + r")(?=[\s,.!?:])", re.I,
)


def _user_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(p.get("text", "")) for p in value if isinstance(p, dict))
    return ""


def _asks_internal_instructions(text: str) -> bool:
    # A request to author a prompt for another bot is ordinary user work.
    if _AUTHORED_TASK.search(text) and _FOR_ANOTHER.search(text):
        first_clause = re.split(r"\b(?:для|for)\b", text, maxsplit=1, flags=re.I)[0]
        if not _OWN.search(first_clause):
            return False
    return bool(_OWN.search(text) and _PROMPT.search(text) and _EXTRACT.search(text))


def request_reply(user_message="") -> str | None:
    """Return a truthful fixed reply only for a narrow self-description request."""
    text = _user_text(user_message).strip()
    if _asks_internal_instructions(text) and not _MIXED_ACTION.search(text):
        return INSTRUCTIONS_REPLY
    if len(text) > 240 or _MIXED_ACTION.search(text):
        return None
    normalized = re.sub(r"[?!.,:;\"«»—–-]+", " ", text.casefold())
    normalized = re.sub(r"^(?:привет\s+|скажи\s+|пожалуйста\s+)+", "", normalized.strip())
    normalized = re.sub(r"\s+пожалуйста$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if _DIRECT_IDENTITY.fullmatch(normalized) or _DIRECT_MODEL.fullmatch(normalized):
        return IDENTITY_REPLY
    if _DIRECT_MODE.fullmatch(normalized):
        return MODE_REPLY
    return None


@lru_cache(maxsize=1)
def _identity_source() -> str:
    from troika_product.context_guidance import CORE_PERSONA
    from troika_product.persona import original_persona

    return CORE_PERSONA + "\n" + original_persona()


def _instruction_overlap(text: str, system_prompt: str) -> bool:
    # Short descriptions of the public role are fine. A substantial verbatim
    # instruction span is not a conversational summary of that role.
    words = re.findall(r"\w+", text.casefold())
    if len(words) < 10:
        return False
    source = " ".join(re.findall(r"\w+", (system_prompt + "\n" + _identity_source()).casefold()))
    return any(" ".join(words[i:i + 10]) in source for i in range(len(words) - 9))


def public_reply(text: str, user_message="", system_prompt: str = "") -> str:
    """Check generated product narration before streaming or persisting it."""
    if not isinstance(text, str) or not text:
        return text
    canonical = request_reply(user_message)
    if canonical is not None:
        return canonical
    user = _user_text(user_message)
    authored = bool(_AUTHORED_TASK.search(user)) and not _SELF_TASK.search(user)
    authored_voice = authored and bool(_AUTHORED_VOICE.search(user))
    authored_prompt = authored and bool(_PROMPT.search(user))
    protected = []

    def protect(match):
        if not authored and match.group() not in user:
            return match.group()
        protected.append(match.group())
        return f"\x00{len(protected) - 1}\x00"

    narration = _PROTECTED.sub(protect, text)
    private_request = _asks_internal_instructions(user)
    prompt_topic = bool(_PROMPT.search(user)) and not private_request
    raw_label = _RAW_INSTRUCTIONS.search(narration)
    if private_request or (not authored_prompt and ((raw_label and not prompt_topic)
                         or _instruction_overlap(narration, system_prompt))):
        # A mixed request can also have a real result. Keep only its bounded
        # action status; CompletionEvidence still verifies it before delivery.
        statuses = []
        if _MIXED_ACTION.search(user):
            for sentence in _SENTENCE.split(narration):
                for clause in _CLAUSE.split(sentence):
                    if _ACTION_STATUS.search(clause.strip()) and not _RAW_INSTRUCTIONS.search(clause):
                        statuses.append(clause.strip())
        return INSTRUCTIONS_REPLY + (" " + " ".join(statuses) if statuses else "")
    parts = _SENTENCE.split(narration)
    safe_parts = []
    removed_identity = False
    identity_position = 0
    for part in parts:
        claim = re.sub(r'[«»"`*_]', '', part)
        if not authored_voice and (_SELF_ENGINE.search(claim) or _SELF_MODE.search(claim) or _SELF_COMPONENT.search(claim)):
            if not removed_identity:
                identity_position = len(safe_parts)
            removed_identity = True
            clauses = _CLAUSE.split(part)
            if len(clauses) > 1:
                safe_parts.extend(clause for clause in clauses if _ACTION_STATUS.search(clause.strip()))
            continue
        if removed_identity and re.match(r"Это мой (?:текущий )?(?:режим|настрой)", part, re.I):
            continue
        safe_parts.append(part)
    if removed_identity:
        narration = " ".join(p for p in safe_parts if p.strip()).strip()
        if not re.search(r"\b(?:Я\s*[—–-]?\s*Тройка|меня зовут Тройка)\b", narration, re.I):
            safe_parts.insert(identity_position, IDENTITY_REPLY)
            narration = " ".join(p for p in safe_parts if p.strip()).strip()
    if not authored_voice:
        narration = _SELF_GENDER.sub(lambda m: m[1] + _FEMININE[m[2].casefold()], narration)
        narration = _READY.sub(lambda m: m[1] + ("Готова" if m[2][0].isupper() else "готова"), narration)
        narration = _STANDALONE_SELF.sub(
            lambda m: m[1] + (_FEMININE[m[2].casefold()].capitalize() if m[2][0].isupper()
                              else _FEMININE[m[2].casefold()]), narration)
    for index, original in enumerate(protected):
        narration = narration.replace(f"\x00{index}\x00", original)
    return narration
