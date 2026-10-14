"""Development admission is Pro-only regardless of the resource balance."""

from datetime import datetime, timedelta, timezone

import pytest

from troika_product.access import AccessRegistry
from troika_product.resource_ledger import FeatureLimitExceeded, ResourceLedger


@pytest.mark.parametrize("plan", ["free", "plus", "pro"])
def test_development_admission_rejects_other_plans_before_resource_is_reserved(tmp_path, plan):
    registry = AccessRegistry(tmp_path / "access.db")
    owner = registry.create_user("autopilot@example.com", plan=plan)
    device = registry.create_device(owner, name="test", platform="windows")
    principal = registry.authenticate(registry.issue_device_token(device))
    ledger = ResourceLedger(registry)
    now = datetime.now(timezone.utc)
    if plan != "free":
        ledger.grant_monthly(principal, starts_at=now, expires_at=now + timedelta(days=30),
                             event_key="activated-period")
    before = ledger.summary(principal, now=now)

    def admit():
        return ledger.reserve(principal, operation_key="development", run_key="project",
                              kind="tool", tokens=100, pricing_version="test",
                              feature="development", now=now)

    if plan == "pro":
        hold = admit()
        assert hold.state == "reserved"
        assert ledger.summary(principal, now=now)["reserved"] == 100
    else:
        with pytest.raises(FeatureLimitExceeded):
            admit()
        after = ledger.summary(principal, now=now)
        assert (after["reserved"], after["remaining"]) == (before["reserved"], before["remaining"])

    # Ordinary document creation keeps its existing entitlement on every plan.
    document = ledger.reserve(principal, operation_key="document", run_key="document",
                              kind="tool", tokens=100, pricing_version="test",
                              feature="documents", now=now)
    assert document.state == "reserved"
