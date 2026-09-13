import sqlite3

from troika_product.access import AccessRegistry
from troika_product.vision_sessions import VisionSessionStore


def _principal(registry: AccessRegistry, email: str):
    user_id = registry.create_user(email)
    device_id = registry.create_device(user_id, name="Phone", platform="android")
    token = registry.issue_device_token(device_id)
    principal = registry.authenticate(token)
    assert principal is not None
    return principal


def test_vision_session_is_owner_bound_single_use_and_metadata_only(tmp_path):
    database = tmp_path / "access.db"
    access = AccessRegistry(database)
    owner = _principal(access, "owner@example.com")
    stranger = _principal(access, "stranger@example.com")
    sessions = VisionSessionStore(database)

    grant = sessions.create(owner, now=1000, ttl_seconds=60)

    assert not sessions.consume(
        stranger, session_id=grant.session_id, nonce=grant.nonce, now=1001
    )
    assert not sessions.consume(
        owner, session_id=grant.session_id, nonce="wrong", now=1001
    )
    assert sessions.consume(
        owner, session_id=grant.session_id, nonce=grant.nonce, now=1001
    )
    assert not sessions.consume(
        owner, session_id=grant.session_id, nonce=grant.nonce, now=1002
    )

    with sqlite3.connect(database) as connection:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(troika_vision_sessions)")
        }
        stored = connection.execute(
            "SELECT nonce_digest, status FROM troika_vision_sessions WHERE id = ?",
            (grant.session_id,),
        ).fetchone()
    assert "image" not in columns
    assert "frame" not in columns
    assert "nonce" not in columns
    assert stored is not None
    assert grant.nonce not in stored[0]
    assert stored[1] == "consumed"


def test_vision_session_rejects_expired_and_revoked_grants(tmp_path):
    database = tmp_path / "access.db"
    access = AccessRegistry(database)
    owner = _principal(access, "owner@example.com")
    sessions = VisionSessionStore(database)

    expired = sessions.create(owner, now=1000, ttl_seconds=10)
    assert not sessions.consume(
        owner, session_id=expired.session_id, nonce=expired.nonce, now=1011
    )

    active = sessions.create(owner, now=2000, ttl_seconds=60)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE troika_api_tokens SET revoked_at = ? WHERE id = ?",
            (2001, owner.token_id),
        )
    assert not sessions.consume(
        owner, session_id=active.session_id, nonce=active.nonce, now=2002
    )
