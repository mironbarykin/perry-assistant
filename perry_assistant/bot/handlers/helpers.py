from __future__ import annotations

import datetime as dt


def parse_time_hhmm(value: str) -> dt.time | None:
    raw = value.strip()
    try:
        return dt.datetime.strptime(raw, "%H:%M").time()
    except ValueError:
        return None


def parse_local_datetime(
    value: str,
    tzinfo: dt.tzinfo,
    *,
    formats: tuple[str, ...],
) -> dt.datetime | None:
    raw = value.strip()
    for fmt in formats:
        try:
            naive = dt.datetime.strptime(raw, fmt)
            return naive.replace(tzinfo=tzinfo)
        except ValueError:
            continue
    return None


def parse_date_flexible(value: str, *, formats: tuple[str, ...]) -> dt.date | None:
    raw = value.strip()
    for fmt in formats:
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_iso_datetime(value: str, *, default_tz: dt.tzinfo | None = None) -> dt.datetime | None:
    """Parse ISO datetime and optionally apply a default timezone when missing."""
    raw = value.strip()
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None and default_tz is not None:
        parsed = parsed.replace(tzinfo=default_tz)
    return parsed
