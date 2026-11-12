"""Versioned, owner-scoped consent for Computer Use pilots."""

from dataclasses import dataclass, field
import re
import threading
import time
from uuid import uuid4

from troika_product.access import AccessPrincipal


VERSION = 1
MAX_GRANT_SECONDS = 120
MAX_OBSERVATION_SECONDS = 15
MAX_ACTIONS = 8
_MAX_GRANTS = 64
_ID = re.compile(r"[a-f0-9]{32}\Z")
_PLATFORMS = frozenset({"windows", "android"})
_APP = "scratchpad"


class ComputerControlError(ValueError):
    def __init__(self, code, status=409):
        super().__init__(code)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class ActionReceipt:
    action_id: str
    sequence: int
    action: str

    def payload(self):
        # This projection is safe for a later history integration. It has no
        # observation, window contents, input values, or raw command fields.
        return {"version": VERSION, "mode": "dry_run", "status": "simulated",
                "verified": False, "action_id": self.action_id,
                "sequence": self.sequence, "action": self.action}


@dataclass(frozen=True)
class _Observation:
    id: str
    expires_at: float
    model_inspect_id: str | None = None

    def payload(self):
        return {"id": self.id, "app": _APP, "elements": [
            {"id": "preview", "role": "button", "label": "Synthetic preview button"},
        ]}


@dataclass
class _Grant:
    id: str
    requester: AccessPrincipal
    target_device_id: str
    platform: str
    expires_at: float
    target: AccessPrincipal | None = None
    status: str = "pending"
    actions: dict = field(default_factory=dict)
    observation: _Observation | None = None

    mode = "dry_run"
    allowed_actions = ("inspect", "click")

    def summary(self, now):
        return {"version": VERSION, "mode": self.mode, "grant_id": self.id,
                "status": self.status, "requesting_device_id": self.requester.device_id,
                "target_device_id": self.target_device_id, "platform": self.platform,
                "app": _APP, "actions": list(self.allowed_actions),
                "action_limit": MAX_ACTIONS, "expires_in_seconds": max(0, self.expires_at - now)}

    def close(self, status):
        self.status = status
        self.observation = None
        self.actions.clear()


def _fields(body, *names):
    if set(body) != {"version", *names}:
        raise ComputerControlError("invalid_request", 400)


def _id(value):
    return isinstance(value, str) and _ID.fullmatch(value) is not None


class ComputerGrantControl:
    """One bounded consent and action ledger per active conversation run."""

    grant_type = _Grant
    platforms = _PLATFORMS
    allow_regrant = True

    def __init__(self, registry, run_owner, *, clock=time.monotonic):
        self._registry = registry
        self._run_owner = run_owner
        self._clock = clock
        self._lock = threading.RLock()
        self._grants: dict[str, _Grant] = {}

    def execute(self, principal, run_id, operation, body):
        if not isinstance(body, dict) or type(body.get("version")) is not int:
            raise ComputerControlError("invalid_request", 400)
        if body["version"] != VERSION:
            raise ComputerControlError("unsupported_version", 400)

        with self._lock:
            grant = self._grants.get(run_id)
            if operation == "request":
                return self._request(principal, run_id, grant, body)
            if not _id(body.get("grant_id")):
                raise ComputerControlError("invalid_request", 400)
            if grant is None or grant.id != body["grant_id"]:
                raise ComputerControlError("grant_not_found", 404)
            requester = principal == grant.requester
            target = (principal.user_id == grant.requester.user_id
                      and principal.device_id == grant.target_device_id
                      and (grant.target is None or principal == grant.target))
            if not (requester or target) or not self._registry.principal_is_active(principal):
                raise ComputerControlError("grant_not_found", 404)
            now = self._check_live(run_id, grant)

            if operation == "stop":
                _fields(body, "grant_id")
                if grant.status in {"pending", "active"}:
                    grant.close("stopped")
                return grant.summary(now)
            if operation == "review" and target:
                _fields(body, "grant_id")
                return grant.summary(now)
            if operation == "consent" and target:
                return self._consent(principal, grant, body, now)
            return self._operate(grant, operation, body, now, requester=requester, target=target)

    def _request(self, principal, run_id, existing, body):
        _fields(body, "target_device_id", "ttl_seconds")
        target, ttl = body["target_device_id"], body["ttl_seconds"]
        if not isinstance(target, str) or not 1 <= len(target) <= 64:
            raise ComputerControlError("invalid_request", 400)
        if type(ttl) is not int or not 1 <= ttl <= MAX_GRANT_SECONDS:
            raise ComputerControlError("invalid_request", 400)
        if self._run_owner(run_id) != (principal.user_id, principal.device_id):
            raise ComputerControlError("run_not_found", 404)
        try:
            devices = self._registry.list_devices(principal)
        except PermissionError:
            raise ComputerControlError("run_not_found", 404) from None
        device = next((item for item in devices if item.id == target and item.status == "active"), None)
        if device is None or device.platform not in self.platforms:
            raise ComputerControlError("device_not_found", 404)
        now = self._clock()
        if existing is not None and (not self.allow_regrant or existing.expires_at > now):
            raise ComputerControlError("grant_exists")
        for key, value in tuple(self._grants.items()):
            if value.expires_at <= now and (self.allow_regrant or self._run_owner(key) is None):
                value.close("expired")
                del self._grants[key]
        if len(self._grants) >= _MAX_GRANTS:
            raise ComputerControlError("capacity_reached", 429)
        grant = self.grant_type(uuid4().hex, principal, device.id, device.platform, now + ttl)
        self._grants[run_id] = grant
        return grant.summary(now)

    def _check_live(self, run_id, grant):
        if grant.status in {"pending", "active"}:
            if (not self._registry.principal_is_active(grant.requester)
                    or (grant.target is not None and not self._registry.principal_is_active(grant.target))):
                grant.close("revoked")
            elif self._run_owner(run_id) != (grant.requester.user_id, grant.requester.device_id):
                grant.close("stopped")
        now = self._clock()
        if now >= grant.expires_at:
            grant.close("expired")
            if self.allow_regrant or self._run_owner(run_id) is None:
                self._grants.pop(run_id, None)
            raise ComputerControlError("grant_expired")
        return now

    @staticmethod
    def _consent(principal, grant, body, now):
        _fields(body, "grant_id", "allow")
        allow = body["allow"]
        if type(allow) is not bool:
            raise ComputerControlError("invalid_request", 400)
        if grant.status != "pending":
            raise ComputerControlError("grant_" + grant.status)
        grant.target = principal
        grant.status = "active" if allow else "denied"
        return grant.summary(now)

    def model_grant_status(self, principal, run_id):
        with self._lock:
            grant = self._grants.get(run_id)
            if grant is None or grant.requester != principal:
                return "pending"
            if self._clock() >= grant.expires_at:
                grant.close("expired")
            if grant.status == "active":
                self._check_live(run_id, grant)
            return grant.status

    def pending_for_device(self, principal):
        with self._lock:
            if not self._registry.principal_is_active(principal):
                raise ComputerControlError("authentication_required", 401)
            pending = []
            for run_id, grant in tuple(self._grants.items()):
                if (grant.status != "pending" or grant.requester.user_id != principal.user_id
                        or grant.target_device_id != principal.device_id):
                    continue
                try:
                    now = self._check_live(run_id, grant)
                except ComputerControlError:
                    continue
                if grant.status == "pending":
                    pending.append({"run_id": run_id, **grant.summary(now)})
            return {"version": VERSION, "requests": pending}

    def stop_run(self, run_id):
        with self._lock:
            grant = self._grants.get(run_id)
            if grant is not None and grant.status in {"pending", "active"}:
                grant.close("stopped")

    def revoke_device(self, user_id, device_id):
        with self._lock:
            for grant in self._grants.values():
                if grant.requester.user_id == user_id and device_id in (
                        grant.requester.device_id, grant.target_device_id):
                    grant.close("revoked")

    def purge_account(self, user_id):
        with self._lock:
            for key, grant in tuple(self._grants.items()):
                if grant.requester.user_id == user_id:
                    grant.close("revoked")
                    del self._grants[key]

    def clear(self):
        with self._lock:
            for grant in self._grants.values():
                grant.close("stopped")
            self._grants.clear()


