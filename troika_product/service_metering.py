"""Bounded metering of hosted voice services using operator-owned prices.

No guessed exchange rate or client-reported audio duration can issue a debit.
Dispatched calls without a billable receipt retain their reservation.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import io
import uuid
import wave

from agent.provider_metering import ProviderCallBlocked
from troika_product.resource_ledger import (
    ResourceLimitExceeded,
    RunBudgetExceeded,
    ResourcePriceChanged,
)
from troika_product.subscription_policy import resource_tokens_for_cost


def _amount(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError("service amount must be finite and non-negative")
    return result


@dataclass(frozen=True)
class ServicePrice:
    version: str
    unit: str
    rub_per_unit: Decimal
    minimum_units: Decimal
    maximum_units: Decimal

    @classmethod
    def from_config(cls, row):
        if not isinstance(row, dict):
            raise ValueError("service price must be a server-owned mapping")
        price = cls(
            row.get("version", ""),
            row.get("unit", ""),
            _amount(row["rub_per_unit"]),
            _amount(row.get("minimum_units", 0)),
            _amount(row["maximum_units"]),
        )
        if (
            not isinstance(price.version, str)
            or not 1 <= len(price.version) <= 100
            or price.unit not in {"seconds", "characters"}
            or not 0 <= price.minimum_units <= price.maximum_units
            or price.maximum_units <= 0
        ):
            raise ValueError("invalid service price")
        return price

    def quote(self, units):
        measured = _amount(units)
        if measured > self.maximum_units:
            raise ValueError("service input exceeds its configured bound")
        billed = max(self.minimum_units, measured)
        cost = billed * self.rub_per_unit
        return billed, cost, resource_tokens_for_cost(cost)


def audio_duration(audio, *, maximum_seconds=180):
    """Decode bounded bytes in RAM. Never trust upload metadata or filenames."""
    try:
        with wave.open(io.BytesIO(audio)) as reader:
            seconds = Decimal(reader.getnframes()) / reader.getframerate()
            # Reject truncated PCM files before sending them to a paid service.
            expected = (
                reader.getnframes() * reader.getsampwidth() * reader.getnchannels()
            )
            if len(reader.readframes(reader.getnframes())) != expected:
                raise ValueError("truncated audio")
    except (wave.Error, EOFError):
        try:
            import av

            with av.open(
                io.BytesIO(audio), options={"protocol_whitelist": "pipe"}
            ) as container:
                if not set(container.format.name.split(",")) & {
                    "wav",
                    "mp3",
                    "flac",
                    "ogg",
                    "mov",
                    "mp4",
                    "matroska",
                    "webm",
                    "aac",
                    "m4a",
                }:
                    raise ValueError("unsupported audio container")
                seconds = Decimal(0)
                for index, frame in enumerate(container.decode(audio=0)):
                    if index > 50_000 or not frame.sample_rate:
                        raise ValueError("unbounded audio")
                    seconds += Decimal(frame.samples) / frame.sample_rate
                    if seconds > maximum_seconds:
                        raise ValueError("audio too long")
        except Exception as error:
            raise ProviderCallBlocked(
                "resource_audio_unbounded",
                "Не удалось проверить длительность записи до платного распознавания.",
            ) from error
    if not 0 < seconds <= maximum_seconds:
        raise ProviderCallBlocked(
            "resource_audio_unbounded", "Запись должна длиться от 0 до 180 секунд."
        )
    return seconds


class ServiceMeter:
    def __init__(self, ledger, principal, *, run_key, prices, run_token_limit=None):
        self.ledger, self.principal, self.run_key = ledger, principal, run_key
        self.prices, self.run_token_limit = prices, run_token_limit

    def begin(self, service, units, *, kind):
        try:
            row = self.prices.get(service)
            if row is None:
                raise ValueError("unpriced service")
            price = ServicePrice.from_config(row)
            if (
                (kind == "stt" and price.unit != "seconds")
                or (kind == "tts" and price.unit != "characters")
                or (service.startswith("groq:") and price.minimum_units < 10)
            ):
                raise ValueError(
                    "service billing units or minimum interval do not match"
                )
            _, _, upper = price.quote(units)
        except (ValueError, KeyError, TypeError, InvalidOperation) as error:
            raise ProviderCallBlocked(
                "resource_price_unavailable",
                "Цена голосового сервиса не подтверждена; вызов остановлен.",
            ) from error
        try:
            self.ledger.bind_price(
                self.principal,
                service,
                {
                    "version": price.version,
                    "unit": price.unit,
                    "rub_per_unit": str(price.rub_per_unit.normalize()),
                    "minimum_units": str(price.minimum_units.normalize()),
                },
            )
            hold = self.ledger.reserve(
                self.principal,
                operation_key=str(uuid.uuid4()),
                run_key=self.run_key,
                kind=kind,
                tokens=upper,
                pricing_version=price.version,
                feature="voice",
                run_token_limit=self.run_token_limit,
            )
            self.ledger.mark_dispatched(self.principal, hold.id)
        except ResourcePriceChanged as error:
            raise ProviderCallBlocked(
                "resource_price_change_requires_approval",
                "Цена голоса изменилась в текущем периоде; вызов остановлен до согласования.",
            ) from error
        except RunBudgetExceeded as error:
            raise ProviderCallBlocked(
                "resource_budget_approval_required",
                "Нужен новый предел расходов на задачу.",
            ) from error
        except ResourceLimitExceeded as error:
            raise ProviderCallBlocked(
                "monthly_resource_exhausted",
                "Недостаточно AI-токенов для голосового вызова.",
            ) from error
        return ServiceLease(self, hold, service, price, _amount(units))


class ServiceLease:
    def __init__(self, meter, hold, service, price, upper_units):
        self.meter, self.hold, self.service, self.price = meter, hold, service, price
        self.upper_units = upper_units

    def succeeded(self, measured_units):
        try:
            measured = _amount(measured_units)
            # Provider duration can include frame rounding; the caller must have
            # reserved this margin before dispatch. No new funds are taken here.
            if measured > self.upper_units:
                raise ValueError("measured usage exceeds reservation")
            billed, cost, charged = self.price.quote(measured)
            return self.meter.ledger.settle(
                self.meter.principal,
                self.hold.id,
                charged_tokens=charged,
                details={
                    "service": self.service,
                    "unit": self.price.unit,
                    "units": str(billed),
                    "cost_rub": str(cost),
                },
            )
        except (
            ValueError,
            TypeError,
            InvalidOperation,
            ResourceLimitExceeded,
        ) as error:
            raise ProviderCallBlocked(
                "resource_usage_unknown",
                "Расход голоса требует сверки; резерв сохранён.",
            ) from error

    def failed(self, error):
        raise ProviderCallBlocked(
            "resource_usage_unknown",
            "Голосовой вызов прервался без подтверждения расходов; резерв сохранён.",
        ) from error


def resource_error_response(error):
    from aiohttp import web

    code = getattr(error, "code", "resource_usage_unknown")
    return web.json_response(
        {"error": {"code": code, "message": str(error)}},
        status=429 if code == "monthly_resource_exhausted" else 409,
        headers={"Cache-Control": "private, no-store"},
    )
