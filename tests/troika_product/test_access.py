"""Tests for the closed-beta user and device access registry."""

from datetime import datetime, timezone
import json

from troika_product.access import AccessRegistry
from troika_product.__main__ import main


def test_self_registration_stores_a_hash_and_authenticates(tmp_path) -> None:
    database = tmp_path / "access.db"
    registry = AccessRegistry(database)
    user_id = registry.register_account("New@Example.com", "safe-password-123")

    assert (
        registry.authenticate_password("new@example.com", "safe-password-123")
        == user_id
    )
    assert registry.authenticate_password("new@example.com", "wrong-password") is None

    import sqlite3

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT email, password_salt, password_digest FROM troika_users WHERE id = ?",
            (user_id,),
        ).fetchone()
    assert row is not None
    assert row[0] == "new@example.com"
    assert row[1] and row[2]
    assert "safe-password-123" not in row


def test_self_registration_rejects_duplicate_email(tmp_path) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    registry.register_account("new@example.com", "safe-password-123")
    try:
        registry.register_account("NEW@example.com", "another-password-123")
    except ValueError as exc:
        assert "already exists" in str(exc)
    else:
        raise AssertionError("duplicate registration must fail")


def test_token_authentication_and_revocation(tmp_path) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    user_id = registry.create_user("one@example.com")
    device_id = registry.create_device(user_id, name="Pixel", platform="android")
    token = registry.issue_device_token(device_id)

    principal = registry.authenticate(token)
    assert principal is not None
    assert principal.user_id == user_id
    assert principal.device_id == device_id
    assert registry.revoke_token(token)
    assert registry.authenticate(token) is None


def test_device_management_is_owner_scoped_and_revokes_all_device_tokens(
    tmp_path,
) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    first_user = registry.create_user("one@example.com")
    second_user = registry.create_user("two@example.com")
    current_device = registry.create_device(
        first_user, name="Pixel", platform="android"
    )
    other_device = registry.create_device(
        first_user, name="Laptop", platform="windows"
    )
    foreign_device = registry.create_device(
        second_user, name="iPhone", platform="ios"
    )
    current_token = registry.issue_device_token(current_device)
    other_token = registry.issue_device_token(other_device)
    other_second_token = registry.issue_device_token(other_device)
    foreign_token = registry.issue_device_token(foreign_device)
    principal = registry.authenticate(current_token)
    assert principal is not None

    devices = registry.list_devices(principal)
    assert {device.id for device in devices} == {current_device, other_device}
    assert next(device for device in devices if device.id == current_device).current
    assert not next(device for device in devices if device.id == other_device).current

    assert not registry.revoke_device(principal, foreign_device)
    assert registry.authenticate(foreign_token) is not None
    assert registry.revoke_device(principal, other_device)
    assert registry.authenticate(other_token) is None
    assert registry.authenticate(other_second_token) is None
    assert registry.authenticate(current_token) == principal
    assert next(
        device for device in registry.list_devices(principal) if device.id == other_device
    ).status == "revoked"


def test_logout_all_revokes_every_owned_device_but_not_foreign_account(
    tmp_path,
) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    owner = registry.create_user("owner@example.com")
    foreign = registry.create_user("foreign@example.com")
    first_device = registry.create_device(owner, name="Pixel", platform="android")
    second_device = registry.create_device(owner, name="PC", platform="windows")
    foreign_device = registry.create_device(
        foreign, name="iPhone", platform="ios"
    )
    first_token = registry.issue_device_token(first_device)
    second_token = registry.issue_device_token(second_device)
    foreign_token = registry.issue_device_token(foreign_device)
    principal = registry.authenticate(first_token)
    assert principal is not None

    assert set(registry.revoke_all_devices(principal)) == {
        first_device,
        second_device,
    }
    assert registry.authenticate(first_token) is None
    assert registry.authenticate(second_token) is None
    assert registry.authenticate(foreign_token) is not None


def test_session_claims_are_isolated_between_users(tmp_path) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    first_user = registry.create_user("one@example.com")
    second_user = registry.create_user("two@example.com")
    first_token = registry.issue_device_token(
        registry.create_device(first_user, name="Pixel", platform="android")
    )
    second_token = registry.issue_device_token(
        registry.create_device(second_user, name="iPhone", platform="ios")
    )
    first = registry.authenticate(first_token)
    second = registry.authenticate(second_token)
    assert first is not None and second is not None

    assert registry.claim_session(first, "private-session")
    assert not registry.claim_session(second, "private-session")
    assert registry.session_belongs_to(first, "private-session")
    assert not registry.session_belongs_to(second, "private-session")


