"""Tests for the closed-beta user and device access registry."""

from datetime import datetime, timezone
import json

from troika_product.access import AccessRegistry
from troika_product.__main__ import main


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
    assert event.session_digest is not None and "private-session" not in event.session_digest
    assert event.run_digest is not None and "run_private" not in event.run_digest
    assert event.details == {"endpoint": "runs", "remaining": 49}

    try:
        registry.record_audit_event("request.accepted", details={"prompt": "secret"})
    except ValueError:
        pass
    else:
        raise AssertionError("audit records must reject message-like fields")


def test_audit_command_shows_only_privacy_safe_fields(tmp_path, monkeypatch, capsys) -> None:
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
