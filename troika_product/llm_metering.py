"""Text and bounded vision SDK adapter; disabled until explicitly wired.

Prices are trusted, versioned all-in RUB values, never model arguments. This
adapter blocks unpriced or unsupported multimodal and unbounded requests.
Audio, native vendor APIs, paid tools and billing need separate adapters.
"""

from dataclasses import dataclass
from decimal import Decimal
import json
from types import MappingProxyType
from urllib.parse import urlsplit
import uuid

from agent.provider_metering import ProviderCallBlocked
from troika_product.resource_ledger import (
    FeatureLimitExceeded,
    ResourceLedger,
    ResourceLimitExceeded,
    RunBudgetExceeded,
    ResourcePriceChanged,
)
from troika_product.subscription_policy import TokenPrices, TokenUsage


@dataclass(frozen=True)
class ModelPrice:
    prices: TokenPrices
    premium: bool = False
    default_output_tokens: int = 8192
    maximum_output_tokens: int = 65536
    vision_input_tokens: int = 0
    debit_mode: str = "provider_cost"

    def __post_init__(self):
        if (
            type(self.premium) is not bool
            or type(self.default_output_tokens) is not int
            or type(self.maximum_output_tokens) is not int
            or not 1
            <= self.default_output_tokens
            <= self.maximum_output_tokens
            <= 65536
            or type(self.vision_input_tokens) is not int
            or not 0 <= self.vision_input_tokens <= 2_000_000
            or self.debit_mode not in {"provider_cost", "model_tokens"}
        ):
            raise ValueError("invalid resource output bound or premium flag")
        # Every input bucket needs a price before reserving a worst-case cost.
        self.prices.quote(TokenUsage(1, 1, 1, 1))
        if self.debit_mode == "model_tokens" and any(value != 0 for value in (
            self.prices.input_rub, self.prices.output_rub,
            self.prices.cache_read_rub, self.prices.cache_write_rub)):
            raise ValueError("raw model-token debit is only for confirmed free models")


class PriceCatalogue:
    def __init__(self, entries):
        self.entries = MappingProxyType(dict(entries))

    @classmethod
    def from_config(cls, config):
        if not isinstance(config, dict):
            raise ValueError("resource prices must be a server-owned mapping")
        entries = {}
        for model, row in config.items():
            if not isinstance(model, str) or not model or not isinstance(row, dict):
                raise ValueError("invalid resource model price")
            provider = row.get("provider", "openrouter")
            if not isinstance(provider, str) or not provider:
                raise ValueError("resource price requires a provider")
            prices = TokenPrices(
                row.get("version", ""),
                *[
                    Decimal(str(row[key]))
                    for key in (
                        "input_rub",
                        "output_rub",
                        "cache_read_rub",
                        "cache_write_rub",
                    )
                ],
            )
            default = row.get("default_output_tokens", 8192)
            maximum = row.get("maximum_output_tokens", 65536)
            premium = row.get("premium", False)
            if (
                type(premium) is not bool
                or type(default) is not int
                or type(maximum) is not int
                or not 1 <= default <= maximum <= 65536
            ):
                raise ValueError("invalid resource output bound or premium flag")
            entries[(provider, model)] = ModelPrice(
                prices, premium, default, maximum, row.get("vision_input_tokens", 0),
                row.get("debit_mode", "provider_cost")
            )
        return cls(entries)


def _get(value, key, default=None):
    return (
        value.get(key, default)
        if isinstance(value, dict)
        else getattr(value, key, default)
    )


def _strict_count(value):
    if type(value) is not int or value < 0:
        raise ProviderCallBlocked(
            "resource_usage_unknown",
            "Провайдер не подтвердил корректный расход токенов; резерв сохранён.",
        )
    return value


