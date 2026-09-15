"""Owner-scoped retention for Troika's current local product stores.

This module deliberately covers only the SQLite and filesystem stores used by
the current product runtime.  Production object storage and backup deletion
need their own verified adapters before they can be reported as complete.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable

from troika_product.access import AccessRegistry
from troika_product.artifacts import ArtifactStore


DAY_SECONDS = 86_400


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention limits approved for the current local product runtime."""

    revoked_credentials_days: int = 90
    conversations_days: int = 365
    memories_days: int = 730
    artifacts_days: int = 365
    project_data_days: int = 730
    delivered_inbox_days: int = 90
    pending_inbox_days: int = 365
    device_context_hours: int = 24
    saved_locations_days: int = 365
    vision_sessions_days: int = 30
    audit_and_usage_days: int = 400

    def cutoff(self, now: float, *, days: int = 0, hours: int = 0) -> float:
        return now - days * DAY_SECONDS - hours * 3600


@dataclass
class RetentionReport:
    """Privacy-safe result of one dry-run or applying run."""

    started_at: float
    finished_at: float
    dry_run: bool
    owner_count: int
    counts: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    local_stores_only: bool = True
    object_storage_purge_verified: bool = False
    backup_deletion_verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["counts"] = dict(sorted(self.counts.items()))
        return result


def delete_session_files_strict(sessions_dir: Path, session_id: str) -> None:
    """Delete direct transcript files and report any incomplete cleanup."""
    if not sessions_dir.exists():
        return
    exact_names = {f"{session_id}.json", f"{session_id}.jsonl"}
    dump_prefix = f"request_dump_{session_id}_"
    targets = [
        entry
        for entry in sessions_dir.iterdir()
        if entry.name in exact_names
        or (entry.name.startswith(dump_prefix) and entry.name.endswith(".json"))
    ]
    for target in targets:
        if target.is_dir():
            raise OSError("session cleanup target is unexpectedly a directory")
        target.unlink(missing_ok=True)
    if any(target.exists() for target in targets):
        raise OSError("session transcript cleanup was incomplete")


