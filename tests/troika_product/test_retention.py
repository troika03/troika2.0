import asyncio
from datetime import datetime, timezone
import sqlite3
import time
import uuid
from unittest.mock import patch

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from hermes_state import SessionDB
from troika_product.access import AccessRegistry
from troika_product.artifacts import ArtifactStore
from troika_product.memory import MemoryStore
from troika_product.proactive import ProactiveStore
from troika_product.retention import RetentionWorker
from troika_product.vision_sessions import VisionSessionStore
from tools import location_tool


NOW = 2_000_000_000.0
OLD = NOW - 800 * 86_400


def test_access_registry_adds_device_revocation_time_without_losing_rows(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE troika_users (
                id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'active', created_at REAL NOT NULL
            );
            CREATE TABLE troika_devices (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES troika_users(id),
                name TEXT NOT NULL, platform TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active', created_at REAL NOT NULL
            );
            INSERT INTO troika_users VALUES ('usr_legacy', 'legacy@example.com', 'active', 1);
            INSERT INTO troika_devices VALUES (
                'dev_legacy', 'usr_legacy', 'Legacy phone', 'android', 'active', 2
            );
            """
        )

    registry = AccessRegistry(database)
    with registry._connect() as connection:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(troika_devices)")
        }
        device = connection.execute(
            "SELECT name, platform, revoked_at FROM troika_devices WHERE id = 'dev_legacy'"
        ).fetchone()
    assert "revoked_at" in columns
    assert tuple(device) == ("Legacy phone", "android", None)


def _owner(registry: AccessRegistry, email: str):
    user_id = registry.create_user(email)
    device_id = registry.create_device(user_id, name="Phone", platform="android")
    token = registry.issue_device_token(device_id)
    principal = registry.authenticate(token)
    assert principal is not None
    return user_id, device_id, token, principal


def _seed_owner(
    registry: AccessRegistry,
    artifacts: ArtifactStore,
    sessions: SessionDB,
    proactive: ProactiveStore,
    memories: MemoryStore,
    vision: VisionSessionStore,
    *,
    email: str,
    sessions_dir,
):
    user_id, device_id, _, principal = _owner(registry, email)
    suffix = uuid.uuid4().hex

    old_memory = memories.create_memory(
        principal, title=f"old-{suffix}", content="expired memory"
    )
    fresh_memory = memories.create_memory(
        principal, title=f"fresh-{suffix}", content="current memory"
    )
    old_artifact = artifacts.create(
        user_id=user_id,
        device_id=device_id,
        filename="old.pdf",
        kind="pdf",
        data=b"%PDF-1.4 old",
    )
    fresh_artifact = artifacts.create(
        user_id=user_id,
        device_id=device_id,
        filename="fresh.pdf",
        kind="pdf",
        data=b"%PDF-1.4 fresh",
    )

    old_session = f"session-{suffix}"
    fresh_session = f"session-fresh-{suffix}"
    assert registry.claim_session(principal, old_session)
    assert registry.claim_session(principal, fresh_session)
    sessions.create_session(old_session, source="api_server")
    sessions.create_session(fresh_session, source="api_server")
    transcript = sessions_dir / f"{old_session}.json"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text("private transcript", encoding="utf-8")

    project = proactive.create_project(principal, name=f"Project {suffix[:8]}")
    task = proactive.create_task(principal, title="Old task", project_id=project.id)
    note = proactive.add_note(
        principal,
        content="Old note",
        project_id=project.id,
        idempotency_key=f"note-{suffix}",
    )
    fresh_project = proactive.create_project(
        principal, name=f"Fresh {suffix[:8]}"
    )
    fresh_task = proactive.create_task(
        principal, title="Fresh task", project_id=fresh_project.id
    )
    fresh_note = proactive.add_note(
        principal,
        content="Fresh note",
        project_id=fresh_project.id,
        idempotency_key=f"fresh-note-{suffix}",
    )

    revoked_device = registry.create_device(
        user_id, name="Retired phone", platform="android"
    )
    revoked_token = registry.issue_device_token(revoked_device)
    revoked_principal = registry.authenticate(revoked_token)
    assert revoked_principal is not None
    grant = vision.create(revoked_principal, now=OLD - 60)
    fresh_grant = vision.create(principal, now=NOW - 60)
    assert registry.revoke_token(revoked_token)

    scope = f"troika:{user_id}:{device_id}"
    location_tool.remember_device_context(scope, {"ssid": email}, now=OLD)
    location_connection = location_tool._conn()
    try:
        location_connection.execute(
            "INSERT INTO locations "
            "(session_key, name, ssid, updated_at) VALUES (?, ?, ?, ?)",
            (scope, "old-place", email, OLD),
        )
        location_connection.execute(
            "INSERT INTO locations "
            "(session_key, name, ssid, updated_at) VALUES (?, ?, ?, ?)",
            (scope, "fresh-place", email, NOW - 1),
        )
        location_connection.commit()
    finally:
        location_connection.close()

    with sqlite3.connect(registry.database_path) as connection:
        connection.execute(
            "UPDATE troika_memories SET created_at = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (OLD, OLD, old_memory.id, user_id),
        )
        connection.execute(
            "UPDATE troika_memories SET created_at = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (NOW - 1, NOW - 1, fresh_memory.id, user_id),
        )
        connection.execute(
            "UPDATE troika_artifacts SET created_at = ? "
            "WHERE id = ? AND user_id = ?",
            (OLD, old_artifact.id, user_id),
        )
        connection.execute(
            "UPDATE troika_artifacts SET created_at = ? "
            "WHERE id = ? AND user_id = ?",
            (NOW - 1, fresh_artifact.id, user_id),
        )
        connection.execute(
            "UPDATE troika_sessions SET created_at = ? "
            "WHERE session_id = ? AND user_id = ?",
            (OLD, old_session, user_id),
        )
        connection.execute(
            "UPDATE troika_sessions SET created_at = ? "
            "WHERE session_id = ? AND user_id = ?",
            (NOW - 1, fresh_session, user_id),
        )
        connection.execute(
            "UPDATE troika_projects SET created_at = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (OLD, OLD, project.id, user_id),
        )
        connection.execute(
            "UPDATE troika_project_tasks SET created_at = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (OLD, OLD, task.id, user_id),
        )
        connection.execute(
            "UPDATE troika_project_notes SET created_at = ? "
            "WHERE id = ? AND user_id = ?",
            (OLD, note["id"], user_id),
        )
        connection.execute(
            "UPDATE troika_projects SET created_at = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (NOW - 1, NOW - 1, fresh_project.id, user_id),
        )
        connection.execute(
            "UPDATE troika_project_tasks SET created_at = ?, updated_at = ? "
            "WHERE id = ? AND user_id = ?",
            (NOW - 1, NOW - 1, fresh_task.id, user_id),
        )
        connection.execute(
            "UPDATE troika_project_notes SET created_at = ? "
            "WHERE id = ? AND user_id = ?",
            (NOW - 1, fresh_note["id"], user_id),
        )
        connection.execute(
            "INSERT INTO troika_inbox_messages "
            "(id, user_id, kind, category, title, body, reason, project_id, task_id, "
            "available_at, delivered_at, requires_approval, idempotency_key, created_at) "
            "VALUES (?, ?, 'follow_up', 'progress', 'Old', 'Old', 'Old', ?, ?, ?, ?, 0, ?, ?)",
            (
                f"msg_{suffix}", user_id, project.id, task.id, OLD, OLD,
                f"inbox-{suffix}", OLD,
            ),
        )
        connection.execute(
            "INSERT INTO troika_usage_daily "
            "(user_id, usage_date, requests, updated_at) VALUES (?, '2020-01-01', 1, ?)",
            (user_id, OLD),
        )
        connection.execute(
            "INSERT INTO troika_inbox_messages "
            "(id, user_id, kind, category, title, body, reason, project_id, task_id, "
            "available_at, delivered_at, requires_approval, idempotency_key, created_at) "
            "VALUES (?, ?, 'follow_up', 'progress', 'Fresh', 'Fresh', 'Fresh', ?, ?, ?, ?, 0, ?, ?)",
            (
                f"msg_fresh_{suffix}", user_id, fresh_project.id, fresh_task.id,
                NOW - 1, NOW - 1, f"inbox-fresh-{suffix}", NOW - 1,
            ),
        )
        connection.execute(
            "INSERT INTO troika_inbox_messages "
            "(id, user_id, kind, category, title, body, reason, available_at, "
            "delivered_at, requires_approval, idempotency_key, created_at) "
            "VALUES (?, ?, 'reminder', 'deadline', 'Pending old', 'Old', 'Old', "
            "?, NULL, 0, ?, ?)",
            (f"msg_pending_{suffix}", user_id, OLD, f"pending-{suffix}", OLD),
        )
        recent_usage_date = datetime.fromtimestamp(
            NOW - 86_400, timezone.utc
        ).date().isoformat()
        connection.execute(
            "INSERT INTO troika_usage_daily "
            "(user_id, usage_date, requests, updated_at) VALUES (?, ?, 1, ?)",
            (user_id, recent_usage_date, NOW - 1),
        )
        connection.execute(
            "INSERT INTO troika_audit_events "
            "(occurred_at, event_type, user_id, device_id, details_json) "
            "VALUES (?, 'test.old', ?, ?, '{}')",
            (OLD, user_id, device_id),
        )
        connection.execute(
            "INSERT INTO troika_audit_events "
            "(occurred_at, event_type, user_id, device_id, details_json) "
            "VALUES (?, 'test.fresh', ?, ?, '{}')",
            (NOW - 1, user_id, device_id),
        )
        connection.execute(
            "UPDATE troika_vision_sessions SET expires_at = ?, consumed_at = ?, "
            "status = 'consumed' WHERE id = ? AND user_id = ?",
            (OLD, OLD, grant.session_id, user_id),
        )
        connection.execute(
            "UPDATE troika_api_tokens SET revoked_at = ? WHERE id = ?",
            (OLD, revoked_principal.token_id),
        )
        connection.execute(
            "UPDATE troika_devices SET status = 'revoked', revoked_at = ? "
            "WHERE id = ? AND user_id = ?",
            (OLD, revoked_device, user_id),
        )
    with sqlite3.connect(sessions.db_path) as connection:
        connection.execute(
            "UPDATE sessions SET started_at = ? WHERE id = ?", (OLD, old_session)
        )
        connection.execute(
            "UPDATE sessions SET started_at = ? WHERE id = ?",
            (NOW - 1, fresh_session),
        )

    return {
        "user_id": user_id,
        "principal": principal,
        "scope": scope,
        "old_memory": old_memory.id,
        "fresh_memory": fresh_memory.id,
        "old_artifact": old_artifact.id,
        "fresh_artifact": fresh_artifact.id,
        "old_session": old_session,
        "fresh_session": fresh_session,
        "transcript": transcript,
        "project": project.id,
        "task": task.id,
        "note": note["id"],
        "fresh_project": fresh_project.id,
        "fresh_task": fresh_task.id,
        "fresh_note": fresh_note["id"],
        "vision": grant.session_id,
        "fresh_vision": fresh_grant.session_id,
        "revoked_device": revoked_device,
        "revoked_token": revoked_principal.token_id,
    }


def test_retention_dry_run_and_apply_are_owner_scoped(tmp_path, monkeypatch):
    database = tmp_path / "access.db"
    registry = AccessRegistry(database)
    artifacts = ArtifactStore(database, tmp_path / "artifacts")
    proactive = ProactiveStore(database)
    memories = MemoryStore(database)
    vision = VisionSessionStore(database)
    sessions = SessionDB(tmp_path / "state.db")
    sessions_dir = tmp_path / "sessions"

    monkeypatch.setattr(location_tool, "_cache_file", lambda: tmp_path / "device_context.json")
    monkeypatch.setattr(location_tool, "_db_path", lambda: tmp_path / "locations.db")
    location_tool._DEVICE_CONTEXT_CACHE.clear()
    location_tool._DEVICE_CONTEXT_RECEIVED_AT.clear()

    first = _seed_owner(
        registry, artifacts, sessions, proactive, memories, vision,
        email="first@example.com", sessions_dir=sessions_dir,
    )
    second = _seed_owner(
        registry, artifacts, sessions, proactive, memories, vision,
        email="second@example.com", sessions_dir=sessions_dir,
    )
    worker = RetentionWorker(
        registry,
        artifact_store=artifacts,
        session_db=sessions,
        sessions_dir=sessions_dir,
    )

    preview = worker.run(now=NOW, dry_run=True, user_id=first["user_id"])
    assert preview.failures == []
    assert preview.counts["memories"] == 1
    assert preview.counts["artifacts"] == 1
    assert preview.counts["conversations"] == 1
    assert preview.counts["saved_locations"] == 1
    assert preview.object_storage_purge_verified is False
    assert preview.backup_deletion_verified is False
    assert artifacts.read_for_user(first["user_id"], first["old_artifact"])
    assert first["transcript"].exists()

    applied = worker.run(now=NOW, dry_run=False, user_id=first["user_id"])
    assert applied.failures == []
    assert applied.owner_count == 1
    assert artifacts.read_for_user(first["user_id"], first["old_artifact"]) is None
    assert artifacts.read_for_user(first["user_id"], first["fresh_artifact"])
    assert sessions.get_session(first["old_session"]) is None
    assert not first["transcript"].exists()
    assert location_tool.get_device_context(first["scope"]) == {}

    first_export = registry.export_account_rows(first["principal"])
    assert [item["id"] for item in first_export["memories"]] == [first["fresh_memory"]]
    assert [item["id"] for item in first_export["artifacts"]] == [first["fresh_artifact"]]
    assert [item["id"] for item in first_export["projects"]] == [first["fresh_project"]]
    assert [item["id"] for item in first_export["tasks"]] == [first["fresh_task"]]
    assert [item["id"] for item in first_export["notes"]] == [first["fresh_note"]]
    assert [item["title"] for item in first_export["inbox_messages"]] == ["Fresh"]
    assert [item["id"] for item in first_export["vision_sessions"]] == [first["fresh_vision"]]
    assert sessions.get_session(first["fresh_session"]) is not None
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM troika_usage_daily WHERE user_id = ?",
            (first["user_id"],),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM troika_audit_events "
            "WHERE user_id = ? AND event_type = 'test.fresh'",
            (first["user_id"],),
        ).fetchone()[0] == 1
    location_connection = location_tool._conn()
    try:
        assert location_connection.execute(
            "SELECT name FROM locations WHERE session_key = ? ORDER BY name",
            (first["scope"],),
        ).fetchall() == [("fresh-place",)]
    finally:
        location_connection.close()
    retired = next(
        item for item in first_export["devices"] if item["id"] == first["revoked_device"]
    )
    assert retired["name"] == ""
    assert retired["platform"] == ""
    assert retired["status"] == "purged"
    assert first["revoked_token"] not in {item["id"] for item in first_export["tokens"]}

    second_export = registry.export_account_rows(second["principal"])
    assert second["old_memory"] in {item["id"] for item in second_export["memories"]}
    assert second["old_artifact"] in {item["id"] for item in second_export["artifacts"]}
    assert second["project"] in {item["id"] for item in second_export["projects"]}
    assert sessions.get_session(second["old_session"]) is not None
    assert second["transcript"].exists()
    assert location_tool.get_device_context(second["scope"])["ssid"] == "second@example.com"


def test_api_server_starts_and_stops_automatic_retention(tmp_path):
    async def scenario():
        adapter = APIServerAdapter(
            PlatformConfig(
                enabled=True,
                extra={
                    "product_auth_enabled": True,
                    "product_auth_db": str(tmp_path / "access.db"),
                    "product_artifact_root": str(tmp_path / "artifacts"),
                    "product_retention_enabled": True,
                    "product_retention_dry_run": True,
                    "host": "127.0.0.1",
                    "port": 0,
                },
            )
        )
        with patch("tools.job_runner.cleanup_orphan_jobs", return_value=0), patch(
            "tools.job_runner.ensure_watchdog_started"
        ):
            assert await adapter.connect()
        try:
            assert adapter._retention_task is not None
            deadline = time.monotonic() + 3
            while adapter._retention_last_report is None and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            assert adapter._retention_last_report is not None
            assert adapter._retention_last_report["dry_run"] is True
        finally:
            await adapter.disconnect()
        assert adapter._retention_task is None

    asyncio.run(scenario())
