"""Timezone-aware formatting for timestamps shown in the live scoring UI."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


OSLO_TIMEZONE = ZoneInfo("Europe/Oslo")


def to_oslo_datetime(value: datetime | str) -> datetime:
    """Interpret naive timestamps as UTC and convert aware timestamps to Oslo."""
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        value = datetime.fromisoformat(normalized)
    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime or ISO-8601 string")
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(OSLO_TIMEZONE)


def format_oslo_time(value: datetime | str | None) -> str:
    """Format a timestamp as HH:MM in Europe/Oslo."""
    if value is None or value == "":
        return ""
    try:
        return to_oslo_datetime(value).strftime("%H:%M")
    except (TypeError, ValueError):
        return str(value)


def current_oslo_time() -> str:
    """Return the current Europe/Oslo time as HH:MM."""
    return datetime.now(OSLO_TIMEZONE).strftime("%H:%M")
