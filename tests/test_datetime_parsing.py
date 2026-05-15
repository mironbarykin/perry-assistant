from __future__ import annotations

import datetime as dt

from perry_assistant.bot.handlers.helpers import (
    parse_iso_datetime,
    parse_date_flexible,
    parse_local_datetime,
    parse_time_hhmm,
)
from perry_assistant.constants import BERLIN_TZ


def test_parse_time_hhmm_valid() -> None:
    parsed = parse_time_hhmm("19:30")
    assert parsed == dt.time(19, 30)


def test_parse_time_hhmm_invalid() -> None:
    assert parse_time_hhmm("25:30") is None


def test_parse_local_datetime_multiple_formats() -> None:
    parsed_a = parse_local_datetime(
        "2026-05-15 19:30",
        BERLIN_TZ,
        formats=("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"),
    )
    parsed_b = parse_local_datetime(
        "15.05.2026 19:30",
        BERLIN_TZ,
        formats=("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"),
    )

    assert parsed_a is not None
    assert parsed_b is not None
    assert parsed_a.year == 2026 and parsed_a.month == 5 and parsed_a.day == 15
    assert parsed_b.year == 2026 and parsed_b.month == 5 and parsed_b.day == 15


def test_parse_date_flexible_multiple_formats() -> None:
    assert parse_date_flexible("15.05.2026", formats=("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d")) == dt.date(2026, 5, 15)
    assert parse_date_flexible("15/05/2026", formats=("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d")) == dt.date(2026, 5, 15)
    assert parse_date_flexible("2026-05-15", formats=("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d")) == dt.date(2026, 5, 15)


def test_parse_iso_datetime_with_default_tz() -> None:
    parsed = parse_iso_datetime("2026-05-15T18:30:00", default_tz=dt.UTC)
    assert parsed is not None
    assert parsed.tzinfo is not None


def test_parse_iso_datetime_invalid() -> None:
    assert parse_iso_datetime("not-a-datetime", default_tz=dt.UTC) is None