def test_daily_quota_is_atomic_per_user_and_resets_each_utc_day(tmp_path) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    user_id = registry.create_user("one@example.com", daily_request_limit=2)
    token = registry.issue_device_token(
        registry.create_device(user_id, name="Pixel", platform="android")
    )
    principal = registry.authenticate(token)
    assert principal is not None

    first_day = datetime(2026, 9, 9, 23, 55, tzinfo=timezone.utc)
    first = registry.consume_chat_request(principal, now=first_day)
    second = registry.consume_chat_request(principal, now=first_day)
    rejected = registry.consume_chat_request(principal, now=first_day)

    assert (first.allowed, first.used, first.remaining) == (True, 1, 1)
    assert (second.allowed, second.used, second.remaining) == (True, 2, 0)
    assert (rejected.allowed, rejected.used, rejected.remaining) == (False, 2, 0)
    assert registry.daily_usage(user_id, now=first_day) == 2

    next_day = registry.consume_chat_request(
        principal, now=datetime(2026, 9, 10, 0, 1, tzinfo=timezone.utc)
    )
    assert (next_day.allowed, next_day.used, next_day.remaining) == (True, 1, 1)


def test_operator_can_change_user_plan_and_limit(tmp_path) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    user_id = registry.create_user("one@example.com")
    registry.set_entitlement(user_id, plan="pro", daily_request_limit=200)
    token = registry.issue_device_token(
        registry.create_device(user_id, name="Pixel", platform="android")
    )
    principal = registry.authenticate(token)
    assert principal is not None
    decision = registry.consume_chat_request(principal)
    assert (decision.limit, decision.remaining) == (200, 199)


def test_subscription_summary_is_owner_scoped_and_reports_current_usage(
    tmp_path,
) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    user_id = registry.create_user(
        "one@example.com", plan="plus", daily_request_limit=5
    )
    token = registry.issue_device_token(
        registry.create_device(user_id, name="Pixel", platform="android")
    )
    principal = registry.authenticate(token)
    assert principal is not None
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

    registry.consume_chat_request(principal, now=now)
    summary = registry.subscription_summary(principal, now=now)

    assert summary == {
        "plan": "plus",
        "status": "active",
        "usage_date": "2026-09-24",
        "daily_limit": 5,
        "used": 1,
        "remaining": 4,
        "updated_at": summary["updated_at"],
    }


def test_audit_log_has_no_raw_session_or_prompt_content(tmp_path) -> None:
    registry = AccessRegistry(tmp_path / "access.db")
    user_id = registry.create_user("one@example.com")
    token = registry.issue_device_token(
        registry.create_device(user_id, name="Pixel", platform="android")
    )
    principal = registry.authenticate(token)
    assert principal is not None

    registry.record_audit_event(
        "request.accepted",
        principal=principal,
        session_id="private-session",
        run_id="run_private",
        details={"endpoint": "runs", "remaining": 49},
    )
    event = registry.list_audit_events(user_id)[0]
    assert event.event_type == "request.accepted"
    assert (
        event.session_digest is not None
        and "private-session" not in event.session_digest
    )
    assert event.run_digest is not None and "run_private" not in event.run_digest
    assert event.details == {"endpoint": "runs", "remaining": 49}

    try:
        registry.record_audit_event("request.accepted", details={"prompt": "secret"})
    except ValueError:
        pass
    else:
        raise AssertionError("audit records must reject message-like fields")


def test_audit_command_shows_only_privacy_safe_fields(
    tmp_path, monkeypatch, capsys
) -> None:
    database = tmp_path / "access.db"
    registry = AccessRegistry(database)
    user_id = registry.create_user("one@example.com")
    registry.record_audit_event("user.provisioned", details={"source": "operator"})
    registry.record_audit_event(
        "request.accepted",
        principal=registry.authenticate(
            registry.issue_device_token(
                registry.create_device(user_id, name="Pixel", platform="android")
            )
        ),
        session_id="private-session",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "troika_product",
            "--database",
            str(database),
            "audit",
            "--user-id",
            user_id,
        ],
    )

    assert main() == 0
    output = capsys.readouterr().out
    row = json.loads(output)
    assert row["event_type"] == "request.accepted"
    assert row["session_digest"] is not None
    assert "private-session" not in output


def test_provision_command_prints_a_device_token(tmp_path, monkeypatch, capsys) -> None:
    database = tmp_path / "access.db"
    monkeypatch.setattr(
        "sys.argv",
        [
            "troika_product",
            "--database",
            str(database),
            "provision",
            "--email",
            "beta@example.com",
            "--device-name",
            "Beta Pixel",
            "--platform",
            "android",
        ],
    )

    assert main() == 0
    assert "token=trk_live_" in capsys.readouterr().out
