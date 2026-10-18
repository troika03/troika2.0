"""Durable owner/device metadata; project bytes are kept only on devices/RAM."""

import hashlib
import json
import time

from troika_product.development_agent import _paths


IDLE = {"paused", "waiting_budget", "interrupted", "completed", "failed", "cancelled"}


def checkpoint_bytes(value):
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("Unsupported development checkpoint")
    task, files = value.get("task"), value.get("files")
    if not isinstance(task, str) or not task.strip() or len(task) > 20000:
        raise ValueError("Invalid checkpoint task")
    if not isinstance(files, list) or any(not isinstance(f, dict) for f in files):
        raise ValueError("Invalid checkpoint sources")
    sources = {f.get("path"): f.get("content") for f in files}
    if len(sources) != len(files) or any(
        not isinstance(p, str) or not isinstance(c, str) for p, c in sources.items()
    ):
        raise ValueError("Invalid checkpoint sources")
    _paths({"task.txt": task})
    if sources:
        _paths(sources)
    completed = value.get("completed", [])
    if not isinstance(completed, list) or any(p not in sources for p in completed):
        raise ValueError("Invalid completed checkpoint files")
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    if len(data) > 2_500_000:
        raise ValueError("Development checkpoint is too large")
    return data


def checkpoint_digest(value):
    return hashlib.sha256(checkpoint_bytes(value)).hexdigest()


