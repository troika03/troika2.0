import asyncio
import pytest
from troika_product.access import AccessRegistry
from troika_product.verification import VerificationService


class Mailer:
    def __init__(self):
        self.sent = []

    async def send(self, email, code):
        self.sent.append((email, code))


@pytest.fixture
def account(tmp_path):
    registry = AccessRegistry(tmp_path / "access.db")
    owner = registry.create_user("verify@example.com", plan="free")
    device = registry.create_device(owner, name="phone", platform="android")
    principal = registry.authenticate(registry.issue_device_token(device))
    mailer = Mailer()
    service = VerificationService(registry, config={}, secret="x" * 32, mailer=mailer)
    return service, principal, mailer


def test_email_confirmation_does_not_claim_anti_abuse_approval(account):
    service, principal, mailer = account
    request = asyncio.run(service.request(principal))
    assert mailer.sent[0][0] == "verify@example.com"
    result = service.confirm(
        principal, identifier=request["id"], code=mailer.sent[0][1]
    )
    assert result == {"verified": True, "welcome_issued": False}
    assert service.ledger.export_rows(principal)["grants"] == []


def test_reviewed_verified_account_receives_welcome_only_once(account):
    service, principal, mailer = account
    service.config["product_verification_reviewed_users"] = [principal.user_id]
    request = asyncio.run(service.request(principal))
    first = service.confirm(principal, identifier=request["id"], code=mailer.sent[0][1])
    assert first["welcome_issued"]
    service.claim_welcome(principal)
    service.confirm(principal, identifier=request["id"], code=mailer.sent[0][1])
    grants = service.ledger.export_rows(principal)["grants"]
    assert len(grants) == 1 and grants[0]["granted"] == 1000000
    assert grants[0]["expires_at"] - grants[0]["starts_at"] == 14 * 86400


def test_wrong_codes_lock_challenge_and_cannot_be_reset_by_resending(account):
    service, principal, mailer = account
    request = asyncio.run(service.request(principal))
    for _ in range(5):
        assert not service.confirm(principal, identifier=request["id"], code="000000")[
            "verified"
        ]
    assert not service.confirm(
        principal, identifier=request["id"], code=mailer.sent[0][1]
    )["verified"]
    with pytest.raises(ValueError):
        asyncio.run(service.request(principal))


def test_another_owner_cannot_confirm_or_claim_bonus(account):
    service, principal, mailer = account
    request = asyncio.run(service.request(principal))
    other_user = service.registry.create_user("other@example.com", plan="free")
    device = service.registry.create_device(
        other_user, name="other", platform="android"
    )
    other = service.registry.authenticate(service.registry.issue_device_token(device))
    assert not service.confirm(other, identifier=request["id"], code=mailer.sent[0][1])[
        "verified"
    ]
    with pytest.raises(PermissionError):
        service.claim_welcome(other)


def test_email_delivery_failure_never_activates_a_challenge(account):
    service, principal, mailer = account

    async def failed(*args):
        raise TimeoutError

    mailer.send = failed
    with pytest.raises(TimeoutError):
        asyncio.run(service.request(principal))
    with service.registry._connect() as c:
        assert (
            c.execute("SELECT sent FROM troika_email_verification").fetchone()[0] == 0
        )
    assert not service.status(principal)["verified"]


def test_global_fund_exhaustion_does_not_undo_email_confirmation(account):
    service, principal, mailer = account
    service.ledger.subsidy_limit_tokens = 0
    service.config["product_verification_reviewed_users"] = [principal.user_id]
    request = asyncio.run(service.request(principal))
    assert service.confirm(
        principal, identifier=request["id"], code=mailer.sent[0][1]
    ) == {"verified": True, "welcome_issued": False}
    assert service.status(principal)["verified"]


def test_changed_email_requires_new_confirmation_before_welcome(account):
    service, principal, mailer = account
    request = asyncio.run(service.request(principal))
    service.confirm(principal, identifier=request["id"], code=mailer.sent[0][1])
    service.config["product_verification_reviewed_users"] = [principal.user_id]
    with service.registry._connect() as c:
        c.execute(
            "UPDATE troika_users SET email = ? WHERE id = ?",
            ("changed@example.com", principal.user_id),
        )
        c.execute("UPDATE troika_email_verification SET created_at = created_at - 61")
    assert not service.status(principal)["verified"]
    with pytest.raises(PermissionError):
        service.claim_welcome(principal)
    new_request = asyncio.run(service.request(principal))
    assert mailer.sent[-1][0] == "changed@example.com"
    assert not service.status(principal)["verified"]
    result = service.confirm(
        principal, identifier=new_request["id"], code=mailer.sent[-1][1]
    )
    assert result == {"verified": True, "welcome_issued": True}
