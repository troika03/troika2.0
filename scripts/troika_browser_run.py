"""Windows browser device client for the loopback Computer Use Run."""

import re
import time
from urllib.parse import urlsplit

import httpx

from troika_product.computer_control import ComputerControlError, MAX_ACTIONS, MAX_GRANT_SECONDS, VERSION
from troika_product.computer_windows_browser import COMMAND_SECONDS, MODE, browser_command


_ID = re.compile(r"[0-9a-f]{32}\Z")
_RUN = re.compile(r"run_[0-9a-f]{32}\Z")
_ENDED = {"grant_stopped", "grant_expired", "grant_revoked", "grant_not_found"}


def _view_for_report(view, share_headings):
    if view["page"] is None:
        return {"page": None, "open_pages": []}
    result = {key: view[key] for key in ("page", "open_pages", "y", "max_y")}
    result["headings"] = []
    if share_headings:
        for heading in view["headings"][:4]:
            clean = "".join(c for c in heading if ord(c) >= 32 and not 127 <= ord(c) < 160
                            and not 0xD800 <= ord(c) <= 0xDFFF).strip()
            if clean:
                result["headings"].append(clean[:128])
    return result


class BrowserRunClient:
    def __init__(self, address, run_id, grant_id, token):
        url = urlsplit(address)
        if (url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port
                or url.netloc != f"127.0.0.1:{url.port}" or url.path not in ("", "/")
                or url.query or url.fragment or not _RUN.fullmatch(run_id) or not _ID.fullmatch(grant_id)):
            raise ValueError("укажите локальный адрес, Run и разрешение")
        if not isinstance(token, str) or not token or not token.isascii() or any(
            c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token
        ):
            raise ValueError("укажите токен выбранного ПК в TROIKA_COMPUTER_TEST_DEVICE_TOKEN")
        self.endpoint = f"http://{url.netloc}/v1/runs/{run_id}/computer-windows-browser/"
        self.grant_id = grant_id
        self._needs_stop = False
        self.http = httpx.Client(headers={"Authorization": "Bearer " + token}, timeout=3,
                                 follow_redirects=False, trust_env=False)

    def close(self):
        try:
            self._stop()
        finally:
            self.http.close()

    def _stop(self):
        if not self._needs_stop:
            return
        try:
            self._send("stop")
        except httpx.HTTPError:
            return
        except ComputerControlError:
            pass
        self._needs_stop = False

    def _send(self, operation, **body):
        response = self.http.post(self.endpoint + operation, json={"version": VERSION, "grant_id": self.grant_id, **body})
        try:
            payload = response.json()
        except ValueError:
            raise ComputerControlError("invalid_browser_run_response") from None
        if not isinstance(payload, dict):
            raise ComputerControlError("invalid_browser_run_response")
        if not response.is_success:
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            raise ComputerControlError(code if isinstance(code, str) and code in _ENDED else "browser_run_rejected")
        if type(payload.get("version")) is not int or payload["version"] != VERSION or payload.get("mode") != MODE:
            raise ComputerControlError("invalid_browser_run_response")
        return payload

    def review(self):
        status = self._send("review")
        if status.get("grant_id") != self.grant_id:
            raise ComputerControlError("invalid_browser_run_response")
        if status.get("status") == "pending":
            self._needs_stop = True
        return status.get("status")

    def deny(self, permission, pages, share_headings):
        self._send("consent", allow=False, permission=permission, pages=list(pages), share_headings=share_headings)
        self._needs_stop = False

    def run(self, lab, approve, permission, share_headings, deadline):
        pages = list(lab.targets)
        self._needs_stop = True
        try:
            began = time.monotonic()
            consent = self._send("consent", allow=True, permission=permission, pages=pages, share_headings=share_headings)
            seconds = consent.get("expires_in_seconds")
            if (consent.get("grant_id") != self.grant_id or consent.get("status") != "active"
                    or consent.get("permission") != permission or consent.get("pages") != pages
                    or consent.get("share_headings") is not share_headings
                    or type(seconds) not in (int, float) or not 0 < seconds <= MAX_GRANT_SECONDS):
                raise ComputerControlError("invalid_browser_run_response")
            deadline = min(deadline, began + seconds)
            if permission == "view" and time.monotonic() < deadline:
                lab.step({"action": "open", "page": "overview"}, lambda _: time.monotonic() < deadline)
            return self._poll(lab, approve, permission, share_headings, deadline)
        finally:
            self._stop()

    def _poll(self, lab, approve, permission, share_headings, deadline):
        previous_id, previous_view = None, None
        sequence = 0
        receipts = []
        while time.monotonic() < deadline:
            requested = time.monotonic()
            try:
                response = self._send("take")
            except ComputerControlError as error:
                if error.code in _ENDED:
                    return receipts
                raise
            if "command" not in response:
                raise ComputerControlError("invalid_browser_run_response")
            command = response["command"]
            if command is None:
                time.sleep(0.15)
                continue
            sequence += 1
            args, expires = self._command(command, sequence, lab.targets, requested, deadline)
            status, result = self._perform(lab, command, args, approve, permission, expires, previous_id, previous_view)
            body = {"command_id": command["id"], "status": status}
            if status in ("verified", "observed"):
                previous_id, previous_view = command["id"], result["view"]
                body["view"] = _view_for_report(previous_view, share_headings)
                receipts.append(result)
            else:
                previous_id, previous_view = None, None
                receipts.append({"action": args["action"], "error": status})
            if time.monotonic() >= expires:
                raise ComputerControlError("command_expired")
            if self._send("report", **body).get("accepted") is not True:
                raise ComputerControlError("invalid_browser_run_response")
        raise ComputerControlError("grant_expired")

    @staticmethod
    def _command(command, sequence, pages, requested, deadline):
        if not isinstance(command, dict):
            raise ComputerControlError("invalid_browser_command")
        action = command.get("action")
        fields = {"id", "sequence", "action", "arguments", "expires_in_ms"}
        if action != "inspect":
            fields.add("inspect_action_id")
        if (set(command) != fields or not isinstance(command["id"], str) or not _ID.fullmatch(command["id"])
                or type(command["sequence"]) is not int or command["sequence"] != sequence or sequence > MAX_ACTIONS
                or type(command["expires_in_ms"]) is not int or not 1 <= command["expires_in_ms"] <= COMMAND_SECONDS * 1000
                or not isinstance(command["arguments"], dict) or "action" in command["arguments"]):
            raise ComputerControlError("invalid_browser_command")
        args = {"action": action, **command["arguments"]}
        browser_command(args, pages)
        return args, min(deadline, requested + command["expires_in_ms"] / 1000)

    def _perform(self, lab, command, args, approve, permission, expires, previous_id, previous_view):
        writing = args["action"] != "inspect"
        if time.monotonic() >= expires:
            return "stale_state", None
        if writing:
            if permission == "view":
                return "denied", None
            if previous_id is None or command["inspect_action_id"] != previous_id or lab.inspect() != previous_view:
                return "stale_state", None
            if not approve(args):
                return "denied", None
            if time.monotonic() >= expires or self.review() != "active" or lab.inspect() != previous_view:
                return "stale_state", None
        result = lab.step(args, lambda _: time.monotonic() < expires)
        if "error" in result or result.get("at_boundary"):
            return "stale_state", None
        return ("verified" if writing else "observed"), result