def _usage(response, *, zero_cost=False):
    raw = _get(response, "usage")
    if raw is None:
        raise ProviderCallBlocked(
            "resource_usage_unknown",
            "Провайдер не передал расход токенов; резерв сохранён.",
        )
    prompt = _strict_count(_get(raw, "prompt_tokens"))
    output = _strict_count(_get(raw, "completion_tokens"))
    details = _get(raw, "prompt_tokens_details")
    cached = _strict_count(
        _get(details, "cached_tokens")
        if _get(details, "cached_tokens") is not None
        else _get(raw, "cache_read_input_tokens", 0)
    )
    written = _strict_count(
        _get(details, "cache_write_tokens")
        if _get(details, "cache_write_tokens") is not None
        else _get(raw, "cache_creation_input_tokens", 0)
    )
    output_details = _get(raw, "completion_tokens_details") or _get(
        raw, "output_tokens_details"
    )
    reasoning = _get(output_details, "reasoning_tokens")
    reasoning = _strict_count(0 if reasoning is None else reasoning)
    if reasoning > output and zero_cost:
        # Some free-router models report incompatible completion/reasoning
        # counters. A confirmed zero bill may proceed: retain both native
        # counters and use their sum only as a conservative token upper bound.
        output += reasoning
    if cached + written > prompt or reasoning > output:
        raise ProviderCallBlocked(
            "resource_usage_unknown",
            "Провайдер передал несовместимые счётчики; резерв сохранён.",
        )
    return TokenUsage(prompt - cached - written, output, cached, written, reasoning)