class DevelopmentSessions:
    def __init__(self, registry):
        self.registry = registry
        with registry._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS troika_development_projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES troika_users(id) ON DELETE CASCADE,
                device_id TEXT NOT NULL REFERENCES troika_devices(id) ON DELETE CASCADE,
                run_id TEXT NOT NULL, state TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0,
                digest TEXT NOT NULL DEFAULT '', confirmed INTEGER NOT NULL DEFAULT 0,
                confirmed_digest TEXT NOT NULL DEFAULT '',
                attempt INTEGER NOT NULL DEFAULT 1,
                budget_tokens INTEGER NOT NULL DEFAULT 250000,
                budget_approved INTEGER NOT NULL DEFAULT 0,
                personal_mode INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL, updated_at REAL NOT NULL
            )""")
            c.execute(
                "CREATE INDEX IF NOT EXISTS idx_development_owner ON troika_development_projects(user_id,device_id)"
            )
            c.execute("""CREATE TABLE IF NOT EXISTS troika_development_requests (
                project_id TEXT NOT NULL REFERENCES troika_development_projects(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL REFERENCES troika_users(id) ON DELETE CASCADE,
                device_id TEXT NOT NULL REFERENCES troika_devices(id) ON DELETE CASCADE,
                key_hash TEXT NOT NULL, request_hash TEXT NOT NULL, run_id TEXT NOT NULL,
                PRIMARY KEY(user_id,device_id,key_hash))""")

    def request(self, principal, key, request_hash):
        with self.registry._connect() as c:
            self.registry._require_active_principal(c, principal)
            row = c.execute(
                "SELECT * FROM troika_development_requests WHERE user_id=? AND device_id=? AND key_hash=?",
                (
                    principal.user_id,
                    principal.device_id,
                    hashlib.sha256(key.encode()).hexdigest(),
                ),
            ).fetchone()
            if row is None:
                return None
            if row["request_hash"] != request_hash:
                raise ValueError("Idempotency request changed")
            return dict(row)

    @staticmethod
    def remember(c, principal, project_id, run_id, request):
        if request is not None:
            key, digest = request
            c.execute(
                "INSERT INTO troika_development_requests VALUES (?,?,?,?,?,?)",
                (
                    project_id,
                    principal.user_id,
                    principal.device_id,
                    hashlib.sha256(key.encode()).hexdigest(),
                    digest,
                    run_id,
                ),
            )

    def get(self, principal, project_id):
        with self.registry._connect() as c:
            self.registry._require_active_principal(c, principal)
            row = c.execute(
                "SELECT * FROM troika_development_projects WHERE id=? AND user_id=? AND device_id=?",
                (project_id, principal.user_id, principal.device_id),
            ).fetchone()
            if row is None:
                raise PermissionError("Project is not owned by this device")
            return dict(row)

    def list(self, principal):
        with self.registry._connect() as c:
            self.registry._require_active_principal(c, principal)
            return [
                dict(row)
                for row in c.execute(
                    "SELECT * FROM troika_development_projects WHERE user_id=? AND device_id=? ORDER BY updated_at DESC LIMIT 40",
                    (principal.user_id, principal.device_id),
                )
            ]

    def create(
        self,
        principal,
        project_id,
        run_id,
        *,
        budget_tokens=250000,
        personal_mode=False,
        approved=False,
        request=None,
    ):
        now = time.time()
        with self.registry._connect() as c:
            self.registry._require_active_principal(c, principal)
            c.execute(
                "INSERT INTO troika_development_projects(id,user_id,device_id,run_id,state,created_at,updated_at,budget_tokens,personal_mode,budget_approved) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    project_id,
                    principal.user_id,
                    principal.device_id,
                    run_id,
                    "queued",
                    now,
                    now,
                    budget_tokens,
                    int(personal_mode),
                    int(approved),
                ),
            )
            self.remember(c, principal, project_id, run_id, request)

    def checkpoint(self, principal, project_id, run_id, value):
        digest = checkpoint_digest(value)
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self.registry._require_active_principal(c, principal)
            row = c.execute(
                "SELECT revision,digest FROM troika_development_projects WHERE id=? AND user_id=? AND device_id=? AND run_id=?",
                (project_id, principal.user_id, principal.device_id, run_id),
            ).fetchone()
            if row is None:
                raise PermissionError("Stale project attempt")
            revision = row["revision"] + (row["digest"] != digest)
            c.execute(
                "UPDATE troika_development_projects SET revision=?,digest=?,updated_at=? WHERE id=?",
                (revision, digest, time.time(), project_id),
            )
        return revision, digest

    def acknowledge(self, principal, project_id, revision, digest):
        row = self.get(principal, project_id)
        if (
            type(revision) is not int
            or row["revision"] != revision
            or row["digest"] != digest
        ):
            raise ValueError("Checkpoint changed before acknowledgement")
        with self.registry._connect() as c:
            self.registry._require_active_principal(c, principal)
            changed = c.execute(
                "UPDATE troika_development_projects SET confirmed=?,confirmed_digest=? WHERE id=? AND revision=? AND digest=?",
                (revision, digest, project_id, revision, digest),
            ).rowcount
            if not changed:
                raise ValueError("Checkpoint changed before acknowledgement")

    def state(self, principal, project_id, run_id, state):
        with self.registry._connect() as c:
            self.registry._require_active_principal(c, principal)
            c.execute(
                "UPDATE troika_development_projects SET state=?,updated_at=? WHERE id=? AND user_id=? AND device_id=? AND run_id=?",
                (
                    state,
                    time.time(),
                    project_id,
                    principal.user_id,
                    principal.device_id,
                    run_id,
                ),
            )

    def resume(
        self,
        principal,
        project_id,
        revision,
        value,
        run_id,
        *,
        budget_tokens=250000,
        approved=True,
        request=None,
    ):
        digest = checkpoint_digest(value)
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self.registry._require_active_principal(c, principal)
            row = c.execute(
                "SELECT * FROM troika_development_projects WHERE id=? AND user_id=? AND device_id=?",
                (project_id, principal.user_id, principal.device_id),
            ).fetchone()
            if row is None:
                raise PermissionError("Project is not owned by this device")
            latest = revision == row["revision"] and digest == row["digest"]
            durable = revision == row["confirmed"] and digest == row["confirmed_digest"]
            if (
                row["state"] not in IDLE
                or type(revision) is not int
                or not (latest or durable)
            ):
                raise ValueError("Checkpoint or active project changed")
            c.execute(
                "UPDATE troika_development_projects SET run_id=?,state='queued',attempt=attempt+1,updated_at=?,budget_tokens=?,budget_approved=? WHERE id=?",
                (run_id, time.time(), budget_tokens, int(approved), project_id),
            )
            self.remember(c, principal, project_id, run_id, request)
        return dict(row)
