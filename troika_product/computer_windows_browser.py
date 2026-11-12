"""Device-scoped browser commands for an opt-in Windows conversation Run."""

from dataclasses import dataclass
from uuid import uuid4

from troika_product.computer_control import ComputerControlError, MAX_ACTIONS, VERSION, _Grant, _fields
from troika_product.computer_windows_lab import WindowsDeviceCommands, _Command


MODE = "windows_browser_lab"
TOOL = "troika_windows_browser"
PAGES = ("overview", "details")
PERMISSIONS = ("ask", "run", "view")
COMMAND_SECONDS = 30


def browser_schema(pages=PAGES):
    return {
        "name": TOOL,
        "description": (
            "Operate only the selected browser pages. Inspect first. Receipts contain the selected page, "
            "its scroll position and shared headings. For open or switch, send exactly action and page. "
            "Open creates a separate window. Switch selects an already open page. "
            "For scroll, send exactly action and direction. For inspect, send only action."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"enum": ["open", "inspect", "scroll", "switch"], "type": "string"},
                "page": {"enum": list(pages), "type": "string", "description": "Only for open or switch."},
                "direction": {"enum": ["up", "down"], "type": "string", "description": "Only for scroll."},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    }


def browser_command(args, pages):
    if not isinstance(args, dict):
        raise ComputerControlError("invalid_tool_arguments", 400)
    action = args.get("action")
    name = args.get("page")
    if action == "inspect" and set(args) == {"action"}:
        return action, {}
    if (action in ("open", "switch") and set(args) == {"action", "page"}
            and isinstance(name, str) and name in pages):
        return action, {"page": name}
    if action == "scroll" and set(args) == {"action", "direction"} and args["direction"] in ("up", "down"):
        return action, {"direction": args["direction"]}
    raise ComputerControlError("invalid_tool_arguments", 400)


@dataclass
class _BrowserGrant(_Grant):
    mode = MODE
    allowed_actions = ("inspect", "open", "scroll", "switch")
    command: _Command | None = None
    issued: int = 0
    permission: str = "ask"
    pages: tuple = ()
    share_headings: bool = False
    denied: bool = False
    view: dict | None = None
    view_id: str | None = None
    view_expires: float = 0

    def summary(self, now):
        return {**super().summary(now), "app": "browser"}

    def close(self, status):
        super().close(status)
        self.view = None
        self.view_id = None
        if self.command is not None:
            self.command.done.set()
            self.command = None


def _validate_view(value, grant):
    if not isinstance(value, dict):
        raise ComputerControlError("invalid_browser_view", 400)
    if value == {"page": None, "open_pages": []}:
        return value
    if set(value) != {"page", "open_pages", "y", "max_y", "headings"}:
        raise ComputerControlError("invalid_browser_view", 400)
    pages, headings = value["open_pages"], value["headings"]
    if (not isinstance(pages, list) or not 1 <= len(pages) <= len(grant.pages)
            or any(not isinstance(page, str) or page not in grant.pages for page in pages)
            or len(set(pages)) != len(pages) or value["page"] not in pages
            or type(value["y"]) is not int or type(value["max_y"]) is not int
            or not 0 <= value["y"] <= value["max_y"] <= 100_000_000
            or not isinstance(headings, list) or len(headings) > 4 or (headings and not grant.share_headings)
            or any(not isinstance(text, str) or not 1 <= len(text) <= 128
                   or any(ord(c) < 32 or 127 <= ord(c) < 160 or 0xD800 <= ord(c) <= 0xDFFF
                          for c in text) for text in headings)):
        raise ComputerControlError("invalid_browser_view", 400)
    return value


def _matches_action(command, before, after):
    if command.action == "inspect":
        return True
    if command.action == "open":
        page = command.arguments["page"]
        return (page not in before["open_pages"] and after["page"] == page
                and after["open_pages"] == [*before["open_pages"], page])
    if after["open_pages"] != before["open_pages"]:
        return False
    if command.action == "switch":
        return before["page"] != after["page"] == command.arguments["page"]
    return (before["page"] is not None and after["page"] == before["page"]
            and (after["y"] > before["y"] if command.arguments["direction"] == "down" else after["y"] < before["y"]))


