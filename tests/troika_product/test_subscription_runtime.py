"""Behaviour checks for account budgets, voice receipts and captured payments."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import io
import json
import wave

import pytest

from agent.provider_metering import ProviderCallBlocked
from troika_product.access import AccessRegistry
from troika_product.billing import BillingService, checkout_url
from troika_product.resource_ledger import (
    ConcurrencyLimitExceeded,
    FeatureLimitExceeded,
    ResourceConflict,
    ResourceLedger,
    ResourceLimitExceeded,
    RunBudgetExceeded,
)
from troika_product.service_metering import ServiceMeter, audio_duration


@pytest.fixture
def account(tmp_path):
    registry = AccessRegistry(tmp_path / "access.db")
    owner = registry.create_user("subscription@example.com", plan="free")
    device = registry.create_device(owner, name="phone", platform="android")
    principal = registry.authenticate(registry.issue_device_token(device))
    return registry, ResourceLedger(registry), principal


def test_zero_price_model_does_not_bypass_an_exhausted_cloud_budget(account):
    registry, ledger, principal = account
    balance = ledger.summary(principal)["remaining"]
    hold = ledger.reserve(principal, operation_key="spend-all", run_key="spent-run",
                          kind="llm", tokens=balance, pricing_version="test")
    ledger.mark_dispatched(principal, hold.id)
    ledger.settle(principal, hold.id, charged_tokens=balance, successful=True)
    with pytest.raises(ResourceLimitExceeded):
        ledger.reserve(principal, operation_key="free-inference", run_key="new-run",
                       kind="llm", tokens=0, pricing_version="free-price")
    # Reading/rendering an existing result remains available after exhaustion.
    voice = ServiceMeter(ledger, principal, run_key="read-existing", prices={
        "edge:tts": {"version":"free-price", "unit":"characters", "rub_per_unit":0,
                     "maximum_units":2000}}).begin("edge:tts", 5, kind="tts")
    voice.succeeded(5)
    assert ledger.summary(principal)["remaining"] == 0


def hold(ledger, principal, key, *, run="run", feature=None, ceiling=None, amount=100):
    return ledger.reserve(
        principal,
        operation_key=key,
        run_key=run,
        kind="tool",
        tokens=amount,
        pricing_version="test",
        feature=feature,
        run_token_limit=ceiling,
    )


def settle(ledger, principal, reservation, amount=0, successful=True):
    ledger.mark_dispatched(principal, reservation.id)
    ledger.settle(
        principal, reservation.id, charged_tokens=amount, successful=successful
    )


def test_feature_counts_whole_run_and_releases_failed_result(account):
    _, ledger, principal = account
    for run in ("one", "two", "three"):
        for step in range(4):
            settle(
                ledger,
                principal,
                hold(ledger, principal, f"{run}-{step}", run=run, feature="documents"),
            )
    assert ledger.summary(principal)["feature_usage"]["documents"] == 3
    with pytest.raises(FeatureLimitExceeded):
        hold(ledger, principal, "four", run="four", feature="documents")
    settle(
        ledger,
        principal,
        hold(ledger, principal, "extra-step", run="one", feature="documents"),
    )
    assert ledger.summary(principal)["feature_usage"]["documents"] == 3


def test_feature_quota_cannot_race_across_devices(account):
    _, ledger, principal = account

    def claim(index):
        try:
            hold(ledger, principal, str(index), run=str(index), feature="documents")
            return True
        except FeatureLimitExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(claim, range(8))) == 3


def test_task_ceiling_includes_pending_spending_but_releases_unused_hold(account):
    _, ledger, principal = account
    first = hold(ledger, principal, "a", ceiling=150)
    with pytest.raises(RunBudgetExceeded):
        hold(ledger, principal, "b", ceiling=150)
    settle(ledger, principal, first, 20)
    second = hold(ledger, principal, "b", ceiling=150)
    ledger.mark_dispatched(principal, second.id)
    with pytest.raises(RunBudgetExceeded):
        hold(ledger, principal, "c", ceiling=150)
    assert ledger.summary(principal)["reserved"] == 100


def test_concurrency_slots_are_shared_and_expiry_never_refunds(account):
    _, ledger, principal = account
    now = datetime.now(timezone.utc)
    ledger.start_run(principal, "a", now=now)
    unknown = hold(ledger, principal, "sent", run="a")
    ledger.mark_dispatched(principal, unknown.id)
    with pytest.raises(ConcurrencyLimitExceeded):
        ledger.start_run(principal, "b", now=now)
    with pytest.raises(ResourceConflict):
        ledger.start_run(principal, "a", now=now)
    ledger.start_run(principal, "b", now=now + timedelta(seconds=181))
    assert ledger.summary(principal)["reserved"] == 100
    ledger.finish_run(principal, "b")
    ledger.start_run(principal, "c", now=now + timedelta(seconds=181))


def test_subsidy_cap_retains_anonymous_issuance_after_grant_deletion(account):
    registry, _, principal = account
    ledger = ResourceLedger(registry, subsidy_limit_tokens=500000)
    ledger.summary(principal)
    with registry._connect() as c:
        c.execute(
            "DELETE FROM troika_resource_grants WHERE user_id = ?", (principal.user_id,)
        )
    assert ledger.summary(principal)["monthly_limit"] == 0
    assert ledger.summary(principal)["remaining"] == 0
    with registry._connect() as c:
        assert (
            c.execute("SELECT SUM(amount) FROM troika_resource_subsidies").fetchone()[0]
            == 500000
        )


def test_exhausted_free_fund_does_not_block_purchased_topups(account):
    registry, _, principal = account
    ledger = ResourceLedger(registry, subsidy_limit_tokens=0)
    ledger.grant_top_up(
        principal,
        at=datetime.now(timezone.utc),
        event_key="paid",
        payment_confirmed=True,
    )
    summary = ledger.summary(principal)
    assert summary["monthly_limit"] == 0
    assert summary["remaining"] == 1_000_000
    settle(ledger, principal, hold(ledger, principal, "paid-call"), 50)
    assert ledger.summary(principal)["remaining"] == 999950


def prices(rate="0.002", minimum=10):
    return {
        "groq:whisper": {
            "version": "voice-v1",
            "unit": "seconds",
            "rub_per_unit": rate,
            "minimum_units": minimum,
            "maximum_units": 180,
        }
    }


def test_voice_minimum_rounding_and_numerical_receipt(account):
    _, ledger, principal = account
    meter = ServiceMeter(ledger, principal, run_key="voice", prices=prices())
    lease = meter.begin("groq:whisper", 3, kind="stt")
    lease.succeeded(2)
    summary = ledger.summary(principal)
    assert summary["spent"] == 667  # ceil(10 seconds * .002 RUB / 30 * 1M)
    assert summary["reserved"] == 0
    assert (
        json.loads(ledger.export_rows(principal)["operations"][0]["usage_json"])[
            "service_usage"
        ]["units"]
        == "10"
    )


@pytest.mark.parametrize("measured", [None, -1, "NaN", 4])
def test_unknown_voice_bill_retains_reservation(account, measured):
    _, ledger, principal = account
    lease = ServiceMeter(ledger, principal, run_key="voice", prices=prices()).begin(
        "groq:whisper", 3, kind="stt"
    )
    with pytest.raises(ProviderCallBlocked):
        lease.succeeded(measured)
    assert ledger.summary(principal)["reserved"] == 667


def test_unpriced_voice_never_creates_operation(account):
    _, ledger, principal = account
    with pytest.raises(ProviderCallBlocked):
        ServiceMeter(ledger, principal, run_key="voice", prices={}).begin(
            "groq:whisper", 3, kind="stt"
        )
    assert ledger.export_rows(principal)["operations"] == []


def test_accounting_coefficients_cannot_change_inside_a_period(account):
    _, ledger, principal = account
    first = ServiceMeter(ledger, principal, run_key="voice", prices=prices()).begin(
        "groq:whisper", 3, kind="stt"
    )
    first.succeeded(2)
    before = ledger.summary(principal)["remaining"]
    changed = prices("0.004")
    changed["groq:whisper"]["version"] = "voice-v2"
    with pytest.raises(ProviderCallBlocked) as error:
        ServiceMeter(ledger, principal, run_key="next", prices=changed).begin(
            "groq:whisper", 3, kind="stt"
        )
    assert error.value.code == "resource_price_change_requires_approval"
    assert ledger.summary(principal)["remaining"] == before


@pytest.mark.parametrize("approved", [True, False])
def test_expensive_step_requires_explicit_budget_consent(
    account, monkeypatch, approved
):
    from troika_product.resource_runtime import ResourceRuntime

    registry, ledger, principal = account
    runtime = ResourceRuntime(
        registry,
        principal,
        run_key="budget",
        config={"product_resource_task_tokens": 100},
    )
    seen = []

    def approval(action, description, **kwargs):
        seen.append((action, description, kwargs))
        return {"approved": approved, "user_consent": approved}

    monkeypatch.setattr("tools.approval.request_gateway_approval", approval)
    if approved:
        runtime.approve_resource_cost(200)
        assert runtime.run_token_limit == 200
    else:
        with pytest.raises(ProviderCallBlocked):
            runtime.approve_resource_cost(200)
        assert runtime.run_token_limit == 100
    assert len(seen) == 1 and seen[0][0] == "resource_budget"
    assert "200" in seen[0][1]
    assert seen[0][2]["choices"] == ("once", "deny")
    assert ledger.export_rows(principal)["operations"] == []


def wav(seconds):
    result = io.BytesIO()
    with wave.open(result, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\x00\x00" * int(seconds * 16000))
    return result.getvalue()


def test_audio_duration_uses_decoded_bytes():
    assert audio_duration(wav(1.5)) == Decimal("1.5")
    with pytest.raises(ProviderCallBlocked):
        audio_duration(wav(181))


class Provider:
    shop_id = "123"
    test = False

    def __init__(self):
        self.receipts = {}
        self.created = 0

    async def create(self, intent):
        self.created += 1
        identifier = "provider-" + intent["id"]
        receipt = {
            "id": identifier,
            "amount": {"currency": "RUB", "value": f"{intent['price_rub']}.00"},
            "metadata": {"troika_intent": intent["id"]},
            "recipient": {"account_id": "123"},
            "test": self.test,
            "status": "pending",
            "paid": False,
            "confirmation": {
                "confirmation_url": "https://yoomoney.ru/checkout/" + intent["id"]
            },
        }
        self.receipts[identifier] = receipt
        return receipt

    async def get(self, payment_id):
        return self.receipts[payment_id]


def payment(account, sku="plus"):
    registry, ledger, principal = account
    provider = Provider()
    billing = BillingService(registry, provider)
    result = asyncio.run(billing.checkout(principal, sku=sku, key="intent-key"))
    identifier = next(iter(provider.receipts))
    return billing, provider, identifier, result


def test_checkout_does_not_issue_resource_and_reuses_payment_key(account):
    billing, provider, _, result = payment(account)
    principal = account[2]
    assert billing.ledger.export_rows(principal)["grants"] == []
    assert (
        asyncio.run(billing.checkout(principal, sku="plus", key="intent-key")) == result
    )
    assert provider.created == 1
    with pytest.raises(ResourceConflict):
        asyncio.run(billing.checkout(principal, sku="pro", key="intent-key"))


def test_only_canonical_captured_payment_issues_once_and_survives_logout(account):
    billing, provider, identifier, _ = payment(account)
    principal = account[2]
    assert not asyncio.run(billing.reconcile(identifier))
    provider.receipts[identifier].update(status="succeeded", paid=True)
    with account[0]._connect() as c:
        c.execute(
            "UPDATE troika_api_tokens SET revoked_at = 1 WHERE id = ?",
            (principal.token_id,),
        )
    assert asyncio.run(billing.reconcile(identifier))
    assert asyncio.run(billing.reconcile(identifier))
    with account[0]._connect() as c:
        assert (
            c.execute("SELECT SUM(granted) FROM troika_resource_grants").fetchone()[0]
            == 5_000_000
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("paid", False),
        ("test", True),
        ("recipient", {"account_id": "other"}),
        ("amount", {"currency": "RUB", "value": "1.00"}),
        ("metadata", {"troika_intent": "other"}),
    ],
)
def test_forged_or_wrong_payment_never_grants(account, field, value):
    billing, provider, identifier, _ = payment(account)
    provider.receipts[identifier].update(status="succeeded", paid=True)
    provider.receipts[identifier][field] = value
    try:
        assert not asyncio.run(billing.reconcile(identifier))
    except ValueError:
        pass
    assert billing.ledger.export_rows(account[2])["grants"] == []


def test_test_payments_never_issue_live_resource(account):
    registry, ledger, principal = account
    provider = Provider()
    provider.test = True
    billing = BillingService(registry, provider)
    asyncio.run(billing.checkout(principal, sku="plus", key="test-payment"))
    identifier = next(iter(provider.receipts))
    provider.receipts[identifier].update(status="succeeded", paid=True)
    assert asyncio.run(billing.reconcile(identifier))
    assert ledger.export_rows(principal)["grants"] == []


def test_first_paid_period_replaces_free_and_next_plan_is_queued(account):
    registry, ledger, principal = account
    ledger.summary(principal)
    billing, provider, identifier, result = payment(account)
    provider.receipts[identifier].update(status="succeeded", paid=True)
    asyncio.run(billing.reconcile(identifier))
    assert ledger.summary(principal)["remaining"] == 5_000_000
    next_payment = asyncio.run(
        billing.checkout(principal, sku="pro", key="next-period")
    )
    second = next(key for key in provider.receipts if key != identifier)
    provider.receipts[second].update(status="succeeded", paid=True)
    asyncio.run(billing.reconcile(second))
    first = billing.status(principal, result["id"])
    future = billing.status(principal, next_payment["id"])
    assert future["starts_at"] == first["expires_at"]
    assert ledger.summary(principal)["plan"] == "plus"
    assert ledger.summary(principal)["remaining"] == 5_000_000


def test_paid_expiry_returns_to_free_without_refilling_old_paid_resource(account):
    registry, ledger, principal = account
    ledger.summary(principal)
    billing, provider, identifier, result = payment(account)
    provider.receipts[identifier].update(status="succeeded", paid=True)
    asyncio.run(billing.reconcile(identifier))
    expiry = billing.status(principal, result["id"])["expires_at"]
    with registry._connect() as c:
        billing._refresh(c, principal.user_id, expiry)
    summary = ledger.summary(
        principal, now=datetime.fromtimestamp(expiry, timezone.utc)
    )
    assert summary["plan"] == "free"
    assert summary["remaining"] == 500000
    assert summary["spent"] == 0


def test_operator_period_expires_with_checkout_disabled_without_fake_payment(account):
    registry, ledger, principal = account
    registry.set_entitlement(principal.user_id, plan="pro", daily_request_limit=1)
    starts = datetime.now(timezone.utc)
    expires = starts + timedelta(days=30)
    ledger.grant_monthly(principal, starts_at=starts, expires_at=expires,
                         event_key="operator-beta-period")
    billing = BillingService(registry, None)
    billing.refresh(principal)
    assert ledger.summary(principal)["remaining"] == 10000000
    with registry._connect() as c:
        assert c.execute("SELECT count(*) FROM troika_billing_intents").fetchone()[0] == 0
        billing._refresh(c, principal.user_id, expires.timestamp())
    summary = ledger.summary(principal, now=expires)
    assert summary["plan"] == "free"
    assert summary["remaining"] == 500000


def test_full_refund_revokes_unused_credit_once(account):
    billing, provider, identifier, result = payment(account, "top_up")
    provider.receipts[identifier].update(status="succeeded", paid=True)
    asyncio.run(billing.reconcile(identifier))

    async def refund(refund_id):
        return {
            "id": refund_id,
            "status": "succeeded",
            "payment_id": identifier,
            "amount": {"currency": "RUB", "value": "99.00"},
        }

    provider.get_refund = refund
    assert asyncio.run(billing.reconcile_refund("refund-1"))
    assert asyncio.run(billing.reconcile_refund("refund-1"))
    assert billing.status(account[2], result["id"])["state"] == "refunded"
    assert billing.ledger.summary(account[2])["remaining"] == 500000


def test_late_provider_receipt_cannot_restore_refunded_resource(account):
    billing, provider, identifier, result = payment(account, "top_up")
    provider.receipts[identifier].update(status="succeeded", paid=True)
    asyncio.run(billing.reconcile(identifier))
    ledger, principal = account[1], account[2]
    # Free expires sooner, so spend it before reserving purchased resource.
    settle(ledger, principal, hold(ledger, principal, "free", amount=500000), 500000)
    pending = hold(ledger, principal, "sent-topup", amount=1000)
    ledger.mark_dispatched(principal, pending.id)

    async def refund(refund_id):
        return {
            "id": refund_id,
            "status": "succeeded",
            "payment_id": identifier,
            "amount": {"currency": "RUB", "value": "99.00"},
        }

    provider.get_refund = refund
    asyncio.run(billing.reconcile_refund("refund-with-hold"))
    ledger.settle(principal, pending.id, charged_tokens=20)
    assert ledger.summary(principal)["remaining"] == 0
    assert billing.status(principal, result["id"])["state"] == "refunded"


@pytest.mark.parametrize(
    "url",
    [
        "http://yoomoney.ru/pay",
        "https://yoomoney.ru.evil.test/",
        "https://evil.test/",
        "https://u:p@yoomoney.ru/pay",
    ],
)
def test_payment_browser_destination_is_allowlisted(url):
    with pytest.raises(ValueError):
        checkout_url(url)


@pytest.mark.asyncio
async def test_subscription_http_shares_voice_cost_and_preserves_legacy_gate(account):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from gateway.config import PlatformConfig
    from gateway.platforms.api_server import APIServerAdapter

    registry, ledger, principal = account
    token = registry.issue_device_token(principal.device_id)
    adapter = APIServerAdapter(
        PlatformConfig(
            enabled=True,
            extra={
                "product_auth_enabled": True,
                "product_auth_db": str(registry.database_path),
                "product_resource_enabled": True,
            },
        )
    )
    lease = ServiceMeter(ledger, principal, run_key="voice", prices=prices()).begin(
        "groq:whisper", 3, kind="stt"
    )
    lease.succeeded(2)
    app = web.Application()
    app.router.add_get("/v1/subscription", adapter._handle_subscription)
    app.router.add_get("/v1/billing", adapter._handle_billing_catalogue)
    async with TestClient(TestServer(app)) as client:
        headers = {"Authorization": "Bearer " + token}
        response = await client.get("/v1/subscription", headers=headers)
        assert response.status == 200
        body = (await response.json())["subscription"]
        assert body["unit"] == "calculated_ai_tokens"
        assert body["remaining"] == 500000 - 667
        assert body["spent"] == 667
        assert body["resource_enforced"]
        assert (
            body["recent_operations"][0]["usage"]["service_usage"]["cost_rub"]
            == "0.020"
        )
        assert response.headers["Cache-Control"] == "private, no-store"
        catalog = await (await client.get("/v1/billing", headers=headers)).json()
        assert catalog["enabled"] is False
        assert catalog["automatic_renewal"] is False
        assert [offer["price_rub"] for offer in catalog["offers"]] == [790, 1490, 99]
        adapter._product_resource_enabled = False
        old = (await (await client.get("/v1/subscription", headers=headers)).json())[
            "subscription"
        ]
        assert not old.get("resource_enforced", False)


def test_payment_status_cannot_be_read_by_another_account(account):
    registry, _, principal = account
    billing, provider, _, result = payment(account)
    other_user = registry.create_user("other@example.com", plan="free")
    device = registry.create_device(other_user, name="other", platform="android")
    other = registry.authenticate(registry.issue_device_token(device))
    with pytest.raises(PermissionError):
        billing.status(other, result["id"])
