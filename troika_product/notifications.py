"""User notification preferences and the delivery policy for future workers.

This module never sends messages. A delivery worker must load current settings
and call ``allows_delivery`` immediately before each delivery attempt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class NotificationPreferences:
    """Account-wide opt-ins; quiet hours use the user's IANA time zone."""

    reminders_enabled: bool = False
    proactive_enabled: bool = False
    quiet_hours_enabled: bool = False
    timezone: str = "UTC"
    quiet_start: str = "22:00"
    quiet_end: str = "08:00"

    def __post_init__(self) -> None:
        for name in ("reminders_enabled", "proactive_enabled", "quiet_hours_enabled"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be a boolean")
        if not isinstance(self.timezone, str) or not 1 <= len(self.timezone) <= 100:
            raise ValueError("timezone must be an IANA time zone")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be an IANA time zone") from exc
        for name in ("quiet_start", "quiet_end"):
            value = getattr(self, name)
            if not isinstance(value, str) or not re.fullmatch(
                r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value
            ):
                raise ValueError(f"{name} must use HH:MM (00:00 through 23:59)")
        if self.quiet_start == self.quiet_end:
            raise ValueError("quiet_start and quiet_end must differ")

    @classmethod
    def from_dict(cls, value: object) -> NotificationPreferences:
        """Require a complete replacement; reject unknown ownership fields."""
        if not isinstance(value, dict) or set(value) != {f.name for f in fields(cls)}:
            raise ValueError("provide exactly the six notification preference fields")
        return cls(**value)

    def to_dict(self) -> dict[str, bool | str]:
        return asdict(self)

    def allows_delivery(self, kind: str, *, now: datetime | None = None) -> bool:
        """Evaluate current consent and local quiet hours, start inclusive.

        End is exclusive. Intervals can cross midnight. Converting from an
        aware instant handles both occurrences of a repeated DST hour without
        constructing ambiguous or nonexistent local datetimes.
        """
        if kind not in ("reminder", "proactive"):
            raise ValueError("unsupported notification kind")
        instant = now if now is not None else datetime.now(timezone.utc)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        enabled = self.reminders_enabled if kind == "reminder" else self.proactive_enabled
        if not enabled:
            return False
        if not self.quiet_hours_enabled:
            return True
        local_time = instant.astimezone(ZoneInfo(self.timezone)).strftime("%H:%M")
        if self.quiet_start < self.quiet_end:
            quiet = self.quiet_start <= local_time < self.quiet_end
        else:
            quiet = local_time >= self.quiet_start or local_time < self.quiet_end
        return not quiet
