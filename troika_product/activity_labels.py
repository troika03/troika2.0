"""Short user-facing descriptions of what the assistant is doing right now.

Product Run events never expose internal tool names, arguments or results.
This module maps a tool to one fixed Russian phrase so clients can show a
small "what is happening" line (like an agent status bar) without leaking
prompts, file contents, search queries or implementation details.
"""

from __future__ import annotations

from typing import Any

DEFAULT_LABEL = "Выполняю действие"

# Ordered: the first matching fragment wins. Fragments are matched against the
# lower-cased tool name only; arguments are used solely to unwrap the routed
# product tool and are never echoed.
_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("tool_search",), "Подбираю инструмент"),
    (("troika_context", "history", "session_search"), "Вспоминаю прошлые разговоры"),
    (("memory",), "Работаю с памятью"),
    (("web_extract", "fetch", "browser", "read_page", "crawl"), "Читаю страницу"),
    (("research", "search"), "Ищу в интернете"),
    (("pptx", "presentation", "slides"), "Готовлю презентацию"),
    (("xlsx", "spreadsheet", "csv", "table"), "Готовлю таблицу"),
    (("docx", "pdf", "document", "infographic"), "Готовлю документ"),
    (("image", "picture", "pollinations"), "Создаю изображение"),
    (("calendar",), "Проверяю календарь"),
    (("remind", "alarm", "timer"), "Ставлю напоминание"),
    (("assistant", "task", "note", "project", "diary"), "Обновляю дела и заметки"),
    (("weather",), "Смотрю погоду"),
    (("location", "navigate", "map"), "Смотрю карту"),
    (("translat",), "Перевожу"),
    (("vision", "screen", "camera", "photo"), "Смотрю на экран"),
    (("speech", "tts", "voice"), "Готовлю озвучку"),
    (("check", "run_tests", "verify", "review"), "Проверяю результат"),
    (("development", "code", "patch", "write_file", "project_zip"), "Пишу код"),
    (("android_", "phone_"), "Действую на телефоне"),
    (("pc_", "windows", "computer", "desktop"), "Действую на компьютере"),
    (("file", "workspace", "artifact"), "Работаю с файлами"),
)


def activity_label(tool_name: Any, args: Any = None) -> str:
    """Return a fixed, content-free phrase for a tool invocation."""
    name = tool_name if isinstance(tool_name, str) else ""
    try:
        from troika_product.capabilities import routed_call

        name, _ = routed_call(name, args)
    except Exception:
        pass
    value = name.casefold()
    if not value:
        return DEFAULT_LABEL
    for fragments, label in _RULES:
        if any(fragment in value for fragment in fragments):
            return label
    return DEFAULT_LABEL
