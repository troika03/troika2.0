"""YooKassa checkout and canonical payment verification. Off by default.

Only the provider's authenticated GET result can grant resources. Webhook
payloads and browser success redirects are notifications, never receipts.
Renewal is explicit: no card saving or automatic debits are requested.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import os
import re
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

from troika_product.resource_ledger import ResourceConflict, ResourceLedger
from troika_product.subscription_policy import TOP_UP_DAYS, TOP_UP_TOKENS, plan_policy


SKUS = {
    "plus": (790, 5_000_000),
    "pro": (1490, 10_000_000),
    "top_up": (99, TOP_UP_TOKENS),
}


def checkout_url(value):
    parsed = urlsplit(value or "")
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
        or not any(
            host == domain or host.endswith("." + domain)
            for domain in {"yoomoney.ru", "yookassa.ru"}
        )
    ):
        raise ValueError("untrusted payment confirmation URL")
    return value


class YooKassa:
    def __init__(self, *, shop_id, secret, return_url, test=True):
        parsed = urlsplit(return_url)
        if (
            not shop_id
            or not secret
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or type(test) is not bool
        ):
            raise ValueError("payment store is not configured")
        self.shop_id, self.secret, self.return_url, self.test = (
            str(shop_id),
            secret,
            return_url,
            test,
        )

    async def _request(self, method, path, *, body=None, key=None):
        import aiohttp

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            auth=aiohttp.BasicAuth(self.shop_id, self.secret),
        ) as client:
            async with client.request(
                method,
                "https://api.yookassa.ru/v3/" + path,
                json=body,
                headers={"Idempotence-Key": key} if key else {},
                allow_redirects=False,
            ) as response:
                if response.status not in {200, 201}:
                    raise RuntimeError("payment provider is temporarily unavailable")
                data = await response.content.read(65537)
                if len(data) > 65536:
                    raise ValueError("payment response is too large")
                import json

                return json.loads(data)

    async def create(self, intent):
        return await self._request(
            "POST",
            "payments",
            key=intent["id"],
            body={
                "amount": {"value": f"{intent['price_rub']}.00", "currency": "RUB"},
                "capture": True,
                "description": "Troika " + intent["sku"],
                "confirmation": {"type": "redirect", "return_url": self.return_url},
                "metadata": {"troika_intent": intent["id"]},
            },
        )

    async def get(self, payment_id):
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", payment_id):
            raise ValueError("invalid payment ID")
        return await self._request("GET", "payments/" + payment_id)

    async def get_refund(self, refund_id):
        if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", refund_id):
            raise ValueError("invalid refund ID")
        return await self._request("GET", "refunds/" + refund_id)


class BillingService:
    def __init__(self, registry, provider):
        self.registry, self.provider = registry, provider
        self.ledger = ResourceLedger(registry)
        with registry._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS troika_billing_intents (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES troika_users(id) ON DELETE CASCADE,
                key_digest TEXT NOT NULL, sku TEXT NOT NULL, price_rub INTEGER NOT NULL,
                created_at REAL NOT NULL, payment_id TEXT UNIQUE, confirmation_url TEXT,
                state TEXT NOT NULL, grant_id TEXT, starts_at REAL, expires_at REAL,
                UNIQUE(user_id,key_digest))""")
            c.execute("""CREATE TABLE IF NOT EXISTS troika_billing_refunds (
                refund_id TEXT PRIMARY KEY, intent_id TEXT NOT NULL
                REFERENCES troika_billing_intents(id) ON DELETE CASCADE,
                amount_rub INTEGER NOT NULL, occurred_at REAL NOT NULL)""")

    @classmethod
    def from_config(cls, registry, config):
        if config.get("product_billing_enabled") is not True:
            raise ValueError("billing is disabled")
        return cls(
            registry,
            YooKassa(
                shop_id=config.get("product_billing_shop_id", ""),
                secret=os.getenv("YOOKASSA_SECRET_KEY", ""),
                return_url=config.get("product_billing_return_url", ""),
                test=config.get("product_billing_test", True),
            ),
        )

    def _intent(self, principal, sku, key):
        if sku not in SKUS or not isinstance(key, str) or not 8 <= len(key) <= 128:
            raise ValueError("invalid payment selection or idempotency key")
        digest = sha256(key.encode()).hexdigest()
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self.registry._require_active_principal(c, principal)
            row = c.execute(
                "SELECT * FROM troika_billing_intents WHERE user_id = ? AND key_digest = ?",
                (principal.user_id, digest),
            ).fetchone()
            if row:
                if row["sku"] != sku:
                    raise ResourceConflict("payment key belongs to another selection")
                return dict(row)
            identifier = str(uuid.uuid4())
            c.execute(
                "INSERT INTO troika_billing_intents (id,user_id,key_digest,sku,price_rub,created_at,state) "
                "VALUES (?,?,?,?,?,?,'created')",
                (
                    identifier,
                    principal.user_id,
                    digest,
                    sku,
                    SKUS[sku][0],
                    datetime.now(timezone.utc).timestamp(),
                ),
            )
            return dict(
                c.execute(
                    "SELECT * FROM troika_billing_intents WHERE id = ?", (identifier,)
                ).fetchone()
            )

    def _validate(self, receipt, intent):
        if (
            not isinstance(receipt, dict)
            or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", str(receipt.get("id", "")))
            or receipt.get("amount", {}).get("currency") != "RUB"
            or Decimal(str(receipt.get("amount", {}).get("value", -1)))
            != intent["price_rub"]
            or receipt.get("metadata", {}).get("troika_intent") != intent["id"]
            or str(receipt.get("recipient", {}).get("account_id", ""))
            != self.provider.shop_id
            or receipt.get("test") is not self.provider.test
            or (intent["payment_id"] and receipt["id"] != intent["payment_id"])
        ):
            raise ValueError("payment receipt does not match the server intent")

    async def checkout(self, principal, *, sku, key):
        intent = self._intent(principal, sku, key)
        if intent["payment_id"]:
            return {
                "id": intent["id"],
                "state": intent["state"],
                "confirmation_url": intent["confirmation_url"],
            }
        if datetime.now(timezone.utc).timestamp() - intent["created_at"] >= 23 * 3600:
            # Provider idempotency storage is finite. Never recreate an unknown
            # charge after its retention window; an operator must reconcile it.
            raise ResourceConflict("unconfirmed payment needs reconciliation")
        receipt = await self.provider.create(intent)
        self._validate(receipt, intent)
        url = checkout_url(receipt.get("confirmation", {}).get("confirmation_url"))
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self.registry._require_active_principal(c, principal)
            c.execute(
                "UPDATE troika_billing_intents SET payment_id = ?, confirmation_url = ?, state = 'pending' "
                "WHERE id = ? AND payment_id IS NULL",
                (receipt["id"], url, intent["id"]),
            )
        return {"id": intent["id"], "state": "pending", "confirmation_url": url}

    async def reconcile(self, payment_id):
        with self.registry._connect() as c:
            row = c.execute(
                "SELECT * FROM troika_billing_intents WHERE payment_id = ?",
                (payment_id,),
            ).fetchone()
        if row is None:
            return False
        intent = dict(row)
        receipt = await self.provider.get(payment_id)
        self._validate(receipt, intent)
        if receipt.get("status") != "succeeded" or receipt.get("paid") is not True:
            return False
        if self.provider.test:
            with self.registry._connect() as c:
                c.execute(
                    "UPDATE troika_billing_intents SET state = 'test_succeeded' WHERE id = ?",
                    (intent["id"],),
                )
            return True
        now = datetime.now(timezone.utc)
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM troika_billing_intents WHERE id = ?", (intent["id"],)
            ).fetchone()
            if row["state"] in {"applied", "refunded"}:
                return True
            user = SimpleNamespace(user_id=row["user_id"])
            plan = c.execute(
                "SELECT plan FROM troika_entitlements WHERE user_id = ?",
                (user.user_id,),
            ).fetchone()[0]
            if row["sku"] == "top_up":
                starts, expires, grant_plan, kind = (
                    now,
                    now + timedelta(days=TOP_UP_DAYS),
                    plan,
                    "top_up",
                )
            else:
                last = c.execute(
                    "SELECT MAX(expires_at) FROM troika_resource_grants WHERE user_id = ? "
                    "AND kind = 'monthly' AND plan IN ('plus','pro') "
                    "AND NOT EXISTS (SELECT 1 FROM troika_resource_revocations r WHERE r.grant_id = troika_resource_grants.id)",
                    (user.user_id,),
                ).fetchone()[0]
                starts = datetime.fromtimestamp(
                    max(now.timestamp(), last or 0), timezone.utc
                )
                # Explicit renewals and plan changes start after paid time ends.
                # Free subsidy ends when the first captured paid period begins.
                if starts == now:
                    c.execute(
                        "UPDATE troika_resource_grants SET expires_at = MAX(starts_at + 0.000001, ?) "
                        "WHERE user_id = ? AND kind = 'monthly' AND plan = 'free' AND expires_at > ?",
                        (now.timestamp(), user.user_id, now.timestamp()),
                    )
                expires = ResourceLedger._next_month(starts.replace(day=1))
                import calendar

                expires = expires.replace(
                    day=min(
                        starts.day, calendar.monthrange(expires.year, expires.month)[1]
                    )
                )
                grant_plan, kind = row["sku"], "monthly"
            grant = self.ledger._grant(
                c,
                user,
                kind=kind,
                event_key="yookassa:" + payment_id,
                starts=starts,
                expires=expires,
                amount=SKUS[row["sku"]][1],
                billing_plan=grant_plan,
            )
            c.execute(
                "UPDATE troika_billing_intents SET state = 'applied', grant_id = ?, starts_at = ?, expires_at = ? "
                "WHERE id = ?",
                (grant, starts.timestamp(), expires.timestamp(), row["id"]),
            )
            self._refresh(c, user.user_id, now.timestamp())
        return True

    async def reconcile_refund(self, refund_id):
        receipt = await self.provider.get_refund(refund_id)
        if receipt.get("id") != refund_id or receipt.get("status") != "succeeded":
            return False
        with self.registry._connect() as c:
            row = c.execute(
                "SELECT * FROM troika_billing_intents WHERE payment_id = ?",
                (receipt.get("payment_id"),),
            ).fetchone()
        if row is None:
            return False
        payment = await self.provider.get(row["payment_id"])
        self._validate(payment, dict(row))
        # Partial refunds need an operator-reviewed proportional settlement;
        # they must not silently revoke the whole paid period.
        if (
            receipt.get("amount", {}).get("currency") != "RUB"
            or Decimal(str(receipt.get("amount", {}).get("value", -1)))
            != row["price_rub"]
        ):
            raise ResourceConflict("partial refund requires operator reconciliation")
        now = datetime.now(timezone.utc).timestamp()
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            current = c.execute(
                "SELECT * FROM troika_billing_intents WHERE id = ?", (row["id"],)
            ).fetchone()
            if c.execute(
                "SELECT 1 FROM troika_billing_refunds WHERE refund_id = ?", (refund_id,)
            ).fetchone():
                return True
            if current["grant_id"]:
                c.execute(
                    "INSERT OR IGNORE INTO troika_resource_revocations VALUES (?,?)",
                    (current["grant_id"], now),
                )
                c.execute(
                    "UPDATE troika_resource_grants SET available = 0, granted = reserved + spent, "
                    "expires_at = MAX(starts_at + 0.000001, ?) WHERE id = ?",
                    (now, current["grant_id"]),
                )
            c.execute(
                "UPDATE troika_billing_intents SET state = 'refunded', expires_at = ? WHERE id = ?",
                (now, current["id"]),
            )
            c.execute(
                "INSERT INTO troika_billing_refunds VALUES (?,?,?,?)",
                (refund_id, current["id"], current["price_rub"], now),
            )
            self._refresh(c, current["user_id"], now)
        return True

    def _refresh(self, c, user_id, now):
        managed = c.execute(
            "SELECT 1 FROM troika_resource_grants WHERE user_id = ? "
            "AND kind = 'monthly' AND plan != 'free' LIMIT 1",
            (user_id,),
        ).fetchone()
        if not managed:
            return
        current = c.execute(
            # Trusted operator beta periods also expire while checkout is off.
            # Resource grants are authoritative; no payment receipt is fabricated.
            "SELECT plan FROM troika_resource_grants WHERE user_id = ? "
            "AND kind = 'monthly' AND plan != 'free' AND starts_at <= ? AND expires_at > ? "
            "AND id NOT IN (SELECT grant_id FROM troika_resource_revocations) "
            "ORDER BY starts_at DESC LIMIT 1",
            (user_id, now, now),
        ).fetchone()
        c.execute(
            "UPDATE troika_entitlements SET plan = ?, updated_at = ? WHERE user_id = ?",
            (current["plan"] if current else "free", now, user_id),
        )

    def refresh(self, principal):
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self.registry._require_active_principal(c, principal)
            self._refresh(c, principal.user_id, datetime.now(timezone.utc).timestamp())

    def status(self, principal, intent_id):
        with self.registry._connect() as c:
            self.registry._require_active_principal(c, principal)
            row = c.execute(
                "SELECT id,sku,price_rub,state,starts_at,expires_at FROM troika_billing_intents "
                "WHERE id = ? AND user_id = ?",
                (intent_id, principal.user_id),
            ).fetchone()
            if row is None:
                raise PermissionError("payment is unavailable")
            return dict(row)
