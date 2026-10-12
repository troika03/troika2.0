"""Transactional foundation for Troika's monthly AI resource accounting.

No public payment endpoint, provider wrapper, or production activation lives
here. Grant methods are for trusted server code AFTER payment/verification.
Callers must reserve a bounded quote before dispatch, settle measured usage,
and retain dispatched reservations when provider billing is unknown.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import sqlite3
import uuid

from troika_product.access import AccessPrincipal, AccessRegistry
from troika_product.subscription_policy import (
    POLICY_VERSION,
    TOP_UP_DAYS,
    TOP_UP_TOKENS,
    WELCOME_DAYS,
    WELCOME_TOKENS,
    TokenUsage,
    plan_policy,
)


class ResourceLimitExceeded(RuntimeError):
    """A reservation cannot fit in the common account resource budget."""


class ResourceConflict(ValueError):
    """An idempotency key was reused for a different operation."""


class FeatureLimitExceeded(ResourceLimitExceeded):
    """A feature is unavailable on this plan or its monthly cap was reached."""


@dataclass(frozen=True)
class Reservation:
    id: str
    state: str
    reserved_tokens: int
    charged_tokens: int | None


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("an aware UTC-compatible timestamp is required")
    return value.astimezone(timezone.utc)


def _key(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise ValueError("a non-empty opaque idempotency key is required")
    return sha256(value.encode("utf-8")).hexdigest()


def _count(value: int) -> int:
    if type(value) is not int or value < 0 or value > 1_000_000_000:
        raise ValueError("resource amount must be a bounded non-negative integer")
    return value


class ResourceLedger:
    """Use the access DB so revocation, export and deletion share owner scope."""

    def __init__(self, registry: AccessRegistry):
        self.registry = registry
        with self.registry._connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS troika_resource_grants (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES troika_users(id) ON DELETE CASCADE,
                    event_digest TEXT NOT NULL UNIQUE,
                    kind TEXT NOT NULL CHECK(kind IN ('monthly','welcome','top_up')),
                    plan TEXT NOT NULL,
                    starts_at REAL NOT NULL,
                    expires_at REAL NOT NULL CHECK(expires_at > starts_at),
                    granted INTEGER NOT NULL CHECK(granted >= 0),
                    available INTEGER NOT NULL CHECK(available >= 0),
                    reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved >= 0),
                    spent INTEGER NOT NULL DEFAULT 0 CHECK(spent >= 0),
                    policy_version TEXT NOT NULL,
                    CHECK(granted = available + reserved + spent)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_resource_month
                    ON troika_resource_grants(user_id, starts_at) WHERE kind = 'monthly';
                CREATE UNIQUE INDEX IF NOT EXISTS idx_resource_welcome
                    ON troika_resource_grants(user_id) WHERE kind = 'welcome';
                CREATE TABLE IF NOT EXISTS troika_resource_operations (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES troika_users(id) ON DELETE CASCADE,
                    key_digest TEXT NOT NULL,
                    run_digest TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('llm','stt','tts','tool')),
                    feature TEXT,
                    period_id TEXT NOT NULL REFERENCES troika_resource_grants(id) ON DELETE CASCADE,
                    state TEXT NOT NULL CHECK(state IN ('reserved','dispatched','settled','released')),
                    reserved_tokens INTEGER NOT NULL CHECK(reserved_tokens >= 0),
                    charged_tokens INTEGER CHECK(charged_tokens >= 0),
                    pricing_version TEXT NOT NULL,
                    usage_json TEXT,
                    created_at REAL NOT NULL,
                    settled_at REAL,
                    UNIQUE(user_id, key_digest)
                );
                CREATE TABLE IF NOT EXISTS troika_resource_allocations (
                    operation_id TEXT NOT NULL REFERENCES troika_resource_operations(id) ON DELETE CASCADE,
                    grant_id TEXT NOT NULL REFERENCES troika_resource_grants(id) ON DELETE CASCADE,
                    amount INTEGER NOT NULL CHECK(amount >= 0),
                    PRIMARY KEY(operation_id, grant_id)
                );
                CREATE TABLE IF NOT EXISTS troika_resource_features (
                    user_id TEXT NOT NULL REFERENCES troika_users(id) ON DELETE CASCADE,
                    period_id TEXT NOT NULL REFERENCES troika_resource_grants(id) ON DELETE CASCADE,
                    feature TEXT NOT NULL,
                    used INTEGER NOT NULL CHECK(used >= 0),
                    PRIMARY KEY(user_id, period_id, feature)
                );
            """)

    def _plan(self, c: sqlite3.Connection, principal: AccessPrincipal):
        self.registry._require_active_principal(c, principal)
        row = c.execute(
            "SELECT plan FROM troika_entitlements WHERE user_id = ?",
            (principal.user_id,),
        ).fetchone()
        if row is None:
            raise PermissionError("active product entitlement is required")
        return plan_policy(row["plan"])

    def _grant(self, c, principal, *, kind, event_key, starts, expires, amount):
        plan = self._plan(c, principal)
        digest = _key(event_key)
        existing = c.execute(
            "SELECT * FROM troika_resource_grants WHERE event_digest = ?", (digest,)
        ).fetchone()
        signature = (
            principal.user_id,
            kind,
            plan.name,
            starts.timestamp(),
            expires.timestamp(),
            amount,
        )
        if existing:
            prior = tuple(
                existing[k]
                for k in (
                    "user_id",
                    "kind",
                    "plan",
                    "starts_at",
                    "expires_at",
                    "granted",
                )
            )
            if prior != signature:
                raise ResourceConflict(
                    "grant event already belongs to a different grant"
                )
            return existing["id"]
        # Another receipt must not create overlapping paid periods or reset quota.
        if (
            kind == "monthly"
            and c.execute(
                "SELECT 1 FROM troika_resource_grants WHERE user_id = ? AND kind = 'monthly' "
                "AND starts_at < ? AND expires_at > ?",
                (principal.user_id, expires.timestamp(), starts.timestamp()),
            ).fetchone()
        ):
            raise ResourceConflict("monthly resource periods cannot overlap")
        grant_id = str(uuid.uuid4())
        try:
            c.execute(
                "INSERT INTO troika_resource_grants "
                "(id,user_id,event_digest,kind,plan,starts_at,expires_at,granted,available,policy_version) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    grant_id,
                    principal.user_id,
                    digest,
                    kind,
                    plan.name,
                    starts.timestamp(),
                    expires.timestamp(),
                    amount,
                    amount,
                    POLICY_VERSION,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ResourceConflict("resource grant already exists") from exc
        return grant_id

    def grant_monthly(
        self, principal, *, starts_at: datetime, expires_at: datetime, event_key: str
    ) -> str:
        """Trusted billing/operator adapter supplies the actual paid period.

        Never derive paid renewal from an API request or an entitlement update.
        Free uses calendar months. Paid invoices must be separately verified.
        """
        starts, expires = _utc(starts_at), _utc(expires_at)
        if not timedelta(0) < expires - starts <= timedelta(days=32):
            raise ValueError("invalid monthly resource period")
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            plan = self._plan(c, principal)
            if plan.name != "free" and expires - starts < timedelta(days=28):
                raise ValueError(
                    "paid resource period must cover a monthly billing period"
                )
            if plan.name == "free" and (
                starts
                != starts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                or expires != self._next_month(starts)
            ):
                raise ValueError("Free resource period must be a calendar month")
            return self._grant(
                c,
                principal,
                kind="monthly",
                event_key=event_key,
                starts=starts,
                expires=expires,
                amount=plan.monthly_tokens,
            )

    @staticmethod
    def _next_month(start: datetime) -> datetime:
        return start.replace(
            year=start.year + (start.month == 12), month=start.month % 12 + 1, day=1
        )

    def _period(self, c, principal, now):
        plan = self._plan(c, principal)
        period = c.execute(
            "SELECT * FROM troika_resource_grants WHERE user_id = ? AND kind = 'monthly' "
            "AND plan = ? AND starts_at <= ? AND expires_at > ? ORDER BY starts_at DESC LIMIT 1",
            (principal.user_id, plan.name, now.timestamp(), now.timestamp()),
        ).fetchone()
        if period is None and plan.name == "free":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            self._grant(
                c,
                principal,
                kind="monthly",
                event_key=f"free:{principal.user_id}:{start.isoformat()}",
                starts=start,
                expires=self._next_month(start),
                amount=plan.monthly_tokens,
            )
            period = c.execute(
                "SELECT * FROM troika_resource_grants WHERE user_id = ? AND kind = 'monthly' AND starts_at = ?",
                (principal.user_id, start.timestamp()),
            ).fetchone()
        if period is None:
            raise ResourceLimitExceeded("monthly resource period is not activated")
        return plan, period

    def grant_welcome(
        self,
        principal,
        *,
        at: datetime,
        event_key: str,
        verification_confirmed: bool = False,
    ) -> str:
        """Trusted verification adapter only; never expose the flag to clients.

        Email/anti-abuse verification does not exist yet, so production callers
        must leave automatic welcome grants disabled.
        """
        if verification_confirmed is not True:
            raise PermissionError("verified account eligibility is required")
        start = _utc(at)
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            return self._grant(
                c,
                principal,
                kind="welcome",
                event_key=event_key,
                starts=start,
                expires=start + timedelta(days=WELCOME_DAYS),
                amount=WELCOME_TOKENS,
            )

    def grant_top_up(
        self,
        principal,
        *,
        at: datetime,
        event_key: str,
        payment_confirmed: bool = False,
    ) -> str:
        """Trusted payment adapter only, after signature/amount/currency checks."""
        if payment_confirmed is not True:
            raise PermissionError("verified top-up payment is required")
        start = _utc(at)
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            return self._grant(
                c,
                principal,
                kind="top_up",
                event_key=event_key,
                starts=start,
                expires=start + timedelta(days=TOP_UP_DAYS),
                amount=TOP_UP_TOKENS,
            )

    @staticmethod
    def _reservation(row) -> Reservation:
        return Reservation(
            row["id"], row["state"], row["reserved_tokens"], row["charged_tokens"]
        )

    def reserve(
        self,
        principal,
        *,
        operation_key: str,
        run_key: str,
        kind: str,
        tokens: int,
        pricing_version: str,
        feature: str | None = None,
        now: datetime | None = None,
    ) -> Reservation:
        """One atomic hold across devices and all calls of a parent run."""
        tokens = _count(tokens)
        when = _utc(now or datetime.now(timezone.utc))
        if kind not in {"llm", "stt", "tts", "tool"}:
            raise ValueError("unsupported resource operation kind")
        if not pricing_version or len(pricing_version) > 100:
            raise ValueError("pricing version is required before dispatch")
        digest, run_digest = _key(operation_key), _key(run_key)
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self._plan(c, principal)
            existing = c.execute(
                "SELECT * FROM troika_resource_operations WHERE user_id = ? AND key_digest = ?",
                (principal.user_id, digest),
            ).fetchone()
            if existing:
                if (
                    existing["run_digest"],
                    existing["kind"],
                    existing["reserved_tokens"],
                    existing["pricing_version"],
                    existing["feature"],
                ) != (run_digest, kind, tokens, pricing_version, feature):
                    raise ResourceConflict(
                        "reservation key was reused with different parameters"
                    )
                return self._reservation(existing)
            plan, period = self._period(c, principal, when)
            if feature is not None:
                limit = plan.feature_limit(feature)
                row = c.execute(
                    "SELECT used FROM troika_resource_features WHERE user_id = ? AND period_id = ? AND feature = ?",
                    (principal.user_id, period["id"], feature),
                ).fetchone()
                used = row["used"] if row else 0
                held = c.execute(
                    "SELECT COUNT(*) FROM troika_resource_operations WHERE user_id = ? AND period_id = ? "
                    "AND feature = ? AND state IN ('reserved','dispatched')",
                    (principal.user_id, period["id"], feature),
                ).fetchone()[0]
                if limit is not None and used + held >= limit:
                    raise FeatureLimitExceeded("subscription feature limit exceeded")
            buckets = c.execute(
                "SELECT * FROM troika_resource_grants WHERE user_id = ? AND starts_at <= ? "
                "AND expires_at > ? AND available > 0 ORDER BY expires_at, starts_at, id",
                (principal.user_id, when.timestamp(), when.timestamp()),
            ).fetchall()
            if sum(row["available"] for row in buckets) < tokens:
                raise ResourceLimitExceeded("monthly AI resource exhausted")
            operation_id = str(uuid.uuid4())
            c.execute(
                "INSERT INTO troika_resource_operations "
                "(id,user_id,key_digest,run_digest,kind,feature,period_id,state,reserved_tokens,pricing_version,created_at) "
                "VALUES (?,?,?,?,?,?,?,'reserved',?,?,?)",
                (
                    operation_id,
                    principal.user_id,
                    digest,
                    run_digest,
                    kind,
                    feature,
                    period["id"],
                    tokens,
                    pricing_version,
                    when.timestamp(),
                ),
            )
            remaining = tokens
            for row in buckets:
                amount = min(remaining, row["available"])
                if not amount:
                    break
                c.execute(
                    "UPDATE troika_resource_grants SET available = available - ?, reserved = reserved + ? WHERE id = ?",
                    (amount, amount, row["id"]),
                )
                c.execute(
                    "INSERT INTO troika_resource_allocations VALUES (?,?,?)",
                    (operation_id, row["id"], amount),
                )
                remaining -= amount
            return Reservation(operation_id, "reserved", tokens, None)

    def _operation(self, c, principal, operation_id):
        self.registry._require_active_principal(c, principal)
        row = c.execute(
            "SELECT * FROM troika_resource_operations WHERE id = ? AND user_id = ?",
            (operation_id, principal.user_id),
        ).fetchone()
        if row is None:
            raise PermissionError("resource operation is unavailable")
        return row

    def mark_dispatched(self, principal, operation_id: str) -> Reservation:
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = self._operation(c, principal, operation_id)
            if row["state"] != "reserved":
                raise ResourceConflict(
                    "resource operation has already been dispatched or completed"
                )
            c.execute(
                "UPDATE troika_resource_operations SET state = 'dispatched' WHERE id = ?",
                (operation_id,),
            )
            return Reservation(operation_id, "dispatched", row["reserved_tokens"], None)

    def settle(
        self,
        principal,
        operation_id: str,
        *,
        charged_tokens: int,
        usage: TokenUsage | None = None,
        successful: bool = True,
        now: datetime | None = None,
    ) -> Reservation:
        """Release the unused hold; retries return the exact original receipt.

        Unknown billing must keep its hold. A provider bound violation is an
        error, not permission to debit unreserved resource or another month.
        """
        charged = _count(charged_tokens)
        if type(successful) is not bool:
            raise ValueError("successful must be a boolean")
        when = _utc(now or datetime.now(timezone.utc))
        payload = json.dumps(
            {"tokens": asdict(usage) if usage else None, "successful": successful},
            sort_keys=True,
        )
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = self._operation(c, principal, operation_id)
            if row["state"] == "settled":
                if (row["charged_tokens"], row["usage_json"]) != (charged, payload):
                    raise ResourceConflict(
                        "settlement differs from the recorded receipt"
                    )
                return self._reservation(row)
            if row["state"] != "dispatched":
                raise ResourceConflict("only a dispatched operation can be settled")
            if charged > row["reserved_tokens"]:
                raise ResourceLimitExceeded(
                    "measured usage exceeds the reserved upper bound"
                )
            allocations = c.execute(
                "SELECT a.*, g.expires_at, g.starts_at FROM troika_resource_allocations a "
                "JOIN troika_resource_grants g ON g.id = a.grant_id "
                "WHERE operation_id = ? ORDER BY g.expires_at, g.starts_at, g.id",
                (operation_id,),
            ).fetchall()
            remaining = charged
            for a in allocations:
                debit = min(remaining, a["amount"])
                c.execute(
                    "UPDATE troika_resource_grants SET reserved = reserved - ?, spent = spent + ?, "
                    "available = available + ? WHERE id = ?",
                    (a["amount"], debit, a["amount"] - debit, a["grant_id"]),
                )
                remaining -= debit
            if successful and row["feature"] is not None:
                c.execute(
                    "INSERT INTO troika_resource_features VALUES (?,?,?,1) "
                    "ON CONFLICT(user_id,period_id,feature) DO UPDATE SET used = used + 1",
                    (principal.user_id, row["period_id"], row["feature"]),
                )
            c.execute(
                "UPDATE troika_resource_operations SET state = 'settled', charged_tokens = ?, "
                "usage_json = ?, settled_at = ? WHERE id = ?",
                (charged, payload, when.timestamp(), operation_id),
            )
            return Reservation(operation_id, "settled", row["reserved_tokens"], charged)

    def release_before_dispatch(self, principal, operation_id: str) -> Reservation:
        """Never auto-release dispatched holds after a timeout or restart."""
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = self._operation(c, principal, operation_id)
            if row["state"] == "released":
                return self._reservation(row)
            if row["state"] != "reserved":
                raise ResourceConflict("dispatched resource needs measured settlement")
            for a in c.execute(
                "SELECT * FROM troika_resource_allocations WHERE operation_id = ?",
                (operation_id,),
            ).fetchall():
                c.execute(
                    "UPDATE troika_resource_grants SET reserved = reserved - ?, available = available + ? WHERE id = ?",
                    (a["amount"], a["amount"], a["grant_id"]),
                )
            c.execute(
                "UPDATE troika_resource_operations SET state = 'released', charged_tokens = 0 WHERE id = ?",
                (operation_id,),
            )
            return Reservation(operation_id, "released", row["reserved_tokens"], 0)

    def summary(self, principal, *, now: datetime | None = None) -> dict:
        """Only trusted, actually issued periods contribute to the balance."""
        when = _utc(now or datetime.now(timezone.utc))
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            plan, period = self._period(c, principal, when)
            rows = c.execute(
                "SELECT kind,granted,available,reserved,spent,expires_at FROM troika_resource_grants "
                "WHERE user_id = ? AND starts_at <= ? AND expires_at > ? ORDER BY expires_at,id",
                (principal.user_id, when.timestamp(), when.timestamp()),
            ).fetchall()
            features = {
                row["feature"]: row["used"]
                for row in c.execute(
                    "SELECT feature,used FROM troika_resource_features WHERE user_id = ? AND period_id = ?",
                    (principal.user_id, period["id"]),
                )
            }
            return {
                "plan": plan.name,
                "unit": "calculated_ai_tokens",
                "policy_version": POLICY_VERSION,
                "monthly_limit": period["granted"],
                "remaining": sum(r["available"] for r in rows),
                "reserved": sum(r["reserved"] for r in rows),
                "spent": sum(r["spent"] for r in rows),
                "resets_at": datetime.fromtimestamp(
                    period["expires_at"], timezone.utc
                ).isoformat(),
                "feature_usage": features,
                "grants": [dict(r) for r in rows],
            }

    def export_rows(self, principal) -> dict:
        """Numerical owner data only; no idempotency hashes or private text."""
        with self.registry._connect() as c:
            self._plan(c, principal)
            return {
                "grants": [
                    dict(r)
                    for r in c.execute(
                        "SELECT kind,plan,starts_at,expires_at,granted,available,reserved,spent,policy_version "
                        "FROM troika_resource_grants WHERE user_id = ? ORDER BY starts_at,id",
                        (principal.user_id,),
                    )
                ],
                "operations": [
                    dict(r)
                    for r in c.execute(
                        "SELECT kind,feature,state,reserved_tokens,charged_tokens,pricing_version,usage_json,created_at,settled_at "
                        "FROM troika_resource_operations WHERE user_id = ? ORDER BY created_at,id",
                        (principal.user_id,),
                    )
                ],
            }
