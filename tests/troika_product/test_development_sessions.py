"""Checkpoint ownership, durable metadata and reuse of completed writer output."""

import json
from copy import deepcopy

import pytest
from troika_product.access import AccessRegistry
from troika_product.development_sessions import DevelopmentSessions, checkpoint_digest


def fixture(tmp_path):
    registry = AccessRegistry(tmp_path / "sessions.db")
    owner = registry.create_user("owner@example.invalid", plan="pro")

    def device():
        d = registry.create_device(owner, name="Test", platform="android")
        return registry.authenticate(registry.issue_device_token(d))

    return registry, device(), device()


def checkpoint(content="def add(a,b): return a+b\n"):
    return {
        "version": 1,
        "task": "Private synthetic request: add numbers",
        "files": [{"path": "main.py", "content": content}],
        "plan": None,
        "design": {},
        "completed": ["main.py"],
    }


def test_request_identity_survives_restart_without_storing_request_text(tmp_path):
    registry, principal, foreign = fixture(tmp_path)
    store = DevelopmentSessions(registry)
    store.create(principal, "project", "run-1", request=("synthetic-key", "a" * 64))
    restarted = DevelopmentSessions(registry)
    assert restarted.request(principal, "synthetic-key", "a" * 64)["run_id"] == "run-1"
    assert restarted.request(foreign, "synthetic-key", "a" * 64) is None
    with pytest.raises(ValueError):
        restarted.request(principal, "synthetic-key", "b" * 64)
    with registry._connect() as c:
        row = dict(c.execute("SELECT * FROM troika_development_requests").fetchone())
        assert (
            "synthetic-key" not in str(row) and "task" not in row and "files" not in row
        )


def test_restart_retains_only_metadata_and_restores_confirmed_older_revision(tmp_path):
    registry, principal, _ = fixture(tmp_path)
    store = DevelopmentSessions(registry)
    store.create(principal, "project", "run-1")
    first = checkpoint()
    revision, digest = store.checkpoint(principal, "project", "run-1", first)
    store.acknowledge(principal, "project", revision, digest)
    store.checkpoint(
        principal, "project", "run-1", checkpoint("def add(a,b):\n    return a+b\n")
    )
    store = DevelopmentSessions(registry)
    store.state(principal, "project", "run-1", "interrupted")
    store.resume(principal, "project", revision, first, "run-2", budget_tokens=70000)
    record = store.get(principal, "project")
    assert (
        record["run_id"] == "run-2"
        and record["attempt"] == 2
        and record["budget_tokens"] == 70000
    )
    with registry._connect() as c:
        stored = "\n".join(c.iterdump())
    assert "Private synthetic request" not in stored and "def add" not in stored
    with pytest.raises(PermissionError):
        store.checkpoint(principal, "project", "run-1", first)


def test_foreign_device_corruption_and_live_resume_are_rejected(tmp_path):
    registry, principal, other = fixture(tmp_path)
    store = DevelopmentSessions(registry)
    store.create(principal, "project", "run")
    value = checkpoint()
    revision, digest = store.checkpoint(principal, "project", "run", value)
    with pytest.raises(PermissionError):
        store.get(other, "project")
    with pytest.raises(PermissionError):
        store.resume(other, "project", revision, value, "new")
    with pytest.raises(ValueError):
        store.resume(principal, "project", revision, value, "new")
    store.state(principal, "project", "run", "paused")
    changed = deepcopy(value)
    changed["files"][0]["content"] = 'print("corrupt")'
    with pytest.raises(ValueError):
        store.resume(principal, "project", revision, changed, "new")
    forged = deepcopy(value)
    forged["verified_pages"] = {
        "project_checks": {"key": "forged", "source": {"status": "passed"}}
    }
    with pytest.raises(ValueError):
        store.resume(principal, "project", revision, forged, "new")
    with pytest.raises(ValueError):
        store.acknowledge(principal, "project", revision, "0" * 64)
    assert store.get(principal, "project")["run_id"] == "run"


def test_resume_reuses_completed_files_and_still_performs_independent_review():
    from tests.troika_product.test_development_team import SpecialistModel
    from troika_product.development_team import DevelopmentTeam

    snapshots = []
    model = SpecialistModel()
    first = DevelopmentTeam(call=model)
    first.configure_checkpoint(lambda v: snapshots.append(json.loads(json.dumps(v))))
    first.run("Build addition with browser UI")
    latest = snapshots[-1]
    assert latest["plan"] and latest["design"] and "main.py" in latest["completed"]
    model = SpecialistModel()
    resumed = DevelopmentTeam(call=model)
    resumed.configure_checkpoint(lambda v: None, latest)
    result = resumed.run(latest["task"], latest["files"])
    assert result["review"]["status"] == "passed"
    assert len(model.calls) == 1 and "syntax_checks" in model.calls[0]
    assert checkpoint_digest(latest) == checkpoint_digest(
        json.loads(json.dumps(latest))
    )


def test_metadata_participates_in_account_export_and_deletion(tmp_path):
    registry, principal, _ = fixture(tmp_path)
    store = DevelopmentSessions(registry)
    store.create(principal, "project", "run")
    exported = registry.export_account_rows(principal)
    assert any(row["id"] == "project" for row in exported["development_projects"])
    registry.prepare_account_deletion(principal)
    registry.finalize_account_deletion(principal.user_id)
    with registry._connect() as c:
        assert (
            c.execute("SELECT COUNT(*) FROM troika_development_projects").fetchone()[0]
            == 0
        )