class WindowsBrowserLab(WindowsDeviceCommands):
    grant_type = _BrowserGrant

    def __init__(self, registry, run_owner, *, openrouter, **options):
        super().__init__(registry, run_owner, **options)
        self.openrouter = openrouter

    @staticmethod
    def _consent(principal, grant, body, now):
        _fields(body, "grant_id", "allow", "permission", "pages", "share_headings")
        permission, pages, share = body["permission"], body["pages"], body["share_headings"]
        if permission not in PERMISSIONS or pages not in (["overview"], list(PAGES)) or type(share) is not bool:
            raise ComputerControlError("invalid_request", 400)
        response = WindowsDeviceCommands._consent(principal, grant, {
            "version": VERSION, "grant_id": body["grant_id"], "allow": body["allow"],
        }, now)
        grant.permission, grant.pages, grant.share_headings = permission, tuple(pages), share
        return {**response, "permission": permission, "pages": pages, "share_headings": share}

    def _active_grant(self, principal, run_id):
        grant = self._grants.get(run_id)
        if grant is None or grant.requester != principal:
            raise ComputerControlError("grant_not_found", 404)
        now = self._check_live(run_id, grant)
        if grant.status != "active":
            raise ComputerControlError("grant_" + grant.status)
        return grant, now

    def action_time(self, principal, run_id):
        with self._lock:
            grant, now = self._active_grant(principal, run_id)
            return grant.expires_at - now

    def model_action(self, principal, run_id, args):
        with self._lock:
            grant, now = self._active_grant(principal, run_id)
            action, arguments = browser_command(args, grant.pages)
            if grant.command is not None:
                raise ComputerControlError("command_busy")
            if grant.issued >= MAX_ACTIONS:
                raise ComputerControlError("action_limit")
            expiry = min(grant.expires_at, now + COMMAND_SECONDS)
            view_id = None
            if action != "inspect":
                if grant.permission == "view" or grant.denied:
                    raise ComputerControlError("action_denied")
                if grant.view is None or now >= grant.view_expires:
                    raise ComputerControlError("stale_state")
                view_id = grant.view_id
                expiry = min(expiry, grant.view_expires)
            grant.issued += 1
            command = _Command(uuid4().hex, grant.issued, action, expiry, view_id, arguments=arguments)
            grant.command = command
        return self._await_report(grant, command)

    def _report(self, grant, body, now):
        command = grant.command
        if (command is None or not command.taken or command.result is not None
                or command.id != body.get("command_id") or now >= command.expires_at):
            raise ComputerControlError("command_unavailable")
        status = body.get("status")
        fields = ("grant_id", "command_id", "status")
        success = status == ("observed" if command.action == "inspect" else "verified")
        if success:
            _fields(body, *fields, "view")
            view = _validate_view(body["view"], grant)
            if not _matches_action(command, grant.view, view):
                raise ComputerControlError("browser_action_unverified", 400)
            grant.view = {key: value for key, value in view.items() if key != "headings"}
            grant.view_id = command.id
            grant.view_expires = min(grant.expires_at, now + COMMAND_SECONDS)
            command.result = {"ok": True, "status": status, "action": command.action,
                              "view": view, "allowed_pages": list(grant.pages), "permission": grant.permission}
        else:
            _fields(body, *fields)
            if status not in ("failed", "stale_state", "denied") or (status == "denied" and command.action == "inspect"):
                raise ComputerControlError("invalid_report", 400)
            grant.denied = grant.denied or status == "denied"
            grant.view = None
            grant.view_id = None
            command.result = {"ok": False, "error": status}
        command.done.set()
        return {"version": VERSION, "mode": MODE, "accepted": True}
