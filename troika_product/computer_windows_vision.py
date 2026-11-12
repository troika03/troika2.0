"""One reviewed frame from a selected Windows device, scoped to a test Run."""

from dataclasses import dataclass, field

from troika_product.computer_control import (
    ComputerControlError, ComputerGrantControl, MAX_OBSERVATION_SECONDS, VERSION, _Grant, _fields,
)


MODE = "windows_vision_lab"


@dataclass
class _VisionGrant(_Grant):
    mode = MODE
    allowed_actions = ("inspect_frame",)
    submitted: bool = False
    receiving: bool = False
    frame: bytes | None = field(default=None, repr=False)
    frame_expires_at: float = 0

    def summary(self, now):
        return {**super().summary(now), "action_limit": 1}

    def close(self, status):
        super().close(status)
        self.frame = None
        self.receiving = False


class WindowsVisionLab(ComputerGrantControl):
    grant_type = _VisionGrant
    platforms = frozenset({"windows"})
    allow_regrant = False

    def _operate(self, grant, operation, body, now, *, requester, target):
        if not target or operation not in {"check_frame", "frame"}:
            raise ComputerControlError("grant_not_found", 404)
        if grant.status != "active":
            raise ComputerControlError("grant_" + grant.status)
        if grant.submitted:
            raise ComputerControlError("frame_already_submitted")
        if operation == "check_frame":
            _fields(body, "grant_id")
            if grant.receiving:
                raise ComputerControlError("frame_busy")
            grant.receiving = True
            return now
        _fields(body, "grant_id", "frame", "expires_at")
        if not grant.receiving:
            raise ComputerControlError("frame_unavailable")
        expires_at = min(grant.expires_at, now + MAX_OBSERVATION_SECONDS, body["expires_at"])
        if now >= expires_at:
            raise ComputerControlError("frame_expired")
        grant.frame = body["frame"]
        grant.frame_expires_at = expires_at
        grant.submitted = True
        return {"version": VERSION, "mode": MODE, "accepted": True}

    def release_upload(self, principal, run_id, grant_id):
        with self._lock:
            grant = self._grants.get(run_id)
            if grant is not None and grant.id == grant_id and grant.target == principal:
                grant.receiving = False

    def model_frame(self, principal, run_id, *, take=False, dispatched=False):
        with self._lock:
            grant = self._grants.get(run_id)
            if grant is None or grant.requester != principal:
                raise ComputerControlError("grant_not_found", 404)
            now = self._check_live(run_id, grant)
            if grant.status != "active":
                raise ComputerControlError("grant_" + grant.status)
            if not grant.submitted:
                return None
            if now >= grant.frame_expires_at:
                grant.close("expired")
                raise ComputerControlError("frame_expired")
            if dispatched:
                return True
            frame = grant.frame
            if take:
                grant.frame = None
            return frame if take else frame is not None
