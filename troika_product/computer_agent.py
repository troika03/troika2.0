"""Hermes binding for a single opt-in synthetic Computer Use Run."""

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import json

from troika_product.capabilities import ROUTER_TOOLSET
from troika_product.computer_control import ComputerControlError, MAX_GRANT_SECONDS


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
_CURRENT = ContextVar("troika_computer_dry_run", default=None)


class ComputerAgentRun:
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


def available():
    return _CURRENT.get() is not None


available._hermes_skip_availability_cache = True


def execute(args, **_):
    scope = _CURRENT.get()
    if scope is None:
        return json.dumps({"ok": False, "error": "computer_dry_run_required"})
    try:
        if isinstance(args, dict):
            # Hermes injects this field after tool argument parsing.
            args = {name: value for name, value in args.items() if name != "_session_id"}
        return json.dumps(scope.act(args))
    except ComputerControlError as exc:
        return json.dumps({"ok": False, "error": exc.code})
