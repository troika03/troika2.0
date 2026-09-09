"""Local access registry for Troika users, devices, and bearer tokens.

The registry is deliberately dependency-free so a private beta can be run on
the existing Hermes gateway before the hosted identity/billing services are
introduced.  It stores only SHA-256 digests of high-entropy bearer tokens;
the clear-text token is returned exactly once when it is issued.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import secrets
import sqlite3
import time
import uuid
from typing import Optional

from hermes_constants import get_hermes_home


@dataclass(frozen=True)
class AccessPrincipal:
    """Authenticated product identity without any clear-text credentials."""

    user_id: str
    device_id: str
    token_id: str

    @property
    def memory_scope(self) -> str:
        """Stable opaque scope for memory and device-context storage."""
        return f"troika:{self.user_id}:{self.device_id}"


class AccessRegistry:
    """SQLite-backed registry for beta access and device-bound API tokens."""

    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or get_hermes_home() / "troika_access.db"
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
                CREATE TABLE IF NOT EXISTS troika_users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS troika_devices (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES troika_users(id),
                    name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS troika_api_tokens (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL REFERENCES troika_devices(id),
                    token_digest TEXT NOT NULL UNIQUE,
                    expires_at REAL,
                    revoked_at REAL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS troika_sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES troika_users(id),
                    device_id TEXT NOT NULL REFERENCES troika_devices(id),
                    created_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_troika_devices_user
                    ON troika_devices(user_id);
                CREATE INDEX IF NOT EXISTS idx_troika_tokens_device
                    ON troika_api_tokens(device_id);
                CREATE INDEX IF NOT EXISTS idx_troika_sessions_user
                    ON troika_sessions(user_id);
                """
            )

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _token_digest(token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = email.strip().lower()
        if not normalized or "@" not in normalized or len(normalized) > 254:
            raise ValueError("a valid email address is required")
        return normalized

    def create_user(self, email: str) -> str:
        """Create an active beta user and return its opaque ID."""
        user_id = self._new_id("usr")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO troika_users (id, email, created_at) VALUES (?, ?, ?)",
                (user_id, self._normalize_email(email), time.time()),
            )
        return user_id

    def create_device(self, user_id: str, *, name: str, platform: str) -> str:
        """Register one device for an active user."""
        clean_name = name.strip()[:120]
        clean_platform = platform.strip().lower()[:40]
        if not clean_name or not clean_platform:
            raise ValueError("device name and platform are required")
        with self._connect() as connection:
            user = connection.execute(
                "SELECT status FROM troika_users WHERE id = ?", (user_id,)
            ).fetchone()
            if user is None or user["status"] != "active":
                raise ValueError("user is not active")
            device_id = self._new_id("dev")
            connection.execute(
                "INSERT INTO troika_devices (id, user_id, name, platform, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (device_id, user_id, clean_name, clean_platform, time.time()),
            )
        return device_id

    def issue_device_token(
        self, device_id: str, *, expires_at: Optional[float] = None
    ) -> str:
        """Issue a high-entropy bearer token. Store only its digest."""
        token = f"trk_live_{secrets.token_urlsafe(32)}"
        with self._connect() as connection:
            device = connection.execute(
                "SELECT status FROM troika_devices WHERE id = ?", (device_id,)
            ).fetchone()
            if device is None or device["status"] != "active":
                raise ValueError("device is not active")
            connection.execute(
                "INSERT INTO troika_api_tokens "
                "(id, device_id, token_digest, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    self._new_id("tok"),
                    device_id,
                    self._token_digest(token),
                    expires_at,
                    time.time(),
                ),
            )
        return token

    def authenticate(self, token: str) -> Optional[AccessPrincipal]:
        """Return the active principal for a bearer token, if any."""
        if not isinstance(token, str) or not token.startswith("trk_live_"):
            return None
        now = time.time()
        digest = self._token_digest(token)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT tokens.id AS token_id, devices.id AS device_id, users.id AS user_id "
                "FROM troika_api_tokens AS tokens "
                "JOIN troika_devices AS devices ON devices.id = tokens.device_id "
                "JOIN troika_users AS users ON users.id = devices.user_id "
                "WHERE tokens.token_digest = ? "
                "AND tokens.revoked_at IS NULL "
                "AND (tokens.expires_at IS NULL OR tokens.expires_at > ?) "
                "AND devices.status = 'active' AND users.status = 'active'",
                (digest, now),
            ).fetchone()
        if row is None:
            return None
        return AccessPrincipal(
            user_id=row["user_id"], device_id=row["device_id"], token_id=row["token_id"]
        )

    def revoke_token(self, token: str) -> bool:
        """Revoke a token without retaining its clear-text form."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE troika_api_tokens SET revoked_at = ? "
                "WHERE token_digest = ? AND revoked_at IS NULL",
                (time.time(), self._token_digest(token)),
            )
        return cursor.rowcount == 1

    def claim_session(self, principal: AccessPrincipal, session_id: str) -> bool:
        """Atomically bind a session to its owner; reject cross-user access."""
        clean_session_id = session_id.strip()
        if (
            not clean_session_id
            or len(clean_session_id) > 200
            or any(char in clean_session_id for char in "\r\n\x00")
        ):
            return False
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT user_id, device_id FROM troika_sessions WHERE session_id = ?",
                (clean_session_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO troika_sessions (session_id, user_id, device_id, created_at) "
                    "VALUES (?, ?, ?, ?)",
                    (clean_session_id, principal.user_id, principal.device_id, time.time()),
                )
                return True
            return (
                existing["user_id"] == principal.user_id
                and existing["device_id"] == principal.device_id
            )

    def session_belongs_to(self, principal: AccessPrincipal, session_id: str) -> bool:
        """Check session ownership without creating a new mapping."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT user_id, device_id FROM troika_sessions WHERE session_id = ?",
                (session_id.strip(),),
            ).fetchone()
        return bool(
            row
            and row["user_id"] == principal.user_id
            and row["device_id"] == principal.device_id
        )

    def user_session_ids(self, principal: AccessPrincipal) -> set[str]:
        """Return only the active user's server-side session IDs."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT session_id FROM troika_sessions WHERE user_id = ?",
                (principal.user_id,),
            ).fetchall()
        return {str(row["session_id"]) for row in rows}
