"""Approved subscription policy; resource tokens are not provider tokens.

This module describes the owner's 2026-10-12 decision. Publishing a capability
does not enable it: runtime availability, consent and ownership still apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from types import MappingProxyType
from typing import Mapping


POLICY_VERSION = "2026-10-12"
RUBLES_PER_MILLION_RESOURCE_TOKENS = Decimal("30")
WELCOME_TOKENS = 1_000_000
WELCOME_DAYS = 14
TOP_UP_TOKENS = 1_000_000
TOP_UP_PRICE_RUB = 99
TOP_UP_DAYS = 90


def resource_tokens_for_cost(cost_rub: Decimal) -> int:
    """Round the entire operation once, never each token or text fragment."""
    if not isinstance(cost_rub, Decimal) or not cost_rub.is_finite() or cost_rub < 0:
        raise ValueError("cost must be a finite non-negative Decimal in RUB")
    return int(
        (cost_rub * 1_000_000 / RUBLES_PER_MILLION_RESOURCE_TOKENS).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


@dataclass(frozen=True)
class SubscriptionPlan:
    name: str
    price_rub: int
    monthly_tokens: int
    concurrent_runs: int
    features: Mapping[str, int | None]

    @property
    def cost_cap_rub(self) -> Decimal:
        return (
            Decimal(self.monthly_tokens)
            * RUBLES_PER_MILLION_RESOURCE_TOKENS
            / 1_000_000
        )

    def feature_limit(self, feature: str) -> int | None:
        """Zero denies access; None means the common resource budget applies."""
        if feature not in FEATURES:
            raise ValueError("unknown subscription feature")
        return self.features.get(feature, 0)


FEATURES = frozenset({
    "voice",
    "search",
    "documents",
    "snapshot",
    "development",
    "deep_research",
    "premium",
})
_BASE = {"voice": None, "search": None, "documents": None, "snapshot": None}
PLANS = MappingProxyType({
    "free": SubscriptionPlan(
        "free",
        0,
        500_000,
        1,
        MappingProxyType({**_BASE, "search": 10, "documents": 3, "snapshot": 5}),
    ),
    "plus": SubscriptionPlan(
        "plus", 790, 5_000_000, 1, MappingProxyType(dict(_BASE))
    ),
    "pro": SubscriptionPlan(
        "pro",
        1490,
        10_000_000,
        5,
        MappingProxyType({feature: None for feature in FEATURES}),
    ),
})


def plan_policy(name: str) -> SubscriptionPlan:
    """Unknown and legacy beta plans need an explicit operator decision."""
    try:
        return PLANS[name]
    except (KeyError, TypeError) as exc:
        raise ValueError("unsupported resource plan") from exc


@dataclass(frozen=True)
class TokenUsage:
    """Canonical disjoint input buckets; reasoning is a subset of output.

    Provider adapters must normalize providers whose prompt count already
    includes cache counts. Summing those overlapping fields directly is wrong.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        for value in vars(self).values():
            if type(value) is not int or value < 0:
                raise ValueError("usage counts must be non-negative integers")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning must be included in output tokens")


class UnknownResourcePrice(ValueError):
    """Missing prices must never silently become free usage."""


@dataclass(frozen=True)
class TokenPrices:
    """Versioned all-in RUB prices per million, supplied by a trusted router.

    FX and provider fees belong in these prices. Actual provider USD costs are
    separate billing evidence. No network fetch or model switch happens here.
    """

    version: str
    input_rub: Decimal | None
    output_rub: Decimal | None
    cache_read_rub: Decimal | None = None
    cache_write_rub: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.version or len(self.version) > 100:
            raise ValueError("a pricing version is required")
        for value in (
            self.input_rub,
            self.output_rub,
            self.cache_read_rub,
            self.cache_write_rub,
        ):
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite() or value < 0
            ):
                raise ValueError("prices must be finite non-negative Decimal values")

    def quote(self, usage: TokenUsage) -> tuple[Decimal, int]:
        cost = Decimal(0)
        for count, price in (
            (usage.input_tokens, self.input_rub),
            (usage.output_tokens, self.output_rub),
            (usage.cache_read_tokens, self.cache_read_rub),
            (usage.cache_write_tokens, self.cache_write_rub),
        ):
            if count:
                if price is None:
                    raise UnknownResourcePrice("resource price is unavailable")
                cost += Decimal(count) * price / 1_000_000
        return cost, resource_tokens_for_cost(cost)
