"""
WORKSPACE — второй «рабочий стол» Тройки (Kali-окружение).

Тройка по команде переключает СВОЙ терминал в изолированный Docker-контейнер
(Kali и т.п.) на время текущей сессии, гоняет там инструменты, потом
возвращается. Переключение per-session: «перейди в кали» влияет только на
текущий разговор, не на DAEMON и параллельные сессии (реализовано через
gateway/session_context overrides, которые читает terminal_tool._get_env_config).

Изоляция (см. tools/environments/docker.py — backend уже hardened):
  • API-ключи Тройки НЕ пробрасываются в контейнер;
  • том /work персистентный — результаты переживают пересоздание;
  • для «без лимитов» режима пробрасываются capabilities/privileged через
    docker_extra_args (по конфигу окружения), но секреты — никогда.

Гейт целей (решение Миши): подтверждение АВТОРИЗАЦИИ один раз на сессию.
Тройка не может технически проверить, чья цель — есть только слово Миши.
Поэтому при входе в Kali (или перед первым сетевым инструментом) она один раз
спрашивает «всё что тестируем — твоё/авторизовано?», дальше сессия идёт молча.
Подтверждение + действия пишутся в аудит-лог ~/.troika/kali_audit.log — это
запись в защиту Миши (доказательство, что сеанс был санкционирован). Режим
«вообще без подтверждения по любой цели» СОЗНАТЕЛЬНО не делается.

Tools:
  • workspace_enter   — войти в рабочий стол (kali), переключить терминал
  • workspace_exit    — выйти, вернуть терминал на основное окружение
  • workspace_status  — где сейчас работает терминал
  • workspace_confirm — подтвердить авторизацию целей на текущую сессию
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_TROIKA = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".troika"))
_AUDIT_LOG = _TROIKA / "kali_audit.log"

# Конфиг рабочих столов. Образ и docker-аргументы задаются через env, чтобы
# деплой/сервер мог их переопределить без правки кода. Дефолты — разумные.
#   WORKSPACE_KALI_IMAGE        — образ (default troika-kali:latest)
#   WORKSPACE_KALI_EXTRA_ARGS   — JSON-массив доп. docker-аргументов
#                                 (напр. ["--cap-add","NET_RAW","--cap-add","NET_ADMIN"]
#                                  или ["--privileged"] для режима без лимитов)
#   WORKSPACE_KALI_VOLUME       — host-путь для тома /work (default ~/.troika/kali_work)
_DEF_KALI_IMAGE = os.environ.get("WORKSPACE_KALI_IMAGE", "troika-kali:latest")
_DEF_KALI_WORK = os.environ.get(
    "WORKSPACE_KALI_VOLUME", str(_TROIKA / "kali_work")
)


def _audit(event: str, detail: str = "") -> None:
    """Дописать строку в аудит-лог (best-effort, не ломаем работу при ошибке)."""
    try:
        from gateway.session_context import get_session_env
        sid = get_session_env("HERMES_SESSION_ID", "") or "-"
    except Exception:
        sid = "-"
    line = f"{datetime.now().isoformat(timespec='seconds')}\t{sid}\t{event}\t{detail}\n"
    try:
        _TROIKA.mkdir(parents=True, exist_ok=True)
        with open(_AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        logger.debug("kali audit write failed: %s", e)


def _sess():
    """Ленивая ссылка на session_context (может отсутствовать в CLI-тестах)."""
    from gateway import session_context
    return session_context


def _confirm_key() -> str:
    """Ключ session-override, под которым хранится подтверждение авторизации."""
    return "WORKSPACE_AUTHORIZED"


def _is_authorized() -> bool:
    try:
        return _sess().get_session_env(_confirm_key(), "") == "1"
    except Exception:
        # вне сессии (CLI) — считаем неавторизованным, чтобы гейт сработал
        return False


def _allowlisted(target: str) -> bool:
    """Цель в постоянном allowlist Миши (env KALI_TARGET_ALLOWLIST, через запятую)."""
    if not target:
        return False
    raw = os.environ.get("KALI_TARGET_ALLOWLIST", "")
    items = [x.strip().lower() for x in raw.replace(";", ",").split(",") if x.strip()]
    t = target.strip().lower()
    return any(t == it or t.endswith(it) or it in t for it in items)


# --- handlers ----------------------------------------------------------------

async def _handle_enter(args: Dict[str, Any], **_kw) -> Dict[str, Any]:
    name = (args.get("name") or "kali").strip().lower()
    if name != "kali":
        return {"ok": False, "error": "unknown_workspace",
                "say_to_user": f"Рабочий стол «{name}» не настроен. Есть только kali."}

    try:
        s = _sess()
    except Exception:
        return {"ok": False, "error": "no_session_context",
                "say_to_user": "Переключение рабочего стола доступно только через gateway, не в CLI."}

    # Собираем docker-аргументы окружения kali.
    extra_args = os.environ.get("WORKSPACE_KALI_EXTRA_ARGS", "").strip()
    volume = _DEF_KALI_WORK
    try:
        Path(volume).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.debug("could not create kali work dir: %s", e)

    # Переключаем терминал ТЕКУЩЕЙ сессии на docker+kali через session-overrides.
    s.set_session_override("TERMINAL_ENV", "docker")
    s.set_session_override("TERMINAL_DOCKER_IMAGE", _DEF_KALI_IMAGE)
    s.set_session_override("TERMINAL_DOCKER_VOLUMES",
                           f'["{volume}:/work"]')
    # Секреты Тройки НЕ пробрасываем: forward_env пуст.
    s.set_session_override("TERMINAL_DOCKER_FORWARD_ENV", "[]")
    if extra_args:
        s.set_session_override("TERMINAL_DOCKER_EXTRA_ARGS", extra_args)
    # tirith не мешает легитимным пентест-командам внутри стола.
    s.set_session_override("TIRITH_ENABLED", "0")

    _audit("enter", f"image={_DEF_KALI_IMAGE} extra={extra_args or '-'}")

    already = _is_authorized()
    msg = "Перешла в Kali. Рабочая папка /work."
    if not already:
        msg += (" Один раз уточню: всё, что тестируем в этот сеанс — твоё или "
                "у тебя есть авторизация? Скажи «да» — и дальше работаю молча.")
    else:
        msg += " Авторизация на эту сессию уже подтверждена."
    return {"ok": True, "workspace": "kali", "authorized": already,
            "image": _DEF_KALI_IMAGE, "say_to_user": msg}


async def _handle_exit(args: Dict[str, Any], **_kw) -> Dict[str, Any]:
    try:
        s = _sess()
    except Exception:
        return {"ok": True, "say_to_user": "Уже в обычном режиме."}
    for key in ("TERMINAL_ENV", "TERMINAL_DOCKER_IMAGE", "TERMINAL_DOCKER_VOLUMES",
                "TERMINAL_DOCKER_FORWARD_ENV", "TERMINAL_DOCKER_EXTRA_ARGS",
                "TIRITH_ENABLED"):
        s.clear_session_override(key)
    _audit("exit", "")
    return {"ok": True, "say_to_user": "Вышла из Kali. Снова в обычном режиме."}


async def _handle_status(args: Dict[str, Any], **_kw) -> Dict[str, Any]:
    try:
        s = _sess()
        env_type = s.get_session_env("TERMINAL_ENV", "local")
        image = s.get_session_env("TERMINAL_DOCKER_IMAGE", "")
    except Exception:
        env_type = os.environ.get("TERMINAL_ENV", "local")
        image = ""
    in_kali = env_type == "docker" and "kali" in (image or "").lower()
    if in_kali:
        say = (f"Я в Kali ({image}), "
               f"{'авторизация подтверждена' if _is_authorized() else 'жду подтверждения авторизации'}.")
    else:
        say = "Я в обычном режиме, не в Kali."
    return {"ok": True, "in_kali": in_kali, "env_type": env_type,
            "image": image, "authorized": _is_authorized(), "say_to_user": say}


async def _handle_confirm(args: Dict[str, Any], **_kw) -> Dict[str, Any]:
    """Подтвердить авторизацию целей на текущую сессию (раз-в-сессию гейт)."""
    try:
        s = _sess()
    except Exception:
        return {"ok": False, "error": "no_session_context",
                "say_to_user": "Подтверждение работает только через gateway."}
    note = (args.get("note") or "").strip()
    s.set_session_override(_confirm_key(), "1")
    _audit("authorize", note or "confirmed-by-user")
    return {"ok": True, "authorized": True,
            "say_to_user": "Принято. Авторизация на этот сеанс подтверждена — дальше работаю без вопросов."}


# --- schemas -----------------------------------------------------------------

ENTER_SCHEMA = {
    "name": "workspace_enter",
    "description": (
        "Войти в отдельный изолированный рабочий стол Тройки (Kali) — переключить "
        "СВОЙ терминал в Kali-контейнер для security/пентест-работы. Используй когда "
        "Миша говорит «перейди в кали», «открой свой рабочий стол», «зайди в кали». "
        "Инструменты Kali (nmap, sqlmap и т.д.) работают ТОЛЬКО после входа сюда. "
        "Переключение только для текущей сессии. После входа, если авторизация ещё "
        "не подтверждена — попроси Мишу подтвердить (workspace_confirm) перед сетевыми "
        "действиями по целям."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Имя рабочего стола. Сейчас только 'kali' (default)."},
        },
    },
}

EXIT_SCHEMA = {
    "name": "workspace_exit",
    "description": (
        "Выйти из рабочего стола Kali и вернуть терминал на обычное окружение Тройки. "
        "Используй когда Миша говорит «вернись», «выйди из кали», «всё, обратно»."
    ),
    "parameters": {"type": "object", "properties": {}},
}

STATUS_SCHEMA = {
    "name": "workspace_status",
    "description": "Где сейчас работает терминал Тройки — в Kali или в обычном режиме, и подтверждена ли авторизация.",
    "parameters": {"type": "object", "properties": {}},
}

CONFIRM_SCHEMA = {
    "name": "workspace_confirm",
    "description": (
        "Подтвердить авторизацию целей на текущую сессию. Вызывай ОДИН раз, когда "
        "Миша подтвердил что всё тестируемое — его/авторизовано (сказал «да, моё», "
        "«да, авторизовано», «подтверждаю»). После этого Тройка не переспрашивает "
        "до конца сессии. НЕ вызывай без явного подтверждения Миши."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "note": {"type": "string", "description": "Короткая заметка для аудит-лога (опц.), напр. 'моя точка доступа'."},
        },
    },
}


# --- registration ------------------------------------------------------------

from tools.registry import registry  # noqa: E402

registry.register(name="workspace_enter", toolset="security", schema=ENTER_SCHEMA,
                  handler=_handle_enter, is_async=True, emoji="🐉")
registry.register(name="workspace_exit", toolset="security", schema=EXIT_SCHEMA,
                  handler=_handle_exit, is_async=True, emoji="🚪")
registry.register(name="workspace_status", toolset="security", schema=STATUS_SCHEMA,
                  handler=_handle_status, is_async=True, emoji="📟")
registry.register(name="workspace_confirm", toolset="security", schema=CONFIRM_SCHEMA,
                  handler=_handle_confirm, is_async=True, emoji="✅")
