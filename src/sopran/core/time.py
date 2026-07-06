from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as datetime_time
from typing import Any


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


def spice_utc_string(value: object) -> str:
    """Return a UTC timestamp string accepted by SPICE ``utc2et``."""

    import numpy as np

    if isinstance(value, np.datetime64):
        if np.isnat(value):
            raise ValueError("NaT cannot be converted to a SPICE UTC timestamp")
        text = np.datetime_as_string(value.astype("datetime64[us]"), unit="us")
        return _format_spice_utc_text(text)
    if isinstance(value, datetime):
        return _format_spice_utc_datetime(value)
    if isinstance(value, date):
        timestamp = datetime.combine(value, datetime_time.min, tzinfo=UTC)
        return _format_spice_utc_datetime(timestamp)
    if isinstance(value, (int, float, np.integer, np.floating)):
        timestamp = datetime.fromtimestamp(float(value), tz=UTC)
        return _format_spice_utc_datetime(timestamp)
    return _format_spice_utc_string(str(value))


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
    normalized = value.astimezone(UTC).replace(tzinfo=None)
    timespec = "microseconds" if normalized.microsecond else "seconds"
    text = normalized.isoformat(timespec=timespec)
    return f"{text}Z"


def _format_spice_utc_datetime(value: datetime) -> str:
    normalized = _as_utc_datetime(value).replace(tzinfo=None)
    return _format_spice_utc_text(normalized.isoformat(timespec="microseconds"))


def _format_spice_utc_string(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("Empty time value cannot be converted to a SPICE UTC timestamp")
    parse_candidate = text
    upper = parse_candidate.upper()
    if upper.endswith("UTC"):
        parse_candidate = parse_candidate[:-3].strip()
    try:
        return _format_spice_utc_datetime(_parse_datetime(parse_candidate))
    except (TypeError, ValueError):
        normalized = text.replace("T", " ", 1)
        if normalized.endswith("Z"):
            normalized = normalized[:-1]
        if normalized.upper().endswith("UTC"):
            normalized = normalized[:-3].strip()
        return f"{normalized} UTC"


def _format_spice_utc_text(value: str) -> str:
    text = value.replace("T", " ", 1)
    if text.endswith(".000000"):
        text = text[:-7]
    return f"{text} UTC"


def _filter_polars_time(frame_or_lazy: Any, time: TimeRange, *, column: str = "time") -> Any:
    import polars as pl

    schema = (
        frame_or_lazy.collect_schema()
        if hasattr(frame_or_lazy, "collect_schema")
        else frame_or_lazy.schema
    )
    dtype = schema.get(column)
    dtype_base = _polars_dtype_base(dtype)
    expr = pl.col(column)
    if dtype_base == pl.Date:
        start = time.start.date()
        stop = ((time.stop - timedelta(microseconds=1)).date() + timedelta(days=1))
        time_expr = expr
    else:
        if dtype_base == pl.Datetime:
            timezone = getattr(dtype, "time_zone", None)
            if timezone is None:
                start = time.start.replace(tzinfo=None)
                stop = time.stop.replace(tzinfo=None)
            else:
                start = time.start.astimezone(UTC)
                stop = time.stop.astimezone(UTC)
            time_expr = expr
        else:
            start = time.start.replace(tzinfo=None)
            stop = time.stop.replace(tzinfo=None)
            text = expr.cast(pl.Utf8)
            time_expr = pl.coalesce(
                text.str.strptime(
                    pl.Datetime,
                    format="%Y-%m-%dT%H:%M:%S%.fZ",
                    strict=False,
                ),
                text.str.strptime(
                    pl.Datetime,
                    format="%Y-%m-%dT%H:%M:%S%.f",
                    strict=False,
                ),
                text.str.strptime(pl.Date, format="%Y-%m-%d", strict=False).cast(
                    pl.Datetime
                ),
            )
    return frame_or_lazy.filter((time_expr >= start) & (time_expr < stop))


def _polars_dtype_base(dtype: Any) -> Any:
    base_type = getattr(dtype, "base_type", None)
    if callable(base_type):
        return base_type()
    return dtype
