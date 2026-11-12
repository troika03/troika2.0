"""A reviewed frame and verified editor actions under one Windows grant."""

from dataclasses import dataclass
from functools import partial

from troika_product.computer_control import ComputerControlError, MAX_ACTIONS, _fields
from troika_product.computer_windows_lab import WindowsComputerLab, _WindowsGrant
from troika_product.computer_windows_vision import WindowsVisionLab, _VisionGrant


MODE = "windows_assisted_lab"


@dataclass
class _AssistedGrant(_WindowsGrant, _VisionGrant):
    mode = MODE
    allowed_actions = (*_WindowsGrant.allowed_actions, *_VisionGrant.allowed_actions)
    frame_approved: bool = False
    vision_ready: bool = False
    permission_mode: str = "ask"
    action_denied: bool = False

    def summary(self, now):
        return {**super().summary(now), "action_limit": MAX_ACTIONS, "permission_mode": self.permission_mode}


class WindowsAssistedLab(WindowsComputerLab, WindowsVisionLab):
    command_seconds = 30
    observation_seconds = 30
    allow_denial = True

    def __init__(self, registry, run_owner, *, openrouter):
        super().__init__(registry, run_owner, openrouter=openrouter)
        self.grant_type = partial(_AssistedGrant, vision_provider="openrouter")

    @staticmethod
    def _consent(principal, grant, body, now):
        options = dict(body)
        policy = options.pop("permission_mode", "ask")
        if policy not in ("ask", "window", "view"):
            raise ComputerControlError("invalid_permission_mode", 400)
        response = WindowsComputerLab._consent(principal, grant, options, now)
        grant.permission_mode = policy
        return {**response, "permission_mode": policy}

    def _operate(self, grant, operation, body, now, *, requester, target):
        if operation in {"approve_frame", "check_frame", "frame"}:
            if not target:
                raise ComputerControlError("grant_not_found", 404)
            if grant.status != "active":
                raise ComputerControlError("grant_" + grant.status)
            if operation == "approve_frame":
                _fields(body, "grant_id", "vision_provider")
                if body["vision_provider"] != grant.vision_provider:
                    raise ComputerControlError("vision_provider_consent_required", 400)
                if grant.frame_approved:
                    raise ComputerControlError("frame_already_approved")
                grant.frame_approved = True
                return grant.summary(now)
            if not grant.frame_approved:
                raise ComputerControlError("vision_provider_consent_required")
            return WindowsVisionLab._operate(self, grant, operation, body, now, requester=requester, target=target)
        return super()._operate(grant, operation, body, now, requester=requester, target=target)

    def complete_vision(self, principal, run_id):
        with self._lock:
            self.model_frame(principal, run_id, dispatched=True)
            grant = self._grants[run_id]
            grant.vision_ready = True
            return grant.permission_mode

    def action_time(self, principal, run_id):
        with self._lock:
            grant = self._grants.get(run_id)
            if grant is None or grant.requester != principal:
                raise ComputerControlError("grant_not_found", 404)
            now = self._check_live(run_id, grant)
            if grant.status != "active":
                raise ComputerControlError("grant_" + grant.status)
            if not grant.vision_ready:
                raise ComputerControlError("vision_observation_required")
            return grant.expires_at - now

    def model_action(self, principal, run_id, action, inspect_id=None, *, text=None):
        self.action_time(principal, run_id)
        if action in {"write", "save"}:
            with self._lock:
                grant = self._grants.get(run_id)
                if grant is None or grant.status != "active":
                    raise ComputerControlError("grant_stopped")
                if grant.permission_mode == "view" or grant.action_denied:
                    raise ComputerControlError("action_denied")
        return super().model_action(principal, run_id, action, inspect_id, text=text)

    def _report(self, grant, body, now):
        response = super()._report(grant, body, now)
        if body["status"] == "denied":
            grant.action_denied = True
        return response
