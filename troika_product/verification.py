"""Owner-bound email confirmation and explicitly eligible welcome grants.

Challenges contain HMACs, never plaintext codes. A valid email alone does not
claim anti-abuse approval: closed-beta review or a captured payment is required.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import hashlib
import hmac
import os
import secrets
import smtplib
import ssl
import time
import uuid

from troika_product.resource_ledger import SubsidyUnavailable
from troika_product.resource_runtime import configured_ledger
from troika_product.subscription_policy import WELCOME_DAYS, WELCOME_TOKENS


class SMTPMailer:
    def __init__(self, config):
        self.host = config.get("product_verification_smtp_host", "")
        self.port = config.get("product_verification_smtp_port", 465)
        self.sender = config.get("product_verification_sender", "")
        self.username = config.get("product_verification_smtp_username", "")
        self.password = os.getenv("TROIKA_SMTP_PASSWORD", "")
        self.implicit_tls = config.get("product_verification_smtp_ssl", True)
        if (
            not self.host
            or not self.sender
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
            or type(self.implicit_tls) is not bool
        ):
            raise ValueError("email service is not configured")

    def _send(self, recipient, code):
        message = EmailMessage()
        message["From"], message["To"] = self.sender, recipient
        message["Subject"] = "Подтверждение почты в Тройке"
        message.set_content(
            f"Код подтверждения: {code}\nДействует 10 минут. Никому не сообщайте код."
        )
        context = ssl.create_default_context()
        if self.implicit_tls:
            connection = smtplib.SMTP_SSL(
                self.host, self.port, timeout=15, context=context
            )
        else:
            connection = smtplib.SMTP(self.host, self.port, timeout=15)
            connection.starttls(context=context)
        with connection:
            if self.username:
                connection.login(self.username, self.password)
            connection.send_message(message)

    async def send(self, recipient, code):
        await asyncio.to_thread(self._send, recipient, code)


class VerificationService:
    def __init__(self, registry, *, config, secret, mailer):
        if not isinstance(secret, str) or len(secret) < 32:
            raise ValueError("verification secret is not configured")
        self.registry, self.config, self.secret, self.mailer = (
            registry,
            config,
            secret.encode(),
            mailer,
        )
        self.ledger = configured_ledger(registry, config)
        with registry._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS troika_email_verification (
                user_id TEXT PRIMARY KEY REFERENCES troika_users(id) ON DELETE CASCADE,
                challenge_id TEXT NOT NULL, code_digest TEXT NOT NULL, email_digest TEXT NOT NULL,
                created_at REAL NOT NULL, expires_at REAL NOT NULL, sent INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0, day TEXT NOT NULL, day_count INTEGER NOT NULL,
                verified_at REAL)""")

    @classmethod
    def from_config(cls, registry, config):
        if config.get("product_verification_enabled") is not True:
            raise ValueError("verification is disabled")
        return cls(
            registry,
            config=config,
            secret=os.getenv("TROIKA_EMAIL_VERIFICATION_SECRET", ""),
            mailer=SMTPMailer(config),
        )

    def _digest(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def _eligible(self, c, user_id):
        if user_id in self.config.get("product_verification_reviewed_users", []):
            return True
        if c.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'troika_billing_intents'"
        ).fetchone():
            return bool(
                c.execute(
                    "SELECT 1 FROM troika_billing_intents WHERE user_id = ? AND state = 'applied' AND price_rub > 0 LIMIT 1",
                    (user_id,),
                ).fetchone()
            )
        return False

    def status(self, principal):
        with self.registry._connect() as c:
            self.registry._require_active_principal(c, principal)
            row = c.execute(
                "SELECT verified_at, email_digest FROM troika_email_verification WHERE user_id = ?",
                (principal.user_id,),
            ).fetchone()
            email = c.execute(
                "SELECT email FROM troika_users WHERE id = ?", (principal.user_id,)
            ).fetchone()[0]
            welcome = c.execute(
                "SELECT 1 FROM troika_resource_grants WHERE user_id = ? AND kind = 'welcome'",
                (principal.user_id,),
            ).fetchone()
            return {
                "verified": bool(row and row[0] and row[1] == self._digest(email)),
                "welcome_issued": bool(welcome),
                "eligible": self._eligible(c, principal.user_id),
            }

    async def request(self, principal):
        now = time.time()
        day = datetime.now(timezone.utc).date().isoformat()
        identifier, code = str(uuid.uuid4()), str(secrets.randbelow(900000) + 100000)
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self.registry._require_active_principal(c, principal)
            email = c.execute(
                "SELECT email FROM troika_users WHERE id = ?", (principal.user_id,)
            ).fetchone()[0]
            row = c.execute(
                "SELECT * FROM troika_email_verification WHERE user_id = ?",
                (principal.user_id,),
            ).fetchone()
            if row and row["verified_at"] and row["email_digest"] == self._digest(email):
                return {"verified": True}
            count = row["day_count"] if row and row["day"] == day else 0
            if row and now - row["created_at"] < 60 or count >= 5:
                raise ValueError("verification request rate limit exceeded")
            c.execute(
                "INSERT INTO troika_email_verification VALUES (?,?,?,?,?,?,0,0,?,?,NULL) "
                "ON CONFLICT(user_id) DO UPDATE SET challenge_id=excluded.challenge_id,code_digest=excluded.code_digest,"
                "email_digest=excluded.email_digest,created_at=excluded.created_at,expires_at=excluded.expires_at,"
                "sent=0,attempts=0,day=excluded.day,day_count=excluded.day_count,verified_at=NULL",
                (
                    principal.user_id,
                    identifier,
                    self._digest(identifier + ":" + code),
                    self._digest(email),
                    now,
                    now + 600,
                    day,
                    count + 1,
                ),
            )
        await self.mailer.send(email, code)
        with self.registry._connect() as c:
            c.execute(
                "UPDATE troika_email_verification SET sent = 1 WHERE user_id = ? AND challenge_id = ?",
                (principal.user_id, identifier),
            )
        return {"id": identifier, "expires_in": 600}

    def _welcome(self, c, principal):
        existing = c.execute(
            "SELECT 1 FROM troika_resource_grants WHERE user_id = ? AND kind = 'welcome'",
            (principal.user_id,),
        ).fetchone()
        if existing:
            return True
        if not self._eligible(c, principal.user_id):
            return False
        start = datetime.now(timezone.utc)
        try:
            self.ledger._grant(
                c,
                principal,
                kind="welcome",
                event_key="verified-welcome:" + principal.user_id,
                starts=start,
                expires=start + timedelta(days=WELCOME_DAYS),
                amount=WELCOME_TOKENS,
            )
            return True
        except (SubsidyUnavailable, ValueError):
            return False

    def confirm(self, principal, *, identifier, code):
        if (
            not isinstance(identifier, str)
            or not isinstance(code, str)
            or len(code) != 6
            or not code.isascii()
            or not code.isdigit()
        ):
            raise ValueError("invalid confirmation")
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self.registry._require_active_principal(c, principal)
            row = c.execute(
                "SELECT * FROM troika_email_verification WHERE user_id = ? AND challenge_id = ?",
                (principal.user_id, identifier),
            ).fetchone()
            email = c.execute(
                "SELECT email FROM troika_users WHERE id = ?", (principal.user_id,)
            ).fetchone()[0]
            if (
                not row
                or not row["sent"]
                or row["expires_at"] <= time.time()
                or row["attempts"] >= 5
                or row["email_digest"] != self._digest(email)
            ):
                return {"verified": False, "welcome_issued": False}
            if not hmac.compare_digest(
                row["code_digest"], self._digest(identifier + ":" + code)
            ):
                c.execute(
                    "UPDATE troika_email_verification SET attempts = attempts + 1 WHERE user_id = ?",
                    (principal.user_id,),
                )
                return {"verified": False, "welcome_issued": False}
            c.execute(
                "UPDATE troika_email_verification SET verified_at = COALESCE(verified_at, ?) WHERE user_id = ?",
                (time.time(), principal.user_id),
            )
            return {"verified": True, "welcome_issued": self._welcome(c, principal)}

    def claim_welcome(self, principal):
        with self.registry._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self.registry._require_active_principal(c, principal)
            row = c.execute(
                "SELECT verified_at, email_digest FROM troika_email_verification WHERE user_id = ?",
                (principal.user_id,),
            ).fetchone()
            email = c.execute(
                "SELECT email FROM troika_users WHERE id = ?", (principal.user_id,)
            ).fetchone()[0]
            if not row or not row[0] or row[1] != self._digest(email):
                raise PermissionError("verified email is required")
            return {"verified": True, "welcome_issued": self._welcome(c, principal)}
