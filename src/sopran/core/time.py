from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone


UTC = timezone.utc


@dataclass(frozen=True)
class TimeRange:
    """Half-open UTC time range used by SOPRAN public APIs."""

    start: datetime
    stop: datetime

    def __post_init__(self) -> None:
        start = _as_utc_datetime(self.start)
        stop = _as_utc_datetime(self.stop)
        if stop <= start:
            raise ValueError("TimeRange stop must be after start")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "stop", stop)

    @property
    def start_iso(self) -> str:
        return _format_utc(self.start)

    @property
    def stop_iso(self) -> str:
        return _format_utc(self.stop)

    def days(self) -> list[str]:
        """Return UTC day labels touched by this half-open interval."""

        final = (self.stop - timedelta(microseconds=1)).date()
        current = self.start.date()
        days: list[str] = []
        while current <= final:
            days.append(current.isoformat())
            current += timedelta(days=1)
        return days


def period(start: object, stop: object) -> TimeRange:
    """Create a half-open UTC period [start, stop)."""

    return TimeRange(_parse_datetime(start), _parse_datetime(stop))


def day(value: object) -> TimeRange:
    start = _parse_datetime(value)
    start = datetime.combine(start.date(), datetime_time.min, tzinfo=UTC)
    return TimeRange(start, start + timedelta(days=1))


def month(value: str) -> TimeRange:
    year_value, month_value = value.split("-", 1)
    start = datetime(int(year_value), int(month_value), 1, tzinfo=UTC)
    if start.month == 12:
        stop = datetime(start.year + 1, 1, 1, tzinfo=UTC)
    else:
        stop = datetime(start.year, start.month + 1, 1, tzinfo=UTC)
    return TimeRange(start, stop)


def year(value: int | str) -> TimeRange:
    start = datetime(int(value), 1, 1, tzinfo=UTC)
    return TimeRange(start, datetime(start.year + 1, 1, 1, tzinfo=UTC))


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return _as_utc_datetime(value)
    if isinstance(value, date):
        return datetime.combine(value, datetime_time.min, tzinfo=UTC)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        if len(text) == 10:
            return datetime.combine(date.fromisoformat(text), datetime_time.min, tzinfo=UTC)
        return _as_utc_datetime(datetime.fromisoformat(text))
    raise TypeError(f"Unsupported time value: {value!r}")


def _as_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    text = value.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds")
    return f"{text}Z"