class RetentionWorker:
    """Apply retention independently for each product owner."""

    def __init__(
        self,
        access_registry: AccessRegistry,
        *,
        artifact_store: ArtifactStore | None = None,
        session_db: Any | None = None,
        sessions_dir: Path | None = None,
        session_file_purger: Callable[[Path, str], None] = delete_session_files_strict,
        policy: RetentionPolicy | None = None,
    ) -> None:
        self.access_registry = access_registry
        self.database_path = Path(access_registry.database_path)
        self.artifact_store = artifact_store
        self.session_db = session_db
        self.sessions_dir = Path(sessions_dir) if sessions_dir is not None else None
        self.session_file_purger = session_file_purger
        self.policy = policy or RetentionPolicy()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _add(counts: dict[str, int], key: str, value: int) -> None:
        counts[key] = counts.get(key, 0) + int(value)

    @staticmethod
    def _failure(failures: list[str], phase: str, exc: BaseException) -> None:
        failures.append(f"{phase}:{type(exc).__name__}")

    def _owner_ids(self, user_id: str | None) -> list[str]:
        with self._connect() as connection:
            if user_id is None:
                rows = connection.execute(
                    "SELECT id FROM troika_users WHERE status = 'active' ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id FROM troika_users WHERE id = ? AND status = 'active'",
                    (user_id,),
                ).fetchall()
        owners = [str(row["id"]) for row in rows]
        if user_id is not None and not owners:
            raise ValueError("active retention owner not found")
        return owners

    def _device_ids(self, user_id: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM troika_devices WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def _prune_locations(
        self, user_id: str, now: float, dry_run: bool, counts: dict[str, int]
    ) -> None:
        from tools.location_tool import prune_location_scope

        context_cutoff = self.policy.cutoff(
            now, hours=self.policy.device_context_hours
        )
        location_cutoff = self.policy.cutoff(
            now, days=self.policy.saved_locations_days
        )
        for device_id in self._device_ids(user_id):
            result = prune_location_scope(
                f"troika:{user_id}:{device_id}",
                context_cutoff=context_cutoff,
                location_cutoff=location_cutoff,
                dry_run=dry_run,
            )
            self._add(counts, "device_context", result["device_context"])
            self._add(counts, "saved_locations", result["saved_locations"])

    def _prune_artifacts(
        self, user_id: str, now: float, dry_run: bool, counts: dict[str, int]
    ) -> None:
        cutoff = self.policy.cutoff(now, days=self.policy.artifacts_days)
        with self._connect() as connection:
            tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if "troika_artifacts" not in tables:
                return
            rows = connection.execute(
                "SELECT id FROM troika_artifacts "
                "WHERE user_id = ? AND created_at < ? ORDER BY id",
                (user_id, cutoff),
            ).fetchall()
        artifact_ids = [str(row["id"]) for row in rows]
        if dry_run:
            self._add(counts, "artifacts", len(artifact_ids))
            return
        if artifact_ids and self.artifact_store is None:
            raise RuntimeError("artifact storage is unavailable")
        for artifact_id in artifact_ids:
            removed = self.artifact_store.purge_for_user(user_id, artifact_id)
            if removed is not None:
                self._add(counts, "artifacts", 1)

    def _session_last_active(self, session_id: str, fallback: float) -> float:
        if self.session_db is None:
            return fallback
        session = self.session_db.get_session(session_id)
        if session is None:
            return fallback
        last_active = float(session.get("started_at") or fallback)
        for message in self.session_db.get_messages(session_id):
            timestamp = message.get("timestamp")
            if isinstance(timestamp, (int, float)):
                last_active = max(last_active, float(timestamp))
        return last_active

    def _prune_sessions(
        self, user_id: str, now: float, dry_run: bool, counts: dict[str, int]
    ) -> None:
        cutoff = self.policy.cutoff(now, days=self.policy.conversations_days)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT session_id, created_at FROM troika_sessions "
                "WHERE user_id = ? ORDER BY session_id",
                (user_id,),
            ).fetchall()
        candidates = [
            str(row["session_id"])
            for row in rows
            if self._session_last_active(
                str(row["session_id"]), float(row["created_at"])
            )
            < cutoff
        ]
        if dry_run:
            self._add(counts, "conversations", len(candidates))
            return
        if candidates and self.session_db is None:
            raise RuntimeError("session storage is unavailable")
        for session_id in candidates:
            if self.session_db.get_session(session_id) is not None:
                self.session_db.delete_session(session_id)
            if self.sessions_dir is not None:
                self.session_file_purger(self.sessions_dir, session_id)
            if self.session_db.get_session(session_id) is not None:
                raise RuntimeError("session deletion was incomplete")
            with self._connect() as connection:
                cursor = connection.execute(
                    "DELETE FROM troika_sessions "
                    "WHERE session_id = ? AND user_id = ?",
                    (session_id, user_id),
                )
            self._add(counts, "conversations", cursor.rowcount)

    def _prune_product_rows(
        self, user_id: str, now: float, dry_run: bool, counts: dict[str, int]
    ) -> None:
        row_counts: dict[str, int] = {}
        p = self.policy
        memory_cutoff = p.cutoff(now, days=p.memories_days)
        project_cutoff = p.cutoff(now, days=p.project_data_days)
        delivered_cutoff = p.cutoff(now, days=p.delivered_inbox_days)
        pending_cutoff = p.cutoff(now, days=p.pending_inbox_days)
        vision_cutoff = p.cutoff(now, days=p.vision_sessions_days)
        audit_cutoff = p.cutoff(now, days=p.audit_and_usage_days)
        credential_cutoff = p.cutoff(now, days=p.revoked_credentials_days)
        usage_cutoff = datetime.fromtimestamp(
            audit_cutoff, timezone.utc
        ).date().isoformat()

        with self._connect() as connection:
            tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if not dry_run:
                connection.execute("BEGIN IMMEDIATE")

            def count(query: str, params: tuple[Any, ...]) -> int:
                row = connection.execute(
                    f"SELECT COUNT(*) FROM ({query}) AS candidates", params
                ).fetchone()
                return int(row[0])

            def remove(
                key: str,
                select_query: str,
                delete_query: str,
                params: tuple[Any, ...],
            ) -> None:
                if dry_run:
                    self._add(row_counts, key, count(select_query, params))
                else:
                    cursor = connection.execute(delete_query, params)
                    self._add(row_counts, key, cursor.rowcount)

            if "troika_vision_sessions" in tables:
                condition = (
                    "user_id = ? AND COALESCE(consumed_at, expires_at) < ?"
                )
                remove(
                    "vision_sessions",
                    f"SELECT id FROM troika_vision_sessions WHERE {condition}",
                    f"DELETE FROM troika_vision_sessions WHERE {condition}",
                    (user_id, vision_cutoff),
                )

            if "troika_memories" in tables:
                condition = "user_id = ? AND updated_at < ?"
                remove(
                    "memories",
                    f"SELECT id FROM troika_memories WHERE {condition}",
                    f"DELETE FROM troika_memories WHERE {condition}",
                    (user_id, memory_cutoff),
                )

            if "troika_inbox_messages" in tables:
                delivered = "user_id = ? AND delivered_at IS NOT NULL AND delivered_at < ?"
                remove(
                    "delivered_inbox",
                    f"SELECT id FROM troika_inbox_messages WHERE {delivered}",
                    f"DELETE FROM troika_inbox_messages WHERE {delivered}",
                    (user_id, delivered_cutoff),
                )
                pending = "user_id = ? AND delivered_at IS NULL AND created_at < ?"
                remove(
                    "pending_inbox",
                    f"SELECT id FROM troika_inbox_messages WHERE {pending}",
                    f"DELETE FROM troika_inbox_messages WHERE {pending}",
                    (user_id, pending_cutoff),
                )

            if "troika_project_tasks" in tables:
                task_condition = "user_id = ? AND updated_at < ?"
                if not dry_run and "troika_inbox_messages" in tables:
                    connection.execute(
                        "UPDATE troika_inbox_messages SET task_id = NULL "
                        "WHERE user_id = ? AND task_id IN ("
                        "SELECT id FROM troika_project_tasks "
                        "WHERE user_id = ? AND updated_at < ?)",
                        (user_id, user_id, project_cutoff),
                    )
                remove(
                    "project_tasks",
                    f"SELECT id FROM troika_project_tasks WHERE {task_condition}",
                    f"DELETE FROM troika_project_tasks WHERE {task_condition}",
                    (user_id, project_cutoff),
                )

            if "troika_project_notes" in tables:
                note_condition = "user_id = ? AND created_at < ?"
                remove(
                    "project_notes",
                    f"SELECT id FROM troika_project_notes WHERE {note_condition}",
                    f"DELETE FROM troika_project_notes WHERE {note_condition}",
                    (user_id, project_cutoff),
                )

            if "troika_projects" in tables:
                recent_task = (
                    "EXISTS (SELECT 1 FROM troika_project_tasks AS t "
                    "WHERE t.user_id = ? AND t.project_id = troika_projects.id "
                    "AND t.updated_at >= ?)"
                    if "troika_project_tasks" in tables
                    else "0"
                )
                recent_note = (
                    "EXISTS (SELECT 1 FROM troika_project_notes AS n "
                    "WHERE n.user_id = ? AND n.project_id = troika_projects.id "
                    "AND n.created_at >= ?)"
                    if "troika_project_notes" in tables
                    else "0"
                )
                project_params: list[Any] = [user_id, project_cutoff]
                if "troika_project_tasks" in tables:
                    project_params.extend([user_id, project_cutoff])
                if "troika_project_notes" in tables:
                    project_params.extend([user_id, project_cutoff])
                project_condition = (
                    f"user_id = ? AND updated_at < ? AND NOT ({recent_task}) "
                    f"AND NOT ({recent_note})"
                )
                if not dry_run and "troika_inbox_messages" in tables:
                    connection.execute(
                        "UPDATE troika_inbox_messages SET project_id = NULL "
                        f"WHERE user_id = ? AND project_id IN (SELECT id FROM "
                        f"troika_projects WHERE {project_condition})",
                        (user_id, *project_params),
                    )
                remove(
                    "projects",
                    f"SELECT id FROM troika_projects WHERE {project_condition}",
                    f"DELETE FROM troika_projects WHERE {project_condition}",
                    tuple(project_params),
                )

            audit_condition = "user_id = ? AND occurred_at < ?"
            remove(
                "audit_events",
                f"SELECT id FROM troika_audit_events WHERE {audit_condition}",
                f"DELETE FROM troika_audit_events WHERE {audit_condition}",
                (user_id, audit_cutoff),
            )
            usage_condition = "user_id = ? AND usage_date < ?"
            remove(
                "usage_daily",
                f"SELECT usage_date FROM troika_usage_daily WHERE {usage_condition}",
                f"DELETE FROM troika_usage_daily WHERE {usage_condition}",
                (user_id, usage_cutoff),
            )

            inactive_at = (
                "CASE WHEN tokens.revoked_at IS NULL THEN tokens.expires_at "
                "WHEN tokens.expires_at IS NULL THEN tokens.revoked_at "
                "ELSE MIN(tokens.revoked_at, tokens.expires_at) END"
            )
            token_condition = (
                "devices.user_id = ? AND "
                f"{inactive_at} IS NOT NULL AND {inactive_at} < ?"
            )
            token_params: list[Any] = [user_id, credential_cutoff]
            if "troika_vision_sessions" in tables:
                token_condition += (
                    " AND NOT EXISTS (SELECT 1 FROM troika_vision_sessions AS vision "
                    "WHERE vision.token_id = tokens.id "
                    "AND COALESCE(vision.consumed_at, vision.expires_at) >= ?)"
                )
                token_params.append(vision_cutoff)
            token_select = (
                "SELECT tokens.id FROM troika_api_tokens AS tokens "
                "JOIN troika_devices AS devices ON devices.id = tokens.device_id "
                f"WHERE {token_condition}"
            )
            token_delete = (
                "DELETE FROM troika_api_tokens WHERE id IN ("
                f"{token_select})"
            )
            remove(
                "api_tokens", token_select, token_delete, tuple(token_params)
            )

            device_condition = (
                "user_id = ? AND status = 'revoked' AND revoked_at IS NOT NULL "
                "AND revoked_at < ?"
            )
            if dry_run:
                self._add(
                    row_counts,
                    "revoked_device_metadata",
                    count(
                        f"SELECT id FROM troika_devices WHERE {device_condition}",
                        (user_id, credential_cutoff),
                    ),
                )
            else:
                cursor = connection.execute(
                    "UPDATE troika_devices SET name = '', platform = '', "
                    "status = 'purged' WHERE " + device_condition,
                    (user_id, credential_cutoff),
                )
                self._add(row_counts, "revoked_device_metadata", cursor.rowcount)
        for key, value in row_counts.items():
            self._add(counts, key, value)

    def run(
        self,
        *,
        now: float | None = None,
        dry_run: bool = True,
        user_id: str | None = None,
    ) -> RetentionReport:
        """Run all local-store retention phases with an injectable clock."""
        wall_started_at = time.time()
        started_at = wall_started_at if now is None else float(now)
        if not math.isfinite(started_at) or started_at < 0:
            raise ValueError("now must be a finite Unix timestamp")
        owners = self._owner_ids(user_id)
        counts: dict[str, int] = {}
        failures: list[str] = []
        for owner_id in owners:
            for phase, action in (
                ("locations", self._prune_locations),
                ("artifacts", self._prune_artifacts),
                ("sessions", self._prune_sessions),
                ("database", self._prune_product_rows),
            ):
                try:
                    action(owner_id, started_at, dry_run, counts)
                except Exception as exc:
                    self._failure(failures, phase, exc)
        return RetentionReport(
            started_at=started_at,
            finished_at=started_at + max(0.0, time.time() - wall_started_at),
            dry_run=bool(dry_run),
            owner_count=len(owners),
            counts=counts,
            failures=failures,
        )
