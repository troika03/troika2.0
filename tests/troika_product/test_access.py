"""Tests for the closed-beta user and device access registry."""

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
