"""Short-lived, device-bound authorization for product vision captures."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import secrets
import sqlite3
import time
import uuid

from troika_product.access import AccessPrincipal


@dataclass(frozen=True)
class VisionSessionGrant:
    """One-time values sent to the already authenticated product device."""

    session_id: str
    nonce: str
    expires_at: float
    capability: str


class VisionSessionStore:
    """Persist metadata only; raw frames and clear-text nonces never enter SQLite."""

    MAX_TTL_SECONDS = 120

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS troika_vision_sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES troika_users(id),
                    device_id TEXT NOT NULL REFERENCES troika_devices(id),
                    token_id TEXT NOT NULL REFERENCES troika_api_tokens(id),
                    capability TEXT NOT NULL,
                    nonce_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL,
                    consumed_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_troika_vision_session_owner
                    ON troika_vision_sessions(user_id, device_id, status, expires_at);
                """
            )

    @staticmethod
    def _digest(value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _valid_capability(value: str) -> bool:
        return value == "screen.snapshot"

    def create(
        self,
        principal: AccessPrincipal,
        *,
        capability: str = "screen.snapshot",
        ttl_seconds: int = MAX_TTL_SECONDS,
        now: float | None = None,
    ) -> VisionSessionGrant:
        """Create one active grant after rechecking token and device ownership."""
        if not self._valid_capability(capability):
            raise ValueError("unsupported vision capability")
        if isinstance(ttl_seconds, bool) or not 1 <= int(ttl_seconds) <= self.MAX_TTL_SECONDS:
            raise ValueError("vision session TTL is out of range")
        current = time.time() if now is None else float(now)
        expires_at = current + int(ttl_seconds)
        session_id = f"vsn_{uuid.uuid4().hex}"
        nonce = secrets.token_urlsafe(32)

        with self._connect() as connection:
            owner = connection.execute(
                """
                SELECT t.id
                FROM troika_api_tokens AS t
                JOIN troika_devices AS d ON d.id = t.device_id
                JOIN troika_users AS u ON u.id = d.user_id
                WHERE t.id = ? AND d.id = ? AND u.id = ?
                  AND u.status = 'active' AND d.status = 'active'
                  AND t.revoked_at IS NULL
                  AND (t.expires_at IS NULL OR t.expires_at > ?)
                """,
                (principal.token_id, principal.device_id, principal.user_id, current),
            ).fetchone()
            if owner is None:
                raise PermissionError("product token or device is no longer active")
            connection.execute(
                """
                UPDATE troika_vision_sessions
                SET status = 'expired'
                WHERE status = 'active' AND expires_at <= ?
                """,
                (current,),
            )
            connection.execute(
                """
                INSERT INTO troika_vision_sessions
                    (id, user_id, device_id, token_id, capability, nonce_digest,
                     status, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    session_id,
                    principal.user_id,
                    principal.device_id,
                    principal.token_id,
                    capability,
                    self._digest(nonce),
                    current,
                    expires_at,
                ),
            )
        return VisionSessionGrant(session_id, nonce, expires_at, capability)

    def consume(
        self,
        principal: AccessPrincipal,
        *,
        session_id: str,
        nonce: str,
        capability: str = "screen.snapshot",
        now: float | None = None,
    ) -> bool:
        """Atomically consume a grant once for its original user and device."""
        if not session_id or not nonce or not self._valid_capability(capability):
            return False
        current = time.time() if now is None else float(now)
        with self._connect() as connection:
            connection.execute(
                "UPDATE troika_vision_sessions SET status = 'expired' "
                "WHERE status = 'active' AND expires_at <= ?",
                (current,),
            )
            cursor = connection.execute(
                """
                UPDATE troika_vision_sessions
                SET status = 'consumed', consumed_at = ?
                WHERE id = ? AND user_id = ? AND device_id = ? AND token_id = ?
                  AND capability = ? AND nonce_digest = ?
                  AND status = 'active' AND expires_at > ?
                  AND EXISTS (
                    SELECT 1
                    FROM troika_api_tokens AS t
                    JOIN troika_devices AS d ON d.id = t.device_id
                    JOIN troika_users AS u ON u.id = d.user_id
                    WHERE t.id = troika_vision_sessions.token_id
                      AND d.id = troika_vision_sessions.device_id
                      AND u.id = troika_vision_sessions.user_id
                      AND u.status = 'active' AND d.status = 'active'
                      AND t.revoked_at IS NULL
                      AND (t.expires_at IS NULL OR t.expires_at > ?)
                  )
                """,
                (
                    current,
                    session_id,
                    principal.user_id,
                    principal.device_id,
                    principal.token_id,
                    capability,
                    self._digest(nonce),
                    current,
                    current,
                ),
            )
            return cursor.rowcount == 1

    def cancel(self, principal: AccessPrincipal, session_id: str) -> None:
        """Close an unused grant without exposing whether another owner has it."""
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE troika_vision_sessions SET status = 'cancelled'
                WHERE id = ? AND user_id = ? AND device_id = ? AND token_id = ?
                  AND status = 'active'
                """,
                (
                    session_id,
                    principal.user_id,
                    principal.device_id,
                    principal.token_id,
                ),
            )