class ComputerDryRun(ComputerGrantControl):
    def _operate(self, grant, operation, body, now, *, requester, target):
        if operation == "action" and requester:
            return self._action(grant, body, now)
        raise ComputerControlError("grant_not_found", 404)

    @staticmethod
    def _action(grant, body, now, *, model=False):
        action = body.get("action")
        if action not in ("inspect", "click"):
            raise ComputerControlError("unsupported_action", 400)
        names = ("grant_id", "action_id", "sequence", "action")
        if action == "click":
            names += ("observation_id", "element_id")
        _fields(body, *names)
        action_id, sequence = body["action_id"], body["sequence"]
        if not _id(action_id) or type(sequence) is not int or not 1 <= sequence <= MAX_ACTIONS:
            raise ComputerControlError("invalid_request", 400)
        observation_id, element_id = body.get("observation_id"), body.get("element_id")
        if action == "click" and (not _id(observation_id) or element_id != "preview"):
            raise ComputerControlError("invalid_request", 400)
        if grant.status != "active":
            raise ComputerControlError("grant_" + grant.status)

        signature = (sequence, action, observation_id, element_id)
        previous = grant.actions.get(action_id)
        fresh = grant.observation is not None and now < grant.observation.expires_at
        if previous is not None:
            old_signature, receipt, issued_observation_id = previous
            if signature != old_signature:
                raise ComputerControlError("action_conflict")
            result = {"receipt": receipt.payload()}
            if fresh and grant.observation.id == issued_observation_id:
                result["observation"] = grant.observation.payload()
            return result
        if sequence != len(grant.actions) + 1:
            raise ComputerControlError("unexpected_sequence")
        if action == "click" and (not fresh or grant.observation.id != observation_id):
            raise ComputerControlError("stale_state")

        grant.observation = (_Observation(uuid4().hex, min(grant.expires_at, now + MAX_OBSERVATION_SECONDS),
                                         action_id if model else None)
                             if action == "inspect" else None)
        receipt = ActionReceipt(action_id, sequence, action)
        grant.actions[action_id] = (signature, receipt, grant.observation.id if grant.observation else None)
        result = {"receipt": receipt.payload()}
        if not model and grant.observation is not None:
            result["observation"] = grant.observation.payload()
        return result

    def model_action(self, principal, run_id, action, inspect_id=None):
        """Execute against the run's grant without exposing its private observation ID."""
        with self._lock:
            grant = self._grants.get(run_id)
            if grant is None or grant.requester != principal:
                raise ComputerControlError("grant_not_found", 404)
            now = self._check_live(run_id, grant)
            if grant.status != "active":
                raise ComputerControlError("grant_" + grant.status)
            body = {"version": VERSION, "grant_id": grant.id, "action_id": uuid4().hex,
                    "sequence": len(grant.actions) + 1, "action": action}
            if action == "click":
                observed = grant.observation
                if observed is None or not _id(inspect_id) or observed.model_inspect_id != inspect_id:
                    raise ComputerControlError("stale_state")
                body.update(observation_id=observed.id, element_id="preview")
            if body["sequence"] > MAX_ACTIONS:
                raise ComputerControlError("action_limit")
            result = self._action(grant, body, now, model=True)
            return result["receipt"]
