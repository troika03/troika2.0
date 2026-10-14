"""Financial, concurrency and owner-scope invariants for resource accounting."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from troika_product.access import AccessPrincipal, AccessRegistry
from troika_product.resource_ledger import (
    FeatureLimitExceeded,
    ResourceConflict,
    ResourceLedger,
    ResourceLimitExceeded,
)
from troika_product.subscription_policy import (
    TokenPrices,
    TokenUsage,
    UnknownResourcePrice,
    plan_policy,
    resource_tokens_for_cost,
)


NOW = datetime(2026, 10, 12, 10, tzinfo=timezone.utc)
NOV = datetime(2026, 11, 1, tzinfo=timezone.utc)


@pytest.fixture
def account(tmp_path):
    registry = AccessRegistry(tmp_path / "access.db")
    owner = registry.create_user("resource@example.com", plan="free")
    device = registry.create_device(owner, name="phone", platform="android")
    principal = registry.authenticate(registry.issue_device_token(device))
    assert principal is not None
    return registry, ResourceLedger(registry), principal


def reserve(ledger, principal, key="call", tokens=100_000, **kwargs):
    return ledger.reserve(
        principal,
        operation_key=key,
        run_key=kwargs.pop("run_key", "run"),
        kind="llm",
        tokens=tokens,
        pricing_version="test-v1",
        now=NOW,
        **kwargs,
    )


def settle(ledger, principal, hold, charged=10_000, **kwargs):
    ledger.mark_dispatched(principal, hold.id)
    return ledger.settle(principal, hold.id, charged_tokens=charged, now=NOW, **kwargs)


def test_reserve_then_measure_releases_only_unused_amount(account):
    _, ledger, principal = account
    hold = reserve(ledger, principal)
    assert ledger.summary(principal, now=NOW)["remaining"] == 400_000
    assert ledger.summary(principal, now=NOW)["reserved"] == 100_000
    receipt = settle(
        ledger, principal, hold, usage=TokenUsage(7000, 500, reasoning_tokens=200)
    )
    result = ledger.summary(principal, now=NOW)
    assert receipt.charged_tokens == 10_000
    assert (result["remaining"], result["reserved"], result["spent"]) == (
        490_000,
        0,
        10_000,
    )


def test_identical_retries_never_reserve_or_settle_twice(account):
    _, ledger, principal = account
    hold = reserve(ledger, principal)
    assert reserve(ledger, principal) == hold
    receipt = settle(ledger, principal, hold)
    assert reserve(ledger, principal) == receipt
    assert ledger.settle(principal, hold.id, charged_tokens=10_000, now=NOW) == receipt
    assert ledger.summary(principal, now=NOW)["spent"] == 10_000
    with pytest.raises(ResourceConflict):
        reserve(ledger, principal, tokens=200_000)
    with pytest.raises(ResourceConflict):
        ledger.settle(principal, hold.id, charged_tokens=20_000, now=NOW)


def test_two_devices_cannot_spend_the_same_last_resource(account):
    registry, ledger, principal = account
    device = registry.create_device(principal.user_id, name="pc", platform="windows")
    second = registry.authenticate(registry.issue_device_token(device))
    assert second is not None

    def attempt(i):
        try:
            return reserve(
                ledger, principal if i % 2 else second, key=str(i), tokens=500_000
            )
        except ResourceLimitExceeded:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        accepted = list(pool.map(attempt, range(16)))
    assert sum(x is not None for x in accepted) == 1
    assert ledger.summary(principal, now=NOW)["remaining"] == 0


def test_concurrent_idempotent_callbacks_debit_once(account):
    _, ledger, principal = account
    hold = reserve(ledger, principal)
    ledger.mark_dispatched(principal, hold.id)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: ledger.settle(
                    principal, hold.id, charged_tokens=40_000, now=NOW
                ),
                range(16),
            )
        )
    assert len(set(results)) == 1
    assert ledger.summary(principal, now=NOW)["spent"] == 40_000


def test_only_one_worker_can_claim_the_provider_dispatch(account):
    _, ledger, principal = account
    hold = reserve(ledger, principal)

    def dispatch(_):
        try:
            return ledger.mark_dispatched(principal, hold.id)
        except ResourceConflict:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(dispatch, range(16)))
    assert sum(claim is not None for claim in claims) == 1
    assert reserve(ledger, principal).state == "dispatched"
    assert ledger.summary(principal, now=NOW)["reserved"] == 100_000


def test_parent_child_voice_and_tool_share_one_budget(account):
    _, ledger, principal = account
    for kind in ("llm", "stt", "tts", "tool"):
        ledger.reserve(
            principal,
            operation_key=kind,
            run_key="same-parent",
            kind=kind,
            tokens=125_000,
            pricing_version="test",
            now=NOW,
        )
    with pytest.raises(ResourceLimitExceeded):
        reserve(ledger, principal, key="child", tokens=1)
    assert ledger.summary(principal, now=NOW)["reserved"] == 500_000


def test_unknown_billing_survives_restart_without_releasing_hold(account):
    registry, ledger, principal = account
    hold = reserve(ledger, principal, tokens=500_000)
    ledger.mark_dispatched(principal, hold.id)
    restored = ResourceLedger(registry)
    with pytest.raises(ResourceConflict):
        restored.release_before_dispatch(principal, hold.id)
    with pytest.raises(ResourceLimitExceeded):
        reserve(restored, principal, key="retry", tokens=1)
    assert restored.summary(principal, now=NOW)["reserved"] == 500_000


def test_pre_dispatch_failure_returns_hold_idempotently(account):
    _, ledger, principal = account
    hold = reserve(ledger, principal)
    receipt = ledger.release_before_dispatch(principal, hold.id)
    assert ledger.release_before_dispatch(principal, hold.id) == receipt
    assert ledger.summary(principal, now=NOW)["remaining"] == 500_000
    with pytest.raises(ResourceConflict):
        ledger.mark_dispatched(principal, hold.id)
    with pytest.raises(ResourceConflict):
        ledger.settle(principal, hold.id, charged_tokens=0)


def test_provider_upper_bound_violation_keeps_hold_and_fails_closed(account):
    _, ledger, principal = account
    hold = reserve(ledger, principal, tokens=100)
    ledger.mark_dispatched(principal, hold.id)
    with pytest.raises(ResourceLimitExceeded):
        ledger.settle(principal, hold.id, charged_tokens=101)
    assert ledger.summary(principal, now=NOW)["reserved"] == 100


def test_expired_month_cannot_leak_or_debit_next_month(account):
    _, ledger, principal = account
    hold = reserve(ledger, principal, tokens=500_000)
    ledger.mark_dispatched(principal, hold.id)
    assert ledger.summary(principal, now=NOV)["remaining"] == 500_000
    ledger.settle(principal, hold.id, charged_tokens=400_000, now=NOV)
    result = ledger.summary(principal, now=NOV)
    assert (result["remaining"], result["reserved"], result["spent"]) == (500_000, 0, 0)
    with pytest.raises(ResourceLimitExceeded):
        reserve(ledger, principal, key="old-month", tokens=600_000)


def test_feature_cap_counts_pending_and_success_but_returns_failed_slot(account):
    _, ledger, principal = account
    holds = [
        reserve(ledger, principal, key=str(i), run_key=str(i), tokens=1, feature="documents")
        for i in range(3)
    ]
    with pytest.raises(FeatureLimitExceeded):
        reserve(ledger, principal, key="fourth", run_key="fourth", tokens=1, feature="documents")
    settle(ledger, principal, holds[0], charged=0, successful=False)
    last = reserve(ledger, principal, key="replacement", run_key="replacement", tokens=1, feature="documents")
    for hold in (*holds[1:], last):
        settle(ledger, principal, hold, charged=1)
    with pytest.raises(FeatureLimitExceeded):
        reserve(ledger, principal, key="fifth", run_key="fifth", tokens=1, feature="documents")
    assert ledger.summary(principal, now=NOW)["feature_usage"]["documents"] == 3
    fresh = ledger.reserve(
        principal,
        operation_key="new-month-doc",
        run_key="run",
        kind="llm",
        tokens=1,
        feature="documents",
        pricing_version="test",
        now=NOV,
    )
    assert fresh.state == "reserved"


@pytest.mark.parametrize("feature", ["development", "deep_research", "premium"])
def test_free_cannot_buy_plan_features_with_bonus_resource(account, feature):
    _, ledger, principal = account
    ledger.grant_welcome(
        principal, at=NOW, event_key="verified", verification_confirmed=True
    )
    with pytest.raises(FeatureLimitExceeded):
        reserve(ledger, principal, feature=feature)


def test_paid_period_requires_actual_activation_and_uses_invoice_date(account):
    registry, ledger, principal = account
    registry.set_entitlement(principal.user_id, plan="plus", daily_request_limit=100)
    with pytest.raises(ResourceLimitExceeded):
        reserve(ledger, principal)
    end = NOW.replace(month=11)
    first = ledger.grant_monthly(
        principal, starts_at=NOW, expires_at=end, event_key="invoice-1"
    )
    assert (
        ledger.grant_monthly(
            principal, starts_at=NOW, expires_at=end, event_key="invoice-1"
        )
        == first
    )
    result = ledger.summary(principal, now=NOW)
    assert result["resets_at"] == end.isoformat()
    assert result["remaining"] == 5_000_000
    assert ledger.summary(principal, now=NOV)["remaining"] == 5_000_000
    with pytest.raises(ResourceLimitExceeded):
        ledger.summary(principal, now=end)
    with pytest.raises(ResourceConflict):
        ledger.grant_monthly(
            principal, starts_at=NOW, expires_at=end, event_key="different-invoice"
        )
    with pytest.raises(ValueError):
        ledger.grant_monthly(
            principal,
            starts_at=end,
            expires_at=end + timedelta(days=1),
            event_key="short",
        )


def test_topup_expiry_is_independent_of_month_and_earliest_expiry_is_spent_first(
    account,
):
    _, ledger, principal = account
    ledger.grant_top_up(principal, at=NOW, event_key="purchase", payment_confirmed=True)
    ledger.grant_welcome(
        principal, at=NOW, event_key="verified", verification_confirmed=True
    )
    hold = reserve(ledger, principal, tokens=1_200_000)
    settle(ledger, principal, hold, charged=1_100_000)
    grants = ledger.summary(principal, now=NOW)["grants"]
    assert [(r["kind"], r["spent"]) for r in grants] == [
        ("welcome", 1_000_000),
        ("monthly", 100_000),
        ("top_up", 0),
    ]
    assert (
        ledger.summary(principal, now=NOW + timedelta(days=14))["remaining"]
        == 1_400_000
    )
    assert ledger.summary(principal, now=NOV)["remaining"] == 1_500_000
    assert (
        ledger.summary(principal, now=NOW + timedelta(days=90))["remaining"] == 500_000
    )


def test_bonus_once_only_and_topup_payment_callback_cannot_duplicate_grant(account):
    _, ledger, principal = account
    first = ledger.grant_welcome(
        principal, at=NOW, event_key="verification", verification_confirmed=True
    )
    assert (
        ledger.grant_welcome(
            principal, at=NOW, event_key="verification", verification_confirmed=True
        )
        == first
    )
    with pytest.raises(ResourceConflict):
        ledger.grant_welcome(
            principal,
            at=NOW,
            event_key="other-verification",
            verification_confirmed=True,
        )
    topup = ledger.grant_top_up(
        principal, at=NOW, event_key="payment", payment_confirmed=True
    )
    assert (
        ledger.grant_top_up(
            principal, at=NOW, event_key="payment", payment_confirmed=True
        )
        == topup
    )
    with pytest.raises(PermissionError):
        ledger.grant_welcome(principal, at=NOW, event_key="unverified")
    with pytest.raises(PermissionError):
        ledger.grant_top_up(principal, at=NOW, event_key="unpaid")


def test_cross_owner_operations_and_payment_receipts_are_rejected(account):
    registry, ledger, principal = account
    other = registry.create_user("other@example.com", plan="free")
    device = registry.create_device(other, name="other", platform="android")
    second = registry.authenticate(registry.issue_device_token(device))
    assert second is not None
    hold = reserve(ledger, principal)
    with pytest.raises(PermissionError):
        ledger.mark_dispatched(second, hold.id)
    with pytest.raises(PermissionError):
        ledger.settle(second, hold.id, charged_tokens=0)
    with pytest.raises(PermissionError):
        ledger.release_before_dispatch(second, hold.id)
    ledger.grant_top_up(
        principal, at=NOW, event_key="global-payment", payment_confirmed=True
    )
    with pytest.raises(ResourceConflict):
        ledger.grant_top_up(
            second, at=NOW, event_key="global-payment", payment_confirmed=True
        )
    assert ledger.summary(second, now=NOW)["remaining"] == 500_000
    assert ledger.export_rows(second)["operations"] == []


def test_revocation_and_forged_principal_cannot_spend_or_read_balance(account):
    registry, ledger, principal = account
    forged = AccessPrincipal(principal.user_id, principal.device_id, "not-a-token")
    with pytest.raises(PermissionError):
        ledger.summary(forged, now=NOW)
    registry.revoke_device(principal, principal.device_id)
    with pytest.raises(PermissionError):
        reserve(ledger, principal)
    with pytest.raises(PermissionError):
        ledger.export_rows(principal)


def test_account_deletion_cascades_ledger_and_export_contains_no_private_identifiers(
    account,
):
    registry, ledger, principal = account
    hold = reserve(ledger, principal, key="opaque-operation")
    settle(ledger, principal, hold, usage=TokenUsage(7000, 500))
    portable = json.dumps(ledger.export_rows(principal))
    assert "7000" in portable
    for private in (
        "key_digest",
        "event_digest",
        "run_digest",
        "opaque-operation",
        principal.token_id,
        principal.user_id,
    ):
        assert private not in portable
    account_export = registry.export_account_rows(principal)
    assert account_export["resource_operations"][0]["charged_tokens"] == 10_000
    registry.prepare_account_deletion(principal)
    registry.finalize_account_deletion(principal.user_id)
    with registry._connect() as c:
        for table in (
            "troika_resource_grants",
            "troika_resource_operations",
            "troika_resource_allocations",
            "troika_resource_features",
        ):
            assert c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("invalid", [-1, True, 1.5, 1_000_000_001])
def test_invalid_reservations_do_not_modify_balance(account, invalid):
    _, ledger, principal = account
    with pytest.raises(ValueError):
        reserve(ledger, principal, tokens=invalid)
    assert ledger.summary(principal, now=NOW)["remaining"] == 500_000


def test_raw_input_includes_greeting_system_memory_history_and_tool_schemas():
    # Authoritative provider usage includes ALL serialized input, not the two
    # visible words. The 2k-7k input baseline was reported by the owner.
    prices = TokenPrices(
        "example-all-in", Decimal("20.7"), Decimal("64.86"), Decimal("2.208")
    )
    short_cost, short_tokens = prices.quote(TokenUsage(2000, 500))
    long_cost, long_tokens = prices.quote(TokenUsage(7000, 500, reasoning_tokens=100))
    assert (short_cost, short_tokens) == (Decimal("0.07383"), 2461)
    assert (long_cost, long_tokens) == (Decimal("0.17733"), 5911)
    cache_cost, cache_tokens = prices.quote(TokenUsage(0, 500, cache_read_tokens=7000))
    assert cache_cost < long_cost and cache_tokens < long_tokens


def test_reasoning_is_not_charged_twice_and_unknown_prices_fail_closed():
    prices = TokenPrices("known", Decimal("30"), Decimal("90"))
    assert prices.quote(TokenUsage(1000, 500, reasoning_tokens=400)) == prices.quote(
        TokenUsage(1000, 500)
    )
    with pytest.raises(UnknownResourcePrice):
        prices.quote(TokenUsage(cache_read_tokens=1000))
    with pytest.raises(ValueError):
        TokenUsage(100, 10, reasoning_tokens=11)


@pytest.mark.parametrize(
    "invalid", [Decimal("NaN"), Decimal("Infinity"), Decimal("-1"), 0.1]
)
def test_invalid_cost_is_not_treated_as_zero(invalid):
    with pytest.raises(ValueError):
        resource_tokens_for_cost(invalid)


def test_cost_conversion_conservatively_rounds_once():
    assert resource_tokens_for_cost(Decimal("0")) == 0
    assert resource_tokens_for_cost(Decimal("0.000001")) == 1
    assert resource_tokens_for_cost(Decimal("0.10")) == 3334
    assert resource_tokens_for_cost(Decimal("3")) == 100_000
    assert plan_policy("plus").cost_cap_rub == Decimal("150")
    with pytest.raises(ValueError):
        plan_policy("beta")
