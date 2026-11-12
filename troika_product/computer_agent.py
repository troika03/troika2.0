"""Hermes bindings for opt-in Computer Use Runs."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import json

from troika_product.capabilities import ROUTER_TOOLSET
from troika_product.computer_control import ComputerControlError, MAX_GRANT_SECONDS
from troika_product.computer_windows_lab import ACTIONS as WINDOWS_ACTIONS, MAX_EDITOR_TEXT_UNITS, MODE as WINDOWS_MODE


TOOL = "troika_computer"
TOOLSET = ROUTER_TOOLSET
SCHEMA = {
    "name": TOOL,
    "description": (
        "Simulate an action on the consented test window. Inspect first, then pass "
        "the inspect receipt's action_id as inspect_action_id to click the preview button. "
        "Results are simulated and cannot verify an action on a real device."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["inspect", "click"]},
            "inspect_action_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}
WINDOWS_TOOL = "troika_windows_editor"
WINDOWS_SCHEMA = {
    "name": WINDOWS_TOOL,
    "description": (
        "Use the consented Windows test editor. Inspect to see which action is available. "
        "When inspect reports text_input=true, pass the exact requested single-line text to write. "
        "Legacy devices use the built-in test sentence. Inspect again before saving. "
        "For write and save, pass the preceding inspect receipt's action_id as inspect_action_id. "
        "A verified save means the editor read back the temporary test file."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(WINDOWS_ACTIONS)},
            "inspect_action_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
            "text": {"type": "string", "minLength": 1, "maxLength": MAX_EDITOR_TEXT_UNITS,
                     "description": "Only for write when text_input=true. Maximum 512 UTF-16 units."},
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}
_CURRENT = ContextVar("troika_computer_run", default=None)


class ComputerAgentRun:
    mode = "computer_dry_run"
    instruction = (
        "Выполни просьбу в тестовом окне. Все действия моделируются. "
        "Осмотри окно перед нажатием. Успех симуляции не подтверждает действие на устройстве."
    )

    def __init__(self, control, principal, run_id):
        self.control = control
        self.principal = principal
        self.run_id = run_id
        self.inspected = False
        self.clicked = False

    async def wait_for_consent(self):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + MAX_GRANT_SECONDS
        while True:
            status = self.control.model_grant_status(self.principal, self.run_id)
            if status == "active":
                return
            if status != "pending":
                raise ComputerControlError("grant_" + status)
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise ComputerControlError("grant_timeout")
            await asyncio.sleep(min(0.25, remaining))

    @contextmanager
    def bind(self):
        token = _CURRENT.set(self)
        try:
            yield
        finally:
            _CURRENT.reset(token)

    def act(self, args):
        if not isinstance(args, dict):
            raise ComputerControlError("invalid_tool_arguments", 400)
        action = args.get("action")
        valid_inspect = action == "inspect" and set(args) == {"action"}
        valid_click = action == "click" and set(args) == {"action", "inspect_action_id"}
        if not (valid_inspect or valid_click):
            raise ComputerControlError("invalid_tool_arguments", 400)
        receipt = self.control.model_action(self.principal, self.run_id, action, args.get("inspect_action_id"))
        result = {"ok": True, "receipt": receipt}
        if valid_inspect:
            self.inspected = True
            result["can_click_preview"] = True
        else:
            self.clicked = True
        return result

    def final_response(self):
        if self.clicked:
            return "Нажатие тестовой кнопки выполнено в симуляции."
        if self.inspected:
            return "Тестовое окно осмотрено. Нажатие в симуляции не подтверждено."
        return "Симуляция завершилась без подтверждённого действия."


class WindowsEditorAgentRun(ComputerAgentRun):
    mode = WINDOWS_MODE
    instruction = (
        "Доступен только тестовый редактор Windows. Осмотри его и следуй задаче пользователя. "
        "Если text_input=true, для ввода передай точный текст задачи в text. "
        "Сохранение требует нового осмотра и подтверждается проверкой файла на устройстве."
    )

    def __init__(self, control, principal, run_id):
        super().__init__(control, principal, run_id)
        self.wrote = False
        self.saved = False

    def act(self, args):
        if not isinstance(args, dict):
            raise ComputerControlError("invalid_tool_arguments", 400)
        action = args.get("action")
        fields = set(args)
        mutation = {"action", "inspect_action_id"}
        valid_inspect = action == "inspect" and fields == {"action"}
        valid_save = action == "save" and fields == mutation
        valid_write = action == "write" and (fields == mutation
                                             or fields == mutation | {"text"} and isinstance(args["text"], str))
        if not (valid_inspect or valid_save or valid_write):
            raise ComputerControlError("invalid_tool_arguments", 400)
        result = self.control.model_action(self.principal, self.run_id, action, args.get("inspect_action_id"),
                                           text=args.get("text"))
        status = result["receipt"]["status"]
        if status == "observed":
            self.inspected = True
        elif status == "applied":
            self.wrote = True
        elif status == "verified":
            self.saved = True
        return result

    def final_response(self):
        if self.saved:
            return "Windows сохранил тестовый файл и проверил его содержимое."
        if self.wrote:
            return "Текст введён. Сохранение файла не подтверждено."
        if self.inspected:
            return "Тестовый редактор осмотрен. Ввод не подтверждён."
        return "Windows не подтвердил действие в тестовом редакторе."


def available():
    return _CURRENT.get() is not None


available._hermes_skip_availability_cache = True


def available_for(mode):
    def check():
        return getattr(_CURRENT.get(), "mode", None) == mode
    check._hermes_skip_availability_cache = True
    return check


def execute(args, *, mode=ComputerAgentRun.mode, **_):
    scope = _CURRENT.get()
    if scope is None or scope.mode != mode:
        return json.dumps({"ok": False, "error": "computer_dry_run_required"})
    try:
        if isinstance(args, dict):
            # Hermes injects this field after tool argument parsing.
            args = {name: value for name, value in args.items() if name != "_session_id"}
        return json.dumps(scope.act(args))
    except ComputerControlError as exc:
        return json.dumps({"ok": False, "error": exc.code})
