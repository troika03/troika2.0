"""Consent, ownership, persistence, and local-time delivery policy checks."""

from dataclasses import replace
from datetime import datetime, timezone
import json
import sqlite3

import pytest

from troika_product.access import AccessRegistry
from troika_product.notifications import NotificationPreferences


def _identity(registry, email):
    user = registry.create_user(email)
    device = registry.create_device(user, name="Test", platform="android")
    token = registry.issue_device_token(device)
    return registry.authenticate(token), token


def test_settings_are_account_scoped_persistent_and_opt_in(tmp_path):
    registry = AccessRegistry(tmp_path / "access.db")
    first, _ = _identity(registry, "one@example.com")
    second, _ = _identity(registry, "two@example.com")
    sibling_token = registry.issue_device_token(
        registry.create_device(first.user_id, name="Tablet", platform="android")
    )
    sibling = registry.authenticate(sibling_token)
    assert registry.notification_preferences(first) == NotificationPreferences()
    assert not registry.notification_preferences(first).allows_delivery("reminder")
    assert not registry.notification_preferences(first).allows_delivery("proactive")

    settings = NotificationPreferences(reminders_enabled=True, timezone="Europe/Moscow")
    registry.set_notification_preferences(first, settings)
    reopened = AccessRegistry(registry.database_path)
    assert reopened.notification_preferences(first) == settings
    assert reopened.notification_preferences(sibling) == settings
    assert reopened.notification_preferences(second) == NotificationPreferences()
    assert not settings.allows_delivery("proactive")
    registry.set_notification_preferences(sibling, NotificationPreferences())
    assert not registry.notification_preferences(first).allows_delivery("reminder")


def test_stale_or_forged_identity_cannot_read_or_change_preferences(tmp_path):
    registry = AccessRegistry(tmp_path / "access.db")
    first, token = _identity(registry, "one@example.com")
    second, _ = _identity(registry, "two@example.com")
    forged = replace(first, user_id=second.user_id)
    registry.revoke_token(token)
    for identity in (first, forged):
        with pytest.raises(PermissionError):
            registry.notification_preferences(identity)
        with pytest.raises(PermissionError):
            registry.set_notification_preferences(identity, NotificationPreferences())
    assert registry.list_audit_events(first.user_id) == []
    assert registry.list_audit_events(second.user_id) == []


def test_consent_audit_is_private_and_atomic(tmp_path):
    registry = AccessRegistry(tmp_path / "access.db")
    principal, token = _identity(registry, "one@example.com")
    settings = NotificationPreferences(reminders_enabled=True, timezone="Europe/Moscow")
    registry.set_notification_preferences(principal, settings)
    event = registry.list_audit_events(principal.user_id)[0]
    assert event.event_type == "notifications.preferences_updated"
    assert event.device_id == principal.device_id
    assert event.details == {
        "reminders_enabled": True, "proactive_enabled": False, "quiet_hours_enabled": False,
    }
    assert "Europe/Moscow" not in json.dumps(event.details)
    assert token not in json.dumps(event.details)
    with sqlite3.connect(registry.database_path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_audit BEFORE INSERT ON troika_audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        registry.set_notification_preferences(principal, NotificationPreferences())
    assert registry.notification_preferences(principal) == settings


@pytest.mark.parametrize("key,value", [
    ("reminders_enabled", "false"), ("proactive_enabled", 1),
    ("quiet_hours_enabled", None), ("timezone", "../etc/passwd"),
    ("timezone", "Mars/Olympus"), ("timezone", []),
    ("quiet_start", "24:00"), ("quiet_start", "9:00"),
    ("quiet_end", "08:60"), ("quiet_end", "22:00"),
])
def test_invalid_preferences_are_rejected(key, value):
    data = NotificationPreferences().to_dict()
    data[key] = value
    with pytest.raises(ValueError):
        NotificationPreferences.from_dict(data)


@pytest.mark.parametrize("data", [None, [], {}, {"reminders_enabled": True}])
def test_partial_updates_never_silently_reset_consent(data):
    with pytest.raises(ValueError):
        NotificationPreferences.from_dict(data)


@pytest.mark.parametrize("utc,allowed", [
    ("2026-09-10T18:59:59+00:00", True),  # Moscow 21:59:59
    ("2026-09-10T19:00:00+00:00", False),  # Start inclusive
    ("2026-09-11T00:00:00+00:00", False),
    ("2026-09-11T04:59:59+00:00", False),
    ("2026-09-11T05:00:00+00:00", True),  # End exclusive
])
def test_quiet_hours_cross_midnight_in_user_timezone(utc, allowed):
    settings = NotificationPreferences(
        reminders_enabled=True, proactive_enabled=True,
        quiet_hours_enabled=True, timezone="Europe/Moscow",
    )
    for kind in ("reminder", "proactive"):
        assert settings.allows_delivery(kind, now=datetime.fromisoformat(utc)) is allowed


@pytest.mark.parametrize("hour,allowed", [(8, True), (9, False), (12, False), (17, True)])
def test_daytime_quiet_hours(hour, allowed):
    settings = NotificationPreferences(
        reminders_enabled=True, quiet_hours_enabled=True, quiet_start="09:00", quiet_end="17:00",
    )
    assert settings.allows_delivery(
        "reminder", now=datetime(2026, 9, 10, hour, tzinfo=timezone.utc),
    ) is allowed


@pytest.mark.parametrize("utc,allowed", [
    ("2026-11-01T05:30:00+00:00", False),  # First 01:30, EDT
    ("2026-11-01T06:30:00+00:00", False),  # Repeated 01:30, EST
    ("2026-11-01T07:00:00+00:00", True),
    ("2026-03-08T06:59:00+00:00", False),  # 01:59 before spring-forward
    ("2026-03-08T07:00:00+00:00", True),  # 03:00 after the missing hour
])
def test_dst_transitions_evaluate_real_instants(utc, allowed):
    settings = NotificationPreferences(
        reminders_enabled=True, quiet_hours_enabled=True,
        timezone="America/New_York", quiet_start="01:00", quiet_end="02:00",
    )
    assert settings.allows_delivery("reminder", now=datetime.fromisoformat(utc)) is allowed


def test_disabled_quiet_hours_and_invalid_delivery_inputs():
    settings = NotificationPreferences(reminders_enabled=True)
    assert settings.allows_delivery("reminder", now=datetime(2026, 9, 10, 23, tzinfo=timezone.utc))
    with pytest.raises(ValueError):
        settings.allows_delivery("reminder", now=datetime(2026, 9, 10))
    with pytest.raises(ValueError):
        settings.allows_delivery("unknown")
