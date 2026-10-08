"""Owner/device-bound RAM relay for checks executed on a consenting user's PC.

The API never executes project code. Source and reports expire and are never
written to a server filesystem, database, or log.
"""

from dataclasses import dataclass
import secrets
import re
import threading
import time
import uuid

from troika_product.development import build_project

MODES = frozenset({"python_syntax", "python_tests", "javascript", "javascript_tests"})


@dataclass
class CheckJob:
    owner: str
    requester: str
    target: str
    mode: str
    workflow: str
    files: dict[str, str]
    expires: float
    state: str = "queued"
    lease: str = ""
    report: dict | None = None

    def metadata(self, job_id: str) -> dict:
        return {"id": job_id, "target_device_id": self.target, "mode": self.mode,
                "requester_device_id": self.requester, "workflow_id": self.workflow,
                "state": self.state, "expires_at": self.expires, "report": self.report}


class DevelopmentCheckStore:
    def __init__(self, *, ttl: float = 600, clock=time.time, max_bytes: int = 2_000_000):
        self.ttl, self.clock, self.max_bytes = ttl, clock, max_bytes
        self.jobs: dict[str, CheckJob] = {}
        self.targets: dict[tuple[str, str], float] = {}
        self.lock = threading.RLock()
        self.timers: dict[str, threading.Timer] = {}

    def heartbeat(self, owner: str, device: str, enabled: bool) -> None:
        with self.lock:
            if enabled:
                self.targets[owner, device] = self.clock() + 30
            else:
                self.targets.pop((owner, device), None)
                self.purge(owner, device)

    def available(self, owner: str, device: str) -> bool:
        return self.targets.get((owner, device), 0) > self.clock()

    def _remove(self, job_id: str) -> None:
        with self.lock:
            self.jobs.pop(job_id, None)
            timer = self.timers.pop(job_id, None)
            if timer:
                timer.cancel()

    def _purge_expired(self) -> None:
        for job_id, job in list(self.jobs.items()):
            if job.expires <= self.clock():
                self._remove(job_id)
        self.targets = {key: expiry for key, expiry in self.targets.items() if expiry > self.clock()}

    def create(self, owner: str, requester: str, target: str, mode: str, files: dict, workflow: str = "") -> dict:
        if mode not in MODES or not isinstance(files, dict):
            raise ValueError("unsupported check")
        if not isinstance(workflow, str) or not 1 <= len(workflow) <= 80:
            raise ValueError("invalid workflow")
        build_project({"files": [{"path": path, "content": source} for path, source in files.items()]})
        size = sum(len(source.encode("utf-8")) for source in files.values())
        if any(re.search(r"trk_live_[\w-]{16,}|sk-[\w-]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----", source)
               for source in files.values()):
            raise ValueError("source contains credentials")
        if size > 120_000:
            raise ValueError("project exceeds remote check limit")
        with self.lock:
            self._purge_expired()
            if not self.available(owner, target):
                raise ValueError("selected PC is unavailable")
            if sum(j.owner == owner and j.state in {"queued", "running"} for j in self.jobs.values()) >= 2:
                raise ValueError("check limit reached")
            if len(self.jobs) >= 128 or sum(j.owner == owner for j in self.jobs.values()) >= 16:
                raise ValueError("check history limit reached")
            if sum(sum(len(s.encode("utf-8")) for s in j.files.values()) +
                   len((j.report or {}).get("output", "").encode("utf-8")) for j in self.jobs.values()) + size > self.max_bytes:
                raise ValueError("check capacity exceeded")
            job_id = "check_" + uuid.uuid4().hex
            job = CheckJob(owner, requester, target, mode, workflow, dict(files), self.clock() + self.ttl)
            self.jobs[job_id] = job
            timer = threading.Timer(self.ttl, self._remove, args=(job_id,))
            timer.daemon = True
            self.timers[job_id] = timer
            timer.start()
            return job.metadata(job_id)

    def get(self, owner: str, device: str, job_id: str) -> dict | None:
        with self.lock:
            self._purge_expired()
            job = self.jobs.get(job_id)
            if job and job.owner == owner and device in {job.requester, job.target}:
                return job.metadata(job_id)
            return None

    def claim(self, owner: str, device: str) -> dict | None:
        with self.lock:
            self._purge_expired()
            for job_id, job in self.jobs.items():
                if job.owner == owner and job.target == device and job.state == "queued":
                    job.state, job.lease = "running", secrets.token_hex(16)
                    return {**job.metadata(job_id), "files": dict(job.files), "lease": job.lease}
            return None

    def finish(self, owner: str, device: str, job_id: str, lease: str, report: dict) -> bool:
        if not isinstance(report, dict) or type(report.get("exit_code")) is not int:
            raise ValueError("invalid report")
        output = report.get("output", "")
        if not isinstance(output, str) or len(output.encode("utf-8")) > 64_000:
            raise ValueError("invalid report output")
        output = re.sub(r"trk_live_[\w-]+|sk-[\w-]{20,}", "[REDACTED]", output)
        for key in ("timed_out", "no_tests", "cancelled"):
            if type(report.get(key, False)) is not bool:
                raise ValueError("invalid report flag")
        with self.lock:
            self._purge_expired()
            job = self.jobs.get(job_id)
            if not job or (job.owner, job.target, job.state, job.lease) != (owner, device, "running", lease):
                return False
            used = sum(sum(len(source.encode("utf-8")) for source in other.files.values()) +
                       len((other.report or {}).get("output", "").encode("utf-8"))
                       for other in self.jobs.values() if other is not job)
            output = output.encode("utf-8")[:max(0, self.max_bytes - used)].decode("utf-8", errors="ignore")
            job.report = {"exit_code": report["exit_code"], "output": output,
                          **{key: report.get(key, False) for key in ("timed_out", "no_tests", "cancelled")}}
            job.state = "completed"
            job.files.clear()
            job.lease = ""
            return True

    def cancel(self, owner: str, device: str, job_id: str) -> bool:
        with self.lock:
            self._purge_expired()
            job = self.jobs.get(job_id)
            if not job or job.owner != owner or device not in {job.requester, job.target}:
                return False
            if job.state in {"queued", "running"}:
                job.state = "cancelled"
                job.files.clear()
                job.lease = ""
            return True

    def purge(self, owner: str, device: str | None = None) -> None:
        with self.lock:
            for job_id, job in list(self.jobs.items()):
                if job.owner == owner and (device is None or device in {job.requester, job.target}):
                    self._remove(job_id)
            for key in list(self.targets):
                if key[0] == owner and (device is None or key[1] == device):
                    self.targets.pop(key)


development_checks = DevelopmentCheckStore()
