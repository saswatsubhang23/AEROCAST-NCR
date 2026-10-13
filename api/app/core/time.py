"""Timestamps are stored and exchanged in UTC; IST is a display conversion only."""

from datetime import datetime, timedelta, timezone

# India has no daylight saving, so a fixed offset is exact and needs no tz database.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_ist(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Refusing to convert a naive datetime; timestamps must be timezone-aware.")
    return value.astimezone(IST)
