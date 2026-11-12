"""Single-delivery commands for the opt-in local Windows scratchpad."""

from dataclasses import dataclass, field
import threading
from uuid import uuid4

from troika_product.computer_control import (
    ComputerControlError,
    ComputerGrantControl,
    MAX_ACTIONS,
    MAX_OBSERVATION_SECONDS,
    VERSION,
    _Grant,
    _fields,
    _id,
)

MODE = "windows_lab"
ACTIONS = ("inspect", "write", "save")
_COMMAND_SECONDS = 10
MAX_EDITOR_TEXT_UNITS = 512


def _valid_editor_text(text):
    if not isinstance(text, str) or not text or len(text) > MAX_EDITOR_TEXT_UNITS:
        return False
    if any(ord(character) < 32 or 127 <= ord(character) < 160
           or character in "\u2028\u2029" for character in text):
        return False
    try:
        return len(text.encode("utf-16-le")) <= MAX_EDITOR_TEXT_UNITS * 2
    except UnicodeEncodeError:
        return False


@dataclass(frozen=True)
class _EditorView:
    inspect_id: str
    expires_at: float
    can_write: bool
    can_save: bool


@dataclass
class _Command:
    id: str
    sequence: int
    action: str
    expires_at: float
    inspect_id: str | None = None
    text: str | None = field(default=None, repr=False)
    taken: bool = False
    result: dict | None = None
    done: threading.Event = field(default_factory=threading.Event)


@dataclass
class _WindowsGrant(_Grant):
    mode = MODE
    allowed_actions = ACTIONS
    command: _Command | None = None
    view: _EditorView | None = None
    issued: int = 0
    wrote: bool = False
    saved: bool = False
    text_input: bool = False

    def close(self, status):
        super().close(status)
        self.view = None
        if self.command is not None:
            self.command.text = None
            self.command.done.set()
            self.command = None


class WindowsComputerLab(ComputerGrantControl):
    grant_type = _WindowsGrant
    platforms = frozenset({"windows"})
    allow_regrant = False

    @staticmethod
    def _consent(principal, grant, body, now):
        options = dict(body)
        text_input = options.pop("text_input", False)
        if type(text_input) is not bool:
            raise ComputerControlError("invalid_request", 400)
        response = ComputerGrantControl._consent(principal, grant, options, now)
        grant.text_input = grant.status == "active" and text_input
        return {**response, "text_input": grant.text_input}

    def model_action(self, principal, run_id, action, inspect_id=None, *, text=None):
        if action not in ACTIONS:
            raise ComputerControlError("unsupported_action", 400)
        if action != "write" and text is not None:
            raise ComputerControlError("invalid_tool_arguments", 400)
        with self._lock:
            grant = self._grants.get(run_id)
            if grant is None or grant.requester != principal:
                raise ComputerControlError("grant_not_found", 404)
            now = self._check_live(run_id, grant)
            if grant.status != "active":
                raise ComputerControlError("grant_" + grant.status)
            if grant.command is not None:
                raise ComputerControlError("command_busy")
            if grant.issued >= MAX_ACTIONS or grant.saved:
                raise ComputerControlError("action_limit")
            if action == "write":
                if grant.text_input and not _valid_editor_text(text):
                    raise ComputerControlError("invalid_text", 400)
                if not grant.text_input and text is not None:
                    raise ComputerControlError("text_input_unavailable")
            expires = min(grant.expires_at, now + _COMMAND_SECONDS)
            if action != "inspect":
                view = grant.view
                if view is None or not _id(inspect_id) or view.inspect_id != inspect_id or now >= view.expires_at:
                    raise ComputerControlError("stale_state")
                if not (view.can_write if action == "write" else view.can_save):
                    raise ComputerControlError("action_unavailable")
                expires = min(expires, view.expires_at)
            grant.view = None
            grant.issued += 1
            command = _Command(uuid4().hex, grant.issued, action, expires, inspect_id, text=text)
            grant.command = command

        command.done.wait(max(0, expires - self._clock()))
        with self._lock:
            if command.result is not None:
                if grant.command is command:
                    grant.command = None
                return command.result
            if grant.status != "active":
                raise ComputerControlError("grant_" + grant.status)
            grant.close("stopped")
            raise ComputerControlError("command_timed_out")

    def _operate(self, grant, operation, body, now, *, requester, target):
        if not target:
            raise ComputerControlError("grant_not_found", 404)
        if grant.status != "active":
            raise ComputerControlError("grant_" + grant.status)
        if operation == "take":
            _fields(body, "grant_id")
            return self._take(grant, now)
        if operation == "report":
            return self._report(grant, body, now)
        raise ComputerControlError("grant_not_found", 404)

    @staticmethod
    def _take(grant, now):
        payload = {"version": VERSION, "mode": MODE, "command": None}
        command = grant.command
        if command is None or command.taken or command.expires_at <= now:
            return payload
        duration_ms = int((command.expires_at - now) * 1000)
        if duration_ms <= 0:
            return payload
        command.taken = True
        payload["command"] = {"id": command.id, "sequence": command.sequence, "action": command.action,
                              "expires_in_ms": duration_ms}
        if command.inspect_id is not None:
            payload["command"]["inspect_action_id"] = command.inspect_id
        if command.text is not None:
            payload["command"]["text"] = command.text
            command.text = None
        return payload

    @staticmethod
    def _report(grant, body, now):
        command = grant.command
        if (command is None or not command.taken or command.result is not None
                or command.id != body.get("command_id") or command.expires_at <= now):
            raise ComputerControlError("command_unavailable")
        status = body.get("status")
        fields = ("grant_id", "command_id", "status")
        if command.action == "inspect" and status == "observed":
            _fields(body, *fields, "can_write", "can_save")
            can_write, can_save = body["can_write"], body["can_save"]
            if (type(can_write) is not bool or type(can_save) is not bool
                    or (can_write and grant.wrote) or (can_save and not grant.wrote)):
                raise ComputerControlError("invalid_report", 400)
            grant.view = _EditorView(command.id, min(grant.expires_at, now + MAX_OBSERVATION_SECONDS),
                                     can_write, can_save)
        else:
            _fields(body, *fields)
            expected = {"inspect": "observed", "write": "applied", "save": "verified"}[command.action]
            if status not in (expected, "stale_state", "failed"):
                raise ComputerControlError("invalid_report", 400)
            if status == "applied":
                grant.wrote = True
            if status == "verified":
                grant.saved = True
        receipt = {"version": VERSION, "mode": MODE, "action_id": command.id, "sequence": command.sequence,
                   "action": command.action, "status": status, "verified": status == "verified"}
        command.result = {"ok": status in ("observed", "applied", "verified"), "receipt": receipt}
        if status == "observed":
            command.result.update(can_write=grant.view.can_write, can_save=grant.view.can_save,
                                  text_input=grant.text_input)
        if not command.result["ok"]:
            command.result["error"] = status
        command.done.set()
        return {"version": VERSION, "mode": MODE, "accepted": True}