def _text_only(value):
    if isinstance(value, dict):
        if value.get("type") in {
            "image_url",
            "input_image",
            "input_audio",
            "audio",
            "file",
            "input_file",
            "video_url",
            "video",
        }:
            return False
        return all(_text_only(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_text_only(item) for item in value)
    return not isinstance(value, (bytes, bytearray))


def _vision_context(value):
    """Quote text plus a confirmed model upper bound for each image.

    Image bytes are never tokenized as text. The real provider prompt counter
    determines the debit; the operator must confirm the model's vision bound.
    """
    if isinstance(value, dict):
        if value.get("type") == "image_url":
            reference = value.get("image_url", {})
            url = reference.get("url") if isinstance(reference, dict) else None
            if not isinstance(url, str) or not url.startswith((
                "https://",
                "data:image/",
            )):
                raise ValueError("invalid vision reference")
            return {"type": "image_url", "detail": reference.get("detail", "auto")}, 1
        if value.get("type") in {
            "input_image",
            "input_audio",
            "audio",
            "file",
            "input_file",
            "video",
            "video_url",
        }:
            raise ValueError("unmetered modality")
        converted, images = {}, 0
        for key, item in value.items():
            result, count = _vision_context(item)
            converted[key], images = result, images + count
        return converted, images
    if isinstance(value, (list, tuple)):
        result = [_vision_context(item) for item in value]
        return [item[0] for item in result], sum(item[1] for item in result)
    if isinstance(value, (bytes, bytearray)):
        raise ValueError("raw media is unbounded")
    return value, 0


class LLMMeter:
    def __init__(
        self,
        ledger: ResourceLedger,
        principal,
        *,
        run_key: str,
        catalogue: PriceCatalogue,
        run_token_limit=None,
    ):
        self.ledger, self.principal = ledger, principal
        self.run_key, self.catalogue = run_key, catalogue
        self.stopped = False
        self.run_token_limit = run_token_limit

    def block_pending_calls(self):
        self.stopped = True

    def begin_call(self, payload, *, provider, base_url):
        if self.stopped:
            raise ProviderCallBlocked(
                "resource_usage_unknown",
                "Расход предыдущего вызова требует сверки; новые вызовы остановлены.",
            )
        actual_provider = {
            "openrouter.ai": "openrouter",
            "api.openai.com": "openai",
        }.get(urlsplit(base_url).hostname)
        if actual_provider is None or provider not in {None, "", actual_provider}:
            raise ProviderCallBlocked(
                "resource_price_unavailable",
                "Нет проверенного тарифа для этого провайдера.",
            )
        model = payload.get("model")
        entry = self.catalogue.entries.get((actual_provider, model))
        if entry is None:
            raise ProviderCallBlocked(
                "resource_price_unavailable",
                "Цена этой модели ещё не подключена к учёту ресурса.",
            )
        images = 0
        vision_context = None
        if entry.vision_input_tokens:
            try:
                vision_context, images = _vision_context(payload.get("messages", []))
                if images > 4:
                    raise ValueError("too many images")
            except ValueError as error:
                raise ProviderCallBlocked(
                    "unmetered_provider_route",
                    "Этот формат медиа ещё не подключён к учёту.",
                ) from error
        if (
            (
                not _text_only(payload.get("messages", []))
                and not (entry.vision_input_tokens and images)
            )
            or payload.get("audio")
            or payload.get("modalities", ["text"]) != ["text"]
        ):
            raise ProviderCallBlocked(
                "unmetered_provider_route",
                "Для изображений и аудио требуется отдельный учёт ресурса.",
            )
        if not isinstance(payload.get("messages"), list) or not payload["messages"]:
            raise ProviderCallBlocked(
                "unmetered_provider_route",
                "Учитываемый вызов должен содержать полный контекст messages.",
            )
        bounded = dict(payload)
        if type(bounded.get("n", 1)) is not int or bounded.get("n", 1) != 1:
            raise ProviderCallBlocked(
                "resource_output_unbounded",
                "Для учёта ресурса доступен один вариант ответа за вызов.",
            )
        limits = [
            key
            for key in ("max_tokens", "max_completion_tokens")
            if bounded.get(key) is not None
        ]
        if len(limits) > 1:
            raise ProviderCallBlocked(
                "resource_output_unbounded",
                "Передан неоднозначный предел ответа модели.",
            )
        limit_key = limits[0] if limits else "max_tokens"
        if not limits:
            bounded.pop("max_tokens", None)
            bounded.pop("max_completion_tokens", None)
        output_bound = bounded.get(limit_key, entry.default_output_tokens)
        if (
            type(output_bound) is not int
            or not 1 <= output_bound <= entry.maximum_output_tokens
        ):
            raise ProviderCallBlocked(
                "resource_output_unbounded",
                "Ответ модели не имеет допустимого предела токенов.",
            )
        bounded[limit_key] = output_bound
        if bounded.get("stream"):
            bounded["stream_options"] = {
                **(bounded.get("stream_options") or {}),
                "include_usage": True,
            }
        extra = bounded.get("extra_body") or {}
        if not isinstance(extra, dict) or set(extra) - {"reasoning", "response_format"}:
            raise ProviderCallBlocked(
                "unmetered_provider_route",
                "Динамический маршрут модели требует отдельной проверки цены.",
            )
        context = {
            key: value
            for key, value in bounded.items()
            if key not in {"extra_headers", "extra_query", "timeout"}
        }
        if images:
            context["messages"] = vision_context
        try:
            # Full UTF-8 payload plus framing slack is deliberately conservative.
            # This is a reservation estimate, never the customer's final debit.
            byte_count = len(
                json.dumps(context, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
        except (TypeError, UnicodeError) as error:
            raise ProviderCallBlocked(
                "resource_input_unbounded",
                "Контекст нельзя безопасно оценить до вызова модели.",
            ) from error
        input_bound = (
            byte_count
            + 8192
            + 256 * len(bounded["messages"])
            + images * entry.vision_input_tokens
        )
        worst_input = max(
            entry.prices.input_rub,
            entry.prices.cache_read_rub,
            entry.prices.cache_write_rub,
        )
        upper_prices = TokenPrices(
            entry.prices.version, worst_input, entry.prices.output_rub
        )
        _, upper_tokens = upper_prices.quote(TokenUsage(input_bound, output_bound))
        if entry.debit_mode == "model_tokens":
            upper_tokens = input_bound + output_bound
        try:
            self.ledger.bind_price(
                self.principal,
                actual_provider + ":" + model,
                {
                    "version": entry.prices.version,
                    **({"debit_mode": entry.debit_mode} if entry.debit_mode != "provider_cost" else {}),
                    **{
                        name: str(getattr(entry.prices, name).normalize())
                        for name in (
                            "input_rub",
                            "output_rub",
                            "cache_read_rub",
                            "cache_write_rub",
                        )
                    },
                },
            )
        except ResourcePriceChanged as error:
            raise ProviderCallBlocked(
                "resource_price_change_requires_approval",
                "Коэффициенты изменились внутри текущего периода; вызов остановлен до согласования.",
            ) from error
        except ResourceLimitExceeded as error:
            raise ProviderCallBlocked(
                "monthly_resource_exhausted", "Месячный AI-ресурс ещё не активирован."
            ) from error
        except PermissionError as error:
            raise ProviderCallBlocked(
                "resource_access_revoked",
                "Доступ устройства отозван; платный вызов остановлен.",
            ) from error
        approve = getattr(self, "approve_resource_cost", None)
        if approve is not None:
            approve(upper_tokens, premium=entry.premium)
        try:
            hold = self.ledger.reserve(
                self.principal,
                operation_key=str(uuid.uuid4()),
                run_key=self.run_key,
                kind="llm",
                tokens=upper_tokens,
                pricing_version=entry.prices.version,
                feature="premium" if entry.premium else None,
                run_token_limit=self.run_token_limit,
            )
            self.ledger.mark_dispatched(self.principal, hold.id)
        except FeatureLimitExceeded as error:
            raise ProviderCallBlocked(
                "subscription_feature_not_available",
                "Эта модель недоступна на текущем тарифе.",
            ) from error
        except RunBudgetExceeded as error:
            if approve is not None:
                # Another worker may have reserved between the quote and this
                # transaction. Recheck through the same explicit approval gate.
                approve(upper_tokens, premium=entry.premium)
                return self.begin_call(payload, provider=provider, base_url=base_url)
            raise ProviderCallBlocked(
                "resource_budget_approval_required",
                "Задача достигла согласованного предела AI-токенов. Продолжение требует подтверждения.",
            ) from error
        except ResourceLimitExceeded as error:
            raise ProviderCallBlocked(
                "monthly_resource_exhausted",
                "Недостаточно месячного AI-ресурса для безопасного начала вызова.",
            ) from error
        except PermissionError as error:
            raise ProviderCallBlocked(
                "resource_access_revoked",
                "Доступ аккаунта или устройства отозван; вызов модели остановлен.",
            ) from error
        return _Lease(self, hold, entry.prices, input_bound, output_bound, entry.debit_mode), bounded


class _Lease:
    def __init__(self, meter, hold, prices, input_bound, output_bound, debit_mode="provider_cost"):
        self.meter, self.hold, self.prices = meter, hold, prices
        self.input_bound, self.output_bound = input_bound, output_bound
        self.debit_mode = debit_mode
        self.settled = False

    def succeeded(self, response):
        raw = _get(response, "usage")
        zero_cost = (
            all(value == 0 for value in (
                self.prices.input_rub, self.prices.output_rub,
                self.prices.cache_read_rub, self.prices.cache_write_rub))
            and type(_get(raw, "cost")) in {int, float}
            and _get(raw, "cost") == 0
        )
        usage = _usage(response, zero_cost=zero_cost)
        reported_output = _get(raw, "completion_tokens")
        reported_reasoning = _get(_get(raw, "completion_tokens_details"), "reasoning_tokens", 0) or 0
        upper_bound = zero_cost and reported_reasoning > reported_output
        if (
            usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens
            > self.input_bound
            or (usage.output_tokens > self.output_bound and not upper_bound)
        ):
            raise ProviderCallBlocked(
                "resource_usage_exceeded",
                "Расход превысил предварительную оценку; дальнейшие вызовы остановлены.",
            )
        cost, charged = self.prices.quote(usage)
        if self.debit_mode == "model_tokens":
            # Top-level provider counts are authoritative for this service rule.
            # Reasoning is not added again, even when its breakdown is inconsistent.
            charged = _get(raw, "prompt_tokens") + reported_output
        self.meter.ledger.settle(
            self.meter.principal,
            self.hold.id,
            charged_tokens=charged,
            usage=usage,
            details={
                "service": "llm",
                "unit": "tokens",
                "units": usage.input_tokens
                + usage.cache_read_tokens
                + usage.cache_write_tokens
                + usage.output_tokens,
                "cost_rub": str(cost),
                **({"debit_mode": "model_tokens"} if self.debit_mode == "model_tokens" else {}),
                **({"reported_completion_tokens": reported_output,
                    "reported_reasoning_tokens": reported_reasoning,
                    "tokens_upper_bound": 1} if upper_bound else {}),
            },
        )
        self.settled = True

    def failed(self, error):
        # No inference-cost claim is made from an exception or missing usage.
        # Reconciliation, including company-paid retries, is a separate adapter.
        self.meter.stopped = True
        if isinstance(error, ProviderCallBlocked):
            raise error
        if isinstance(error, Exception):
            raise ProviderCallBlocked(
                "resource_usage_unknown",
                "Вызов прервался без полной сверки расхода; резерв сохранён, повторы остановлены.",
            ) from error

    def require_settled(self):
        if not self.settled:
            raise ProviderCallBlocked(
                "resource_usage_unknown",
                "Поток завершился без подтверждения расхода; резерв сохранён.",
            )
