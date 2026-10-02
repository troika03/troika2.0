"""Check product completion claims against receipts from the current turn.

This is a deterministic backstop, not a semantic verifier for arbitrary prose.
Only structured tool receipts count; model narration and previous turns never do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import shlex
from typing import Any


_DONE = re.compile(r"\b(?:готово|сделано|выполнено|всё сделала|все сделала|done|completed)\b", re.I)
_VERBS = {
    "create": r"создал[аи]?|создан[аоы]?|добавил[аи]?|добавлен[аоы]?|сохранил[аи]?|сохран[её]н[аоы]?|записал[аи]?|записан[аоы]?|подготовил[аи]?|подготовлен[аоы]?|готов[аоы]?|created|saved|added",
    "update": r"изменил[аи]?|измен[её]н[аоы]?|обновил[аи]?|обновл[её]н[аоы]?|исправил[аи]?|исправлен[аоы]?|updated|changed|fixed",
    "delete": r"удалил[аи]?|удал[её]н[аоы]?|deleted|removed",
    "open": r"открыл[аи]?|открыт[аоы]?|запустил[аи]?|запущен[аоы]?|opened|launched",
    "send": r"отправил[аи]?|отправлен[аоы]?|опубликовал[аи]?|опубликован[аоы]?|sent|published",
    "set": r"установил[аи]?|установлен[аоы]?|включил[аи]?|включ[её]н[аоы]?|выключил[аи]?|выключен[аоы]?|поставил[аи]?|поставлен[аоы]?|настроил[аи]?|настроен[аоы]?|выставил[аи]?|выставлен[аоы]?",
    "remember": r"запомнил[аи]?|remembered",
    "remind": r"напомню|буду напоминать",
    "read": r"прочитал[аи]?|изучил[аи]?|проверил[аи]?|посмотрел[аи]?|просмотрел[аи]?|checked|reviewed",
}
_CLAIMS = {key: re.compile(r"\b(?:" + value + r")\b", re.I) for key, value in _VERBS.items()}
_DOMAINS = {
    "file": re.compile(r"файл|документ|презентац|отч[её]т|папк|\.docx|\.pdf|\.pptx|\.txt|document|file|folder", re.I),
    "reminder": re.compile(r"напомин|будильник|таймер|remind|alarm|timer", re.I),
    "task": re.compile(r"задач|task", re.I),
    "memory": re.compile(r"памят|запом|memory|remember", re.I),
    "note": re.compile(r"заметк|note", re.I),
    "project": re.compile(r"проект|project", re.I),
    "message": re.compile(r"сообщени|письм|sms|message|email", re.I),
    "device": re.compile(r"приложени|телефон|громкост|яркост|фонарик|device|app", re.I),
    "information": re.compile(r"сайт|страниц|интернет|результат.{0,20}поиск|website|search results", re.I),
}
_ACTION_REQUEST = re.compile(
    r"(?:созда|сдела|сохран|добав|удал|измени|обнови|исправ).{0,100}"
    r"(?:файл|документ|презентац|папк|задач|напомин|заметк|проект)|"
    r"\b(?:напомни|запомни|открой|отправь|включи|выключи|установи|поставь)\b|"
    r"\b(?:create|save|delete|send|open|set|remember)\b",
    re.I | re.S,
)
_PENDING = {"pending", "queued", "accepted", "running", "waiting_for_approval", "cancelled", "failed", "error"}
_ASSISTANT_ACTIONS = {
    "project_create": ("project", "create"), "project_activate": ("project", "set"),
    "note_add": ("note", "create"), "task_add": ("task", "create"),
    "task_update": ("task", "update"), "memory_add": ("memory", "remember"),
    "memory_update": ("memory", "update"), "memory_delete": ("memory", "delete"),
    "reminder_schedule": ("reminder", "set"), "follow_up_schedule": ("reminder", "set"),
}
_PHONE_ACTIONS = {
    "open_app": ("device", "open"), "navigate": ("device", "open"),
    "web_search": ("browser", "open"), "set_alarm": ("reminder", "set"),
    "set_timer": ("reminder", "set"), "send_sms": ("message", "send"),
    "call": ("device", "set"), "volume": ("device", "set"),
    "brightness": ("device", "set"), "torch": ("device", "set"),
    "clipboard_set": ("device", "set"), "file_write": ("file", "create"),
    "file_delete": ("file", "delete"), "file_move": ("file", "update"),
    "calendar_create_event": ("calendar", "create"),
    "calendar_update_event": ("calendar", "update"),
    "calendar_delete_event": ("calendar", "delete"),
}


def _object(value: Any) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def _successful(payload: dict, *, check_nested_status: bool = True) -> bool:
    if payload.get("ok") is not True and payload.get("success") is not True:
        return False
    if payload.get("error") or payload.get("ok") is False or payload.get("success") is False:
        return False
    if str(payload.get("status", "")).lower() in _PENDING:
        return False
    nested = payload.get("result")
    if isinstance(nested, dict):
        if nested.get("error") or nested.get("ok") is False or nested.get("success") is False:
            return False
        if check_nested_status and str(nested.get("status", "")).lower() in _PENDING:
            return False
    return True


@dataclass
class CompletionEvidence:
    """A request-local ledger populated only after actual tool execution."""

    receipts: dict[str, tuple[str, str, bool]] = field(default_factory=dict)
    disabled_reminders: bool = False
    filenames: set[str] = field(default_factory=set)
    phone_file_saved: bool = False

    def record(self, name: str, args: Any, raw_result: Any) -> None:
        args, payload = _object(args), _object(raw_result)
        action = str(args.get("action") or "")
        domain, operation = "", ""
        proved = _successful(payload, check_nested_status=name != "troika_assistant")
        if name.startswith("troika_create_"):
            domain, operation = "file", "create"
            artifact = _object(payload.get("artifact"))
            proved = proved and bool(artifact.get("id") and artifact.get("filename"))
            if proved:
                self.filenames.add(str(artifact["filename"]).casefold())
        elif name == "troika_assistant":
            domain, operation = _ASSISTANT_ACTIONS.get(action, ("", ""))
            result = _object(payload.get("result"))
            proved = proved and payload.get("action") == action and bool(
                result.get("id") or result.get("message_id") or result.get("memory_id")
            )
            if domain == "reminder" and result.get("delivery_enabled") is False:
                self.disabled_reminders = True
                proved = False
        elif name == "troika_files":
            domain = "file"
            operation = {"write": "create", "mkdir": "create", "copy": "create",
                         "replace": "update", "move": "update", "delete": "delete",
                         "read": "read", "stat": "read", "list": "read"}.get(action, "")
            if proved and operation in {"create", "update"}:
                path = str(_object(payload.get("entry")).get("path") or args.get("destination") or args.get("path") or "")
                self.filenames.add(path.replace("\\", "/").rsplit("/", 1)[-1].casefold())
        elif name == "troika_terminal":
            try:
                tokens = shlex.split(str(args.get("command") or ""))
            except ValueError:
                tokens = []
            action = tokens[0] if tokens else ""
            domain, operation = "file", {
                "touch": "create", "mkdir": "create", "cp": "create", "mv": "update", "rm": "delete",
                "cat": "read", "head": "read", "tail": "read", "ls": "read", "wc": "read",
            }.get(action, "")
            proved = proved and payload.get("command") == action
            if proved and operation in {"create", "update"}:
                self.filenames.add(str(payload.get("output") or "").replace("\\", "/").rsplit("/", 1)[-1].casefold())
        elif name.startswith("android_"):
            domain, operation = _PHONE_ACTIONS.get(name[8:], ("", ""))
            if name == "android_file_write" and proved:
                self.phone_file_saved = True
                self.filenames.add(str(args.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1].casefold())
            if not operation and name[8:] in {"read_screen", "file_read", "file_info", "status", "battery", "network"}:
                domain, operation = "device", "read"
        elif name in {"web_search", "web_extract", "troika_file_search", "troika_screen_snapshot"}:
            domain, operation = "information", "read"
            if name == "web_extract":
                results = payload.get("results")
                proved = bool(isinstance(results, list) and results) and all(
                    isinstance(item, dict) and item.get("content") and not item.get("error")
                    for item in results or []
                ) and not payload.get("error")
        if not operation:
            return  # Read-only/unknown tools cannot prove a mutation.
        target = str(args.get("command") or args.get("path") or args.get("task_id") or args.get("memory_id")
                     or args.get("idempotency_key") or args.get("title") or args.get("name") or "")
        # A successful retry supersedes a failure only for the same operation
        # and target. A different successful action never erases that failure.
        key = json.dumps([name, action, target], ensure_ascii=False)
        self.receipts[key] = (domain, operation, bool(proved))

    def unsupported(self, text: str, user_message: Any = "") -> bool:
        successes = [(domain, operation) for domain, operation, ok in self.receipts.values() if ok]
        failures = any(not ok for _, _, ok in self.receipts.values())
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", re.sub(r"```.*?```", "", text, flags=re.S)):
            # Negation and conditional/instructional wording are not claims.
            clean = re.sub(r"[«\"].*?[»\"]", "", sentence)
            clean = re.sub(r"\b(?:не|not|never)\s+(?:\w+\s+){0,2}(?:" + "|".join(_VERBS.values()) + r")\b", "", clean, flags=re.I)
            if re.search(r"\b(?:если|когда|чтобы|if|when)\b", clean, re.I):
                continue
            operations = [op for op, pattern in _CLAIMS.items() if pattern.search(clean)]
            if not operations:
                continue
            domains = [domain for domain, pattern in _DOMAINS.items() if pattern.search(clean)]
            # Writing an answer/poem in chat and checking supplied text require
            # no external tool. Short "сохранила" after an action request does.
            if not domains and not self.receipts and not _ACTION_REQUEST.search(str(user_message)):
                continue
            if failures and re.search(r"\b(?:все|всё|оба|обе|all|both)\b", clean, re.I):
                return True
            if "file" in domains and any(op in {"create", "update"} for op in operations):
                if re.search(r"(?:на|в)\s+(?:компьютер|ПК|рабочий стол)", clean, re.I):
                    return True
                if re.search(r"(?:на|в)\s+телефон", clean, re.I) and not self.phone_file_saved:
                    return True
                for filename in re.findall(r"[\w-]+\.(?:docx|pdf|pptx|txt|csv|xlsx)\b", clean, re.I):
                    if filename.casefold() not in self.filenames:
                        return True
            for operation in operations:
                compatible = {operation}
                if operation == "create":
                    compatible |= {"remember", "set"}  # Saved memory/reminder.
                if operation == "set" and "reminder" in domains:
                    compatible.add("create")
                if operation == "remind":
                    compatible = {"set"}
                if not any(op in compatible and (not domains or domain in domains)
                           for domain, op in successes):
                    return True
            for requested in domains:
                if not any(domain == requested for domain, _ in successes):
                    return True
        if _DONE.search(text) and (self.receipts or _ACTION_REQUEST.search(str(user_message))):
            mutations = [op for _, op in successes if op != "read"]
            if failures or not mutations:
                return True
        return False

    def may_retry(self) -> bool:
        """Only retry missing actions, never replay a mutation or a denial."""
        return all(operation == "read" for _, operation, _ in self.receipts.values())

    def fallback(self) -> str:
        successful_actions = any(ok and operation != "read" for _, operation, ok in self.receipts.values())
        if self.disabled_reminders:
            return "Напоминание сохранено, но доставка отключена. Включи напоминания в настройках, чтобы получать их."
        if successful_actions:
            return "Часть действий выполнена, но подтвердить выполнение всей просьбы не удалось. Не буду говорить, что всё готово."
        return "Не удалось подтвердить выполнение просьбы. Действие не считаю выполненным."


COMPLETION_RETRY_INSTRUCTION = (
    "Твой ответ утверждает выполнение без подтверждающего результата текущего запроса. "
    "Проверь результаты уже вызванных действий. Не повторяй успешно выполненные действия. "
    "Если действие ещё не выполнялось, используй доступный инструмент с обычными правилами подтверждения. "
    "Если инструмент отсутствует, отказал, завершился ошибкой или только принял команду, "
    "честно сообщи это. Не говори «готово», пока нужный результат не подтверждён."
)
