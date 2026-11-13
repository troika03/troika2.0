"""Windows browser device client for the loopback Computer Use Run."""

import re
import time
from urllib.parse import urlsplit

import httpx

from troika_product.computer_control import ComputerControlError, MAX_ACTIONS, MAX_GRANT_SECONDS, VERSION
from troika_product.computer_windows_browser import COMMAND_SECONDS, MODE, device_command


_ID = re.compile(r"[0-9a-f]{32}\Z")
_RUN = re.compile(r"run_[0-9a-f]{32}\Z")
_ENDED = {"grant_stopped", "grant_expired", "grant_revoked", "grant_not_found"}


def _view_for_report(view, share_headings, share_links=False):
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
    if share_headings and share_links and "links" in view:
        result.update(fragment=view["fragment"], at_section=view["at_section"],
                      links=[{key: link[key] for key in ("id", "label", "fragment")} for link in view["links"]])
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

    def run(self, lab, approve, permission, share_headings, deadline, *, progress=None):
        pages = list(lab.targets)
        apps = list(getattr(lab, "apps", ("browser",)))
        self._needs_stop = True
        try:
            began = time.monotonic()
            scope = {"apps": apps} if apps != ["browser"] else {}
            consent = self._send("consent", allow=True, permission=permission, pages=pages,
                                 share_headings=share_headings, **scope)
            seconds = consent.get("expires_in_seconds")
            if (consent.get("grant_id") != self.grant_id or consent.get("status") != "active"
                    or consent.get("permission") != permission or consent.get("pages") != pages
                    or consent.get("apps", ["browser"]) != apps
                    or consent.get("share_headings") is not share_headings
                    or type(seconds) not in (int, float) or not 0 < seconds <= MAX_GRANT_SECONDS):
                raise ComputerControlError("invalid_browser_run_response")
            deadline = min(deadline, began + seconds)
            if progress is not None:
                progress({"kind": "ready"})
            if permission == "view" and "browser" in apps and time.monotonic() < deadline:
                lab.step({"action": "open", "page": "overview"}, lambda _: time.monotonic() < deadline)
            share_links = share_headings and consent.get("section_links") is True
            return self._poll(lab, apps, approve, permission, share_headings, share_links, deadline, progress)
        finally:
            self._stop()

    def _poll(self, lab, apps, approve, permission, share_headings, share_links, deadline, progress):
        previous = {}
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
            app, args, expires = self._command(command, sequence, lab.targets, apps, requested, deadline)
            previous_id, previous_view = previous.get(app, (None, None))
            status, result = self._perform(lab, app, command, args, approve, permission, expires, previous_id, previous_view)
            body = {"command_id": command["id"], "status": status}
            if status in ("verified", "observed"):
                previous[app] = (command["id"], result["view"])
                body["view"] = (_view_for_report(result["view"], share_headings, share_links)
                                if app == "browser" else result["view"])
                receipts.append({"app": app, **result})
            else:
                previous.pop(app, None)
                receipts.append({"app": app, "action": args["action"], "error": status})
            if time.monotonic() >= expires:
                raise ComputerControlError("command_expired")
            if self._send("report", **body).get("accepted") is not True:
                raise ComputerControlError("invalid_browser_run_response")
            if progress is not None:
                progress({"kind": "action", "app": app, "action": args["action"], "status": status})
        raise ComputerControlError("grant_expired")

    @staticmethod
    def _command(command, sequence, pages, apps, requested, deadline):
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
        app, _, arguments = device_command({"action": action, **command["arguments"]}, pages, apps)
        return app, {"action": action, **arguments}, min(deadline, requested + command["expires_in_ms"] / 1000)

    def _perform(self, lab, app, command, args, approve, permission, expires, previous_id, previous_view):
        writing = args["action"] != "inspect"
        if time.monotonic() >= expires:
            return "stale_state", None
        if writing:
            if permission == "view":
                return "denied", None
            inspect = lab.inspect if app == "browser" else lambda: lab.notepad({"action": "inspect"}, expires)["view"]
            if previous_id is None or command["inspect_action_id"] != previous_id or inspect() != previous_view:
                return "stale_state", None
            approval = {"app": app, **args}
            if args["action"] == "click":
                link = next((link for link in previous_view.get("links", ()) if link["id"] == args["link_id"]), None)
                if link is None:
                    return "stale_state", None
                approval["label"] = link["label"]
            if not approve(approval, expires):
                return "denied", None
            if time.monotonic() >= expires or self.review() != "active" or inspect() != previous_view:
                return "stale_state", None
        result = (lab.step(args, lambda _: time.monotonic() < expires, expires=expires,
                           still_allowed=lambda: self.review() == "active" and lab.inspect() == previous_view) if app == "browser"
                  else lab.notepad(args, expires))
        if "error" in result or result.get("at_boundary"):
            return "stale_state", None
        return ("verified" if writing else "observed"), result
