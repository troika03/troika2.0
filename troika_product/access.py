"""Local access registry for Troika users, devices, and bearer tokens.

The registry is deliberately dependency-free so a private beta can be run on
the existing Hermes gateway before the hosted identity/billing services are
introduced.  It stores only SHA-256 digests of high-entropy bearer tokens;
the clear-text token is returned exactly once when it is issued.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import scrypt, sha256
import json
from pathlib import Path
import secrets
import sqlite3
import time
import uuid
from typing import Optional

from hermes_constants import get_hermes_home
from troika_product.notifications import NotificationPreferences


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


@dataclass(frozen=True)
class UsageDecision:
    """The result of atomically reserving one request from a daily quota."""

    allowed: bool
    usage_date: str
    limit: int
    used: int
    remaining: int


@dataclass(frozen=True)
class AuditEvent:
    """Append-only product audit entry with no prompts, tokens, or raw IDs."""

    id: int
    occurred_at: float
    event_type: str
    user_id: str | None
    device_id: str | None
    session_digest: str | None
    run_digest: str | None
    details: dict[str, str | int | float | bool | None]


@dataclass(frozen=True)
class DeviceSummary:
    """Owner-visible device metadata with no credential material."""

    id: str
    name: str
    platform: str
    status: str
    created_at: float
    current: bool

    def to_dict(self) -> dict[str, str | float | bool]:
        return {
            "id": self.id,
            "name": self.name,
            "platform": self.platform,
            "status": self.status,
            "created_at": self.created_at,
            "current": self.current,
        }


@dataclass(frozen=True)
class AccountDeletionManifest:
    """Data references needed to finish an already-authorized deletion."""

    user_id: str
    device_ids: tuple[str, ...]
    session_ids: tuple[str, ...]
    artifact_count: int


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
                    password_salt TEXT,
                    password_digest TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS troika_devices (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES troika_users(id),
                    name TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    revoked_at REAL,
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

                CREATE TABLE IF NOT EXISTS troika_entitlements (
                    user_id TEXT PRIMARY KEY REFERENCES troika_users(id),
                    plan TEXT NOT NULL,
                    daily_request_limit INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS troika_usage_daily (
                    user_id TEXT NOT NULL REFERENCES troika_users(id),
                    usage_date TEXT NOT NULL,
                    requests INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (user_id, usage_date)
                );

                CREATE TABLE IF NOT EXISTS troika_audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occurred_at REAL NOT NULL,
                    event_type TEXT NOT NULL,
                    user_id TEXT REFERENCES troika_users(id),
                    device_id TEXT REFERENCES troika_devices(id),
                    session_digest TEXT,
                    run_digest TEXT,
                    details_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS troika_notification_preferences (
                    user_id TEXT PRIMARY KEY REFERENCES troika_users(id),
                    preferences_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_troika_devices_user
                    ON troika_devices(user_id);
                CREATE INDEX IF NOT EXISTS idx_troika_tokens_device
                    ON troika_api_tokens(device_id);
                CREATE INDEX IF NOT EXISTS idx_troika_sessions_user
                    ON troika_sessions(user_id);
                CREATE INDEX IF NOT EXISTS idx_troika_usage_daily_date
                    ON troika_usage_daily(usage_date);
                CREATE INDEX IF NOT EXISTS idx_troika_audit_events_user_time
                    ON troika_audit_events(user_id, occurred_at DESC);
                CREATE INDEX IF NOT EXISTS idx_troika_audit_events_device_time
                    ON troika_audit_events(device_id, occurred_at DESC);
                """
            )
            device_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(troika_devices)")
            }
            if "revoked_at" not in device_columns:
                connection.execute(
                    "ALTER TABLE troika_devices ADD COLUMN revoked_at REAL"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_troika_devices_user_revoked "
                "ON troika_devices(user_id, status, revoked_at)"
            )
            user_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(troika_users)")
            }
            if "password_salt" not in user_columns:
                connection.execute(
                    "ALTER TABLE troika_users ADD COLUMN password_salt TEXT"
                )
            if "password_digest" not in user_columns:
                connection.execute(
                    "ALTER TABLE troika_users ADD COLUMN password_digest TEXT"
                )

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _token_digest(token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _audit_reference_digest(value: str | None) -> str | None:
        """Keep an auditable correlation reference without storing raw client IDs."""
        if value is None:
            return None
        clean_value = str(value).strip()
        if not clean_value:
            return None
        return sha256(clean_value.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _normalize_email(email: str) -> str:
        normalized = email.strip().lower()
        if not normalized or "@" not in normalized or len(normalized) > 254:
            raise ValueError("a valid email address is required")
        return normalized

    @staticmethod
    def _password_hash(password: str, salt: bytes) -> str:
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            raise ValueError("password must contain between 10 and 128 characters")
        return scrypt(
            password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
        ).hex()

    def register_account(
        self,
        email: str,
        password: str,
        *,
        plan: str = "free",
        daily_request_limit: int = 1,
    ) -> str:
        """Create a password-backed account atomically for self-registration."""
        user_id = self._new_id("usr")
        normalized_email = self._normalize_email(email)
        clean_plan = self._normalize_plan(plan)
        limit = self._validate_daily_request_limit(daily_request_limit)
        salt = secrets.token_bytes(16)
        digest = self._password_hash(password, salt)
        now = time.time()
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO troika_users "
                    "(id, email, password_salt, password_digest, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (user_id, normalized_email, salt.hex(), digest, now),
                )
                connection.execute(
                    "INSERT INTO troika_entitlements "
                    "(user_id, plan, daily_request_limit, updated_at) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, clean_plan, limit, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("an account with this email already exists") from exc
        return user_id

    def authenticate_password(self, email: str, password: str) -> str | None:
        """Return the active user ID when email and password match."""
        normalized_email = self._normalize_email(email)
        # Validate length before doing the lookup and expensive hash.
        if not isinstance(password, str) or not 10 <= len(password) <= 128:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, password_salt, password_digest FROM troika_users "
                "WHERE email = ? AND status = 'active'",
                (normalized_email,),
            ).fetchone()
        if row is None or not row["password_salt"] or not row["password_digest"]:
            return None
        try:
            actual = self._password_hash(password, bytes.fromhex(row["password_salt"]))
        except (TypeError, ValueError):
            return None
        return (
            str(row["id"])
            if secrets.compare_digest(actual, row["password_digest"])
            else None
        )

    @staticmethod
    def _validate_daily_request_limit(value: int) -> int:
        if isinstance(value, bool):
            raise ValueError("daily request limit must be an integer")
        try:
            limit = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("daily request limit must be an integer") from exc
        if not 1 <= limit <= 10_000:
            raise ValueError("daily request limit must be between 1 and 10000")
        return limit

    @staticmethod
    def _normalize_plan(plan: str) -> str:
        cleaned = str(plan).strip().lower()
        if (
            not cleaned
            or len(cleaned) > 60
            or not cleaned.replace("_", "").replace("-", "").isalnum()
        ):
            raise ValueError(
                "plan must contain only letters, numbers, hyphens, or underscores"
            )
        return cleaned

    def create_user(
        self,
        email: str,
        *,
        plan: str = "beta",
        daily_request_limit: int = 50,
    ) -> str:
        """Create an active beta user and return its opaque ID."""
        user_id = self._new_id("usr")
        normalized_email = self._normalize_email(email)
        clean_plan = self._normalize_plan(plan)
        limit = self._validate_daily_request_limit(daily_request_limit)
        now = time.time()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO troika_users (id, email, created_at) VALUES (?, ?, ?)",
                (user_id, normalized_email, now),
            )
            connection.execute(
                "INSERT INTO troika_entitlements "
                "(user_id, plan, daily_request_limit, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, clean_plan, limit, now),
            )
        return user_id

    def set_entitlement(
        self, user_id: str, *, plan: str, daily_request_limit: int
    ) -> None:
        """Set an operator-approved plan and daily request limit for one user."""
        clean_plan = self._normalize_plan(plan)
        limit = self._validate_daily_request_limit(daily_request_limit)
        with self._connect() as connection:
            user = connection.execute(
                "SELECT id FROM troika_users WHERE id = ?", (user_id,)
            ).fetchone()
            if user is None:
                raise ValueError("user does not exist")
            connection.execute(
                "INSERT INTO troika_entitlements "
                "(user_id, plan, daily_request_limit, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "plan = excluded.plan, "
                "daily_request_limit = excluded.daily_request_limit, "
                "updated_at = excluded.updated_at",
                (user_id, clean_plan, limit, time.time()),
            )

    def consume_chat_request(
        self, principal: AccessPrincipal, *, now: datetime | None = None
    ) -> UsageDecision:
        """Atomically consume one request from the user's UTC daily quota.

        A rejected request is not recorded.  ``BEGIN IMMEDIATE`` serializes
        concurrent requests against the same SQLite database, so two devices
        cannot both spend the last available request.
        """
        timestamp = now or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        usage_date = timestamp.astimezone(timezone.utc).date().isoformat()
        current_time = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            entitlement = connection.execute(
                "SELECT daily_request_limit FROM troika_entitlements WHERE user_id = ?",
                (principal.user_id,),
            ).fetchone()
            if entitlement is None:
                raise ValueError("user has no active entitlement")
            limit = self._validate_daily_request_limit(
                entitlement["daily_request_limit"]
            )
            row = connection.execute(
                "SELECT requests FROM troika_usage_daily "
                "WHERE user_id = ? AND usage_date = ?",
                (principal.user_id, usage_date),
            ).fetchone()
            used = int(row["requests"]) if row is not None else 0
            if used >= limit:
                return UsageDecision(False, usage_date, limit, used, 0)
            used += 1
            connection.execute(
                "INSERT INTO troika_usage_daily "
                "(user_id, usage_date, requests, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, usage_date) DO UPDATE SET "
                "requests = excluded.requests, updated_at = excluded.updated_at",
                (principal.user_id, usage_date, used, current_time),
            )
        return UsageDecision(True, usage_date, limit, used, limit - used)

    def daily_usage(self, user_id: str, *, now: datetime | None = None) -> int:
        """Return recorded requests for an operator's current UTC day view."""
        timestamp = now or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        usage_date = timestamp.astimezone(timezone.utc).date().isoformat()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT requests FROM troika_usage_daily "
                "WHERE user_id = ? AND usage_date = ?",
                (user_id, usage_date),
            ).fetchone()
        return int(row["requests"]) if row is not None else 0

    def subscription_summary(
        self, principal: AccessPrincipal, *, now: datetime | None = None
    ) -> dict[str, str | int | float]:
        """Return the current owner's plan and daily usage without billing data."""
        timestamp = now or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        usage_date = timestamp.astimezone(timezone.utc).date().isoformat()
        with self._connect() as connection:
            self._require_active_principal(connection, principal)
            entitlement = connection.execute(
                "SELECT plan, daily_request_limit, updated_at "
                "FROM troika_entitlements WHERE user_id = ?",
                (principal.user_id,),
            ).fetchone()
            if entitlement is None:
                raise ValueError("user has no active entitlement")
            usage = connection.execute(
                "SELECT requests FROM troika_usage_daily "
                "WHERE user_id = ? AND usage_date = ?",
                (principal.user_id, usage_date),
            ).fetchone()
        limit = self._validate_daily_request_limit(
            entitlement["daily_request_limit"]
        )
        used = int(usage["requests"]) if usage is not None else 0
        return {
            "plan": str(entitlement["plan"]),
            "status": "active",
            "usage_date": usage_date,
            "daily_limit": limit,
            "used": used,
            "remaining": max(0, limit - used),
            "updated_at": float(entitlement["updated_at"]),
        }

    @staticmethod
    def _normalize_audit_details(
        details: dict[str, str | int | float | bool | None] | None,
    ) -> dict[str, str | int | float | bool | None]:
        """Reject message-like fields so audit rows cannot become a shadow chat log."""
        if details is None:
            return {}
        if not isinstance(details, dict) or len(details) > 16:
            raise ValueError("audit details must contain at most 16 scalar values")
        normalized: dict[str, str | int | float | bool | None] = {}
        forbidden = {
            "api_key",
            "authorization",
            "content",
            "message",
            "prompt",
            "token",
        }
        for key, value in details.items():
            clean_key = str(key).strip().lower()
            if (
                not clean_key
                or len(clean_key) > 64
                or clean_key in forbidden
                or not clean_key.replace("_", "").replace("-", "").isalnum()
            ):
                raise ValueError("audit detail key is not allowed")
            if isinstance(value, str):
                if len(value) > 120:
                    raise ValueError("audit detail value is too long")
                normalized[clean_key] = value
            elif value is None or isinstance(value, (bool, int, float)):
                normalized[clean_key] = value
            else:
                raise ValueError("audit details must use scalar values")
        return normalized

    def record_audit_event(
        self,
        event_type: str,
        *,
        principal: AccessPrincipal | None = None,
        session_id: str | None = None,
        run_id: str | None = None,
        details: dict[str, str | int | float | bool | None] | None = None,
    ) -> int:
        """Append a privacy-preserving product event and return its database ID."""
        clean_event_type = str(event_type).strip().lower()
        if (
            not clean_event_type
            or len(clean_event_type) > 100
            or not clean_event_type
            .replace("_", "")
            .replace("-", "")
            .replace(".", "")
            .isalnum()
        ):
            raise ValueError("audit event type is invalid")
        normalized_details = self._normalize_audit_details(details)
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO troika_audit_events "
                "(occurred_at, event_type, user_id, device_id, session_digest, run_digest, details_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    time.time(),
                    clean_event_type,
                    principal.user_id if principal else None,
                    principal.device_id if principal else None,
                    self._audit_reference_digest(session_id),
                    self._audit_reference_digest(run_id),
                    json.dumps(
                        normalized_details, sort_keys=True, separators=(",", ":")
                    ),
                ),
            )
        return int(cursor.lastrowid)

    def list_audit_events(self, user_id: str, *, limit: int = 100) -> list[AuditEvent]:
        """Return a bounded operator view of one user's privacy-safe audit trail."""
        if isinstance(limit, bool) or not 1 <= int(limit) <= 500:
            raise ValueError("audit event limit must be between 1 and 500")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, occurred_at, event_type, user_id, device_id, "
                "session_digest, run_digest, details_json "
                "FROM troika_audit_events WHERE user_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, int(limit)),
            ).fetchall()
        return [
            AuditEvent(
                id=int(row["id"]),
                occurred_at=float(row["occurred_at"]),
                event_type=str(row["event_type"]),
                user_id=row["user_id"],
                device_id=row["device_id"],
                session_digest=row["session_digest"],
                run_digest=row["run_digest"],
                details=json.loads(row["details_json"]),
            )
            for row in rows
        ]

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

    def principal_is_active(self, principal: AccessPrincipal) -> bool:
        """Recheck a previously authenticated principal against current state."""
        with self._connect() as connection:
            try:
                self._require_active_principal(connection, principal)
            except PermissionError:
                return False
        return True

    def list_devices(self, principal: AccessPrincipal) -> list[DeviceSummary]:
        """List only devices owned by the authenticated account."""
        with self._connect() as connection:
            connection.execute("BEGIN")
            self._require_active_principal(connection, principal)
            rows = connection.execute(
                "SELECT id, name, platform, status, created_at "
                "FROM troika_devices WHERE user_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (principal.user_id,),
            ).fetchall()
        return [
            DeviceSummary(
                id=str(row["id"]),
                name=str(row["name"]),
                platform=str(row["platform"]),
                status=str(row["status"]),
                created_at=float(row["created_at"]),
                current=str(row["id"]) == principal.device_id,
            )
            for row in rows
        ]

    def revoke_device(self, principal: AccessPrincipal, device_id: str) -> bool:
        """Revoke one owned device and every bearer token issued to it."""
        clean_device_id = str(device_id).strip()
        if (
            not clean_device_id
            or len(clean_device_id) > 200
            or any(char in clean_device_id for char in "\r\n\x00")
        ):
            return False
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_active_principal(connection, principal)
            owned = connection.execute(
                "SELECT 1 FROM troika_devices WHERE id = ? AND user_id = ?",
                (clean_device_id, principal.user_id),
            ).fetchone()
            if owned is None:
                return False
            connection.execute(
                "UPDATE troika_devices SET status = 'revoked', "
                "revoked_at = COALESCE(revoked_at, ?) "
                "WHERE id = ? AND user_id = ?",
                (now, clean_device_id, principal.user_id),
            )
            connection.execute(
                "UPDATE troika_api_tokens SET revoked_at = COALESCE(revoked_at, ?) "
                "WHERE device_id = ?",
                (now, clean_device_id),
            )
        return True

    def revoke_all_devices(self, principal: AccessPrincipal) -> tuple[str, ...]:
        """Revoke every device and bearer token owned by this account."""
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_active_principal(connection, principal)
            device_ids = tuple(
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM troika_devices "
                    "WHERE user_id = ? AND status = 'active' ORDER BY id",
                    (principal.user_id,),
                ).fetchall()
            )
            connection.execute(
                "UPDATE troika_devices SET status = 'revoked', "
                "revoked_at = COALESCE(revoked_at, ?) "
                "WHERE user_id = ? AND status = 'active'",
                (now, principal.user_id),
            )
            connection.execute(
                "UPDATE troika_api_tokens SET revoked_at = COALESCE(revoked_at, ?) "
                "WHERE device_id IN "
                "(SELECT id FROM troika_devices WHERE user_id = ?)",
                (now, principal.user_id),
            )
        return device_ids

    @staticmethod
    def _require_active_principal(
        connection: sqlite3.Connection,
        principal: AccessPrincipal,
    ) -> None:
        """Recheck ownership and revocation within a preferences transaction."""
        row = connection.execute(
            "SELECT 1 FROM troika_api_tokens AS tokens "
            "JOIN troika_devices AS devices ON devices.id = tokens.device_id "
            "JOIN troika_users AS users ON users.id = devices.user_id "
            "WHERE tokens.id = ? AND devices.id = ? AND users.id = ? "
            "AND tokens.revoked_at IS NULL "
            "AND (tokens.expires_at IS NULL OR tokens.expires_at > ?) "
            "AND devices.status = 'active' AND users.status = 'active'",
            (principal.token_id, principal.device_id, principal.user_id, time.time()),
        ).fetchone()
        if row is None:
            raise PermissionError("active product authentication is required")

    def notification_preferences(
        self, principal: AccessPrincipal
    ) -> NotificationPreferences:
        """Read this authenticated account's preferences, defaulting to opt-out."""
        with self._connect() as connection:
            self._require_active_principal(connection, principal)
            row = connection.execute(
                "SELECT preferences_json FROM troika_notification_preferences WHERE user_id = ?",
                (principal.user_id,),
            ).fetchone()
        if row is None:
            return NotificationPreferences()
        return NotificationPreferences.from_dict(json.loads(row["preferences_json"]))

    def set_notification_preferences(
        self,
        principal: AccessPrincipal,
        preferences: NotificationPreferences,
    ) -> NotificationPreferences:
        """Atomically replace preferences and record consent without schedule data."""
        validated = NotificationPreferences.from_dict(preferences.to_dict())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_active_principal(connection, principal)
            now = time.time()
            connection.execute(
                "INSERT INTO troika_notification_preferences "
                "(user_id, preferences_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "preferences_json = excluded.preferences_json, updated_at = excluded.updated_at",
                (principal.user_id, json.dumps(validated.to_dict()), now),
            )
            details = {
                "reminders_enabled": validated.reminders_enabled,
                "proactive_enabled": validated.proactive_enabled,
                "quiet_hours_enabled": validated.quiet_hours_enabled,
            }
            connection.execute(
                "INSERT INTO troika_audit_events "
                "(occurred_at, event_type, user_id, device_id, details_json) "
                "VALUES (?, 'notifications.preferences_updated', ?, ?, ?)",
                (now, principal.user_id, principal.device_id, json.dumps(details)),
            )
        return validated

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
                    (
                        clean_session_id,
                        principal.user_id,
                        principal.device_id,
                        time.time(),
                    ),
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

    def export_account_rows(self, principal: AccessPrincipal) -> dict[str, object]:
        """Return one active account's portable rows in a read transaction.

        Bearer-token digests, vision nonce digests, and artifact storage names
        are server credentials or implementation details, so they are never
        included in the user-facing export.
        """

        def rows(
            connection: sqlite3.Connection,
            query: str,
            parameters: tuple[object, ...],
        ) -> list[dict[str, object]]:
            return [dict(row) for row in connection.execute(query, parameters)]

        def decode_json_fields(
            items: list[dict[str, object]], fields: tuple[str, ...]
        ) -> list[dict[str, object]]:
            for item in items:
                for field in fields:
                    value = item.get(field)
                    if isinstance(value, str):
                        item[field] = json.loads(value)
            return items

        with self._connect() as connection:
            connection.execute("BEGIN")
            self._require_active_principal(connection, principal)
            existing_tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

            account = connection.execute(
                "SELECT id, email, status, created_at FROM troika_users WHERE id = ?",
                (principal.user_id,),
            ).fetchone()
            if account is None:
                raise PermissionError("active product authentication is required")

            devices = rows(
                connection,
                "SELECT id, name, platform, status, revoked_at, created_at "
                "FROM troika_devices WHERE user_id = ? ORDER BY created_at, id",
                (principal.user_id,),
            )
            tokens = rows(
                connection,
                "SELECT tokens.id, tokens.device_id, tokens.expires_at, "
                "tokens.revoked_at, tokens.created_at "
                "FROM troika_api_tokens AS tokens "
                "JOIN troika_devices AS devices ON devices.id = tokens.device_id "
                "WHERE devices.user_id = ? ORDER BY tokens.created_at, tokens.id",
                (principal.user_id,),
            )
            sessions = rows(
                connection,
                "SELECT session_id, device_id, created_at FROM troika_sessions "
                "WHERE user_id = ? ORDER BY created_at, session_id",
                (principal.user_id,),
            )
            entitlements = rows(
                connection,
                "SELECT plan, daily_request_limit, updated_at "
                "FROM troika_entitlements WHERE user_id = ?",
                (principal.user_id,),
            )
            usage = rows(
                connection,
                "SELECT usage_date, requests, updated_at FROM troika_usage_daily "
                "WHERE user_id = ? ORDER BY usage_date",
                (principal.user_id,),
            )
            audit_events = decode_json_fields(
                rows(
                    connection,
                    "SELECT id, occurred_at, event_type, device_id, session_digest, "
                    "run_digest, details_json FROM troika_audit_events "
                    "WHERE user_id = ? ORDER BY occurred_at, id",
                    (principal.user_id,),
                ),
                ("details_json",),
            )
            preferences = decode_json_fields(
                rows(
                    connection,
                    "SELECT preferences_json, updated_at "
                    "FROM troika_notification_preferences WHERE user_id = ?",
                    (principal.user_id,),
                ),
                ("preferences_json",),
            )

            optional_queries = {
                "memories": (
                    "troika_memories",
                    "SELECT id, kind, title, content, created_at, updated_at "
                    "FROM troika_memories WHERE user_id = ? ORDER BY created_at, id",
                ),
                "projects": (
                    "troika_projects",
                    "SELECT id, name, summary, status, is_active, created_at, updated_at "
                    "FROM troika_projects WHERE user_id = ? ORDER BY created_at, id",
                ),
                "tasks": (
                    "troika_project_tasks",
                    "SELECT id, project_id, title, details, status, due_at, action_mode, "
                    "action_summary, idempotency_key, created_at, updated_at "
                    "FROM troika_project_tasks WHERE user_id = ? ORDER BY created_at, id",
                ),
                "notes": (
                    "troika_project_notes",
                    "SELECT id, project_id, kind, content, idempotency_key, created_at "
                    "FROM troika_project_notes WHERE user_id = ? ORDER BY created_at, id",
                ),
                "inbox_messages": (
                    "troika_inbox_messages",
                    "SELECT id, kind, category, title, body, reason, project_id, task_id, "
                    "available_at, delivered_at, read_at, requires_approval, "
                    "idempotency_key, created_at FROM troika_inbox_messages "
                    "WHERE user_id = ? ORDER BY created_at, id",
                ),
                "vision_sessions": (
                    "troika_vision_sessions",
                    "SELECT id, device_id, token_id, capability, status, created_at, "
                    "expires_at, consumed_at FROM troika_vision_sessions "
                    "WHERE user_id = ? ORDER BY created_at, id",
                ),
                "artifacts": (
                    "troika_artifacts",
                    "SELECT id, created_by_device_id, filename, kind, mime_type, byte_size, "
                    "sha256_digest, created_at FROM troika_artifacts "
                    "WHERE user_id = ? ORDER BY created_at, id",
                ),
            }
            optional = {
                key: rows(connection, query, (principal.user_id,))
                if table in existing_tables
                else []
                for key, (table, query) in optional_queries.items()
            }

        return {
            "account": dict(account),
            "devices": devices,
            "tokens": tokens,
            "sessions": sessions,
            "entitlements": entitlements,
            "usage_daily": usage,
            "audit_events": audit_events,
            "notification_preferences": preferences,
            **optional,
        }

    def prepare_account_deletion(
        self, principal: AccessPrincipal
    ) -> AccountDeletionManifest:
        """Revoke an account immediately and return its cleanup manifest.

        The account remains as a ``deleting`` tombstone until filesystem and
        SessionDB cleanup succeeds.  This keeps deletion retryable after a
        process crash without allowing any revoked token to authenticate.
        """
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._require_active_principal(connection, principal)
            now = time.time()
            connection.execute(
                "UPDATE troika_users SET status = 'deleting' WHERE id = ?",
                (principal.user_id,),
            )
            connection.execute(
                "UPDATE troika_devices SET status = 'revoked', "
                "revoked_at = COALESCE(revoked_at, ?) WHERE user_id = ?",
                (now, principal.user_id),
            )
            connection.execute(
                "UPDATE troika_api_tokens SET revoked_at = COALESCE(revoked_at, ?) "
                "WHERE device_id IN (SELECT id FROM troika_devices WHERE user_id = ?)",
                (now, principal.user_id),
            )
            return self._account_deletion_manifest(connection, principal.user_id)

    def account_deletion_manifest(self, user_id: str) -> AccountDeletionManifest:
        """Return cleanup references for a persisted ``deleting`` account."""
        with self._connect() as connection:
            return self._account_deletion_manifest(connection, user_id)

    @staticmethod
    def _account_deletion_manifest(
        connection: sqlite3.Connection, user_id: str
    ) -> AccountDeletionManifest:
        user = connection.execute(
            "SELECT status FROM troika_users WHERE id = ?", (user_id,)
        ).fetchone()
        if user is None or user["status"] != "deleting":
            raise ValueError("account is not pending deletion")
        device_ids = tuple(
            str(row["id"])
            for row in connection.execute(
                "SELECT id FROM troika_devices WHERE user_id = ? ORDER BY id",
                (user_id,),
            ).fetchall()
        )
        session_ids = tuple(
            str(row["session_id"])
            for row in connection.execute(
                "SELECT session_id FROM troika_sessions WHERE user_id = ? "
                "ORDER BY session_id",
                (user_id,),
            ).fetchall()
        )
        tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        artifact_count = 0
        if "troika_artifacts" in tables:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM troika_artifacts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            artifact_count = int(row["count"])
        return AccountDeletionManifest(
            user_id=user_id,
            device_ids=device_ids,
            session_ids=session_ids,
            artifact_count=artifact_count,
        )

    def pending_account_deletions(self) -> tuple[str, ...]:
        """List crash-recoverable account deletion tombstones."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM troika_users WHERE status = 'deleting' ORDER BY id"
            ).fetchall()
        return tuple(str(row["id"]) for row in rows)

    def finalize_account_deletion(self, user_id: str) -> None:
        """Delete every product SQLite row for a prepared account atomically."""
        child_tables = (
            "troika_memories",
            "troika_inbox_messages",
            "troika_project_notes",
            "troika_project_tasks",
            "troika_projects",
            "troika_vision_sessions",
            "troika_artifacts",
            "troika_notification_preferences",
            "troika_audit_events",
            "troika_usage_daily",
            "troika_entitlements",
            "troika_sessions",
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._account_deletion_manifest(connection, user_id)
            existing_tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            for table in child_tables:
                if table in existing_tables:
                    connection.execute(
                        f"DELETE FROM {table} WHERE user_id = ?", (user_id,)
                    )
            connection.execute(
                "DELETE FROM troika_api_tokens WHERE device_id IN "
                "(SELECT id FROM troika_devices WHERE user_id = ?)",
                (user_id,),
            )
            connection.execute(
                "DELETE FROM troika_devices WHERE user_id = ?", (user_id,)
            )
            cursor = connection.execute(
                "DELETE FROM troika_users WHERE id = ?", (user_id,)
            )
            if cursor.rowcount != 1:
                raise RuntimeError("account deletion did not remove the user tombstone")
