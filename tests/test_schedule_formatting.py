from __future__ import annotations

import datetime as dt

from perry_assistant.domain.models import EventView, WeatherSnapshot
from perry_assistant.services.schedule_service import ScheduleService, check_school_practice_gap


class FakeCalendarClient:
    def __init__(self, mapping: dict[dt.date, list[EventView]]) -> None:
        self.mapping = mapping

    def get_events_for_date(self, target_date: dt.datetime) -> list[EventView]:
        return self.mapping.get(target_date.date(), [])


class FakeWeatherClient:
    def get_weather(self, location: dict[str, float], target_dt: dt.datetime) -> WeatherSnapshot:
        return WeatherSnapshot(temp=18.0, wind_speed=2.0, wind_deg=210.0, rain=False, description="clear")


def test_school_practice_gap_warning():
    now = dt.datetime(2026, 2, 20, 12, 0, tzinfo=dt.UTC)
    events = [
        EventView(
            start=now.replace(hour=8),
            end=now.replace(hour=15),
            line="School day",
            is_basketball=False,
            is_all_day=False,
        ),
        EventView(
            start=now.replace(hour=16),
            end=now.replace(hour=18),
            line="Basketball practice",
            is_basketball=True,
            is_all_day=False,
        ),
    ]
    warning = check_school_practice_gap(events)
    assert warning is not None


def test_weekend_message_filters_basketball():
    today = dt.datetime.now(dt.UTC)
    saturday = (today + dt.timedelta((5 - today.weekday()) % 7)).date()
    sunday = (today + dt.timedelta((5 - today.weekday()) % 7) + dt.timedelta(days=1)).date()

    mapping = {
        saturday: [
            EventView(None, "A game 1", True, False, None),
            EventView(None, "Non basketball", False, False, None),
        ],
        sunday: [EventView(None, "A game 2", True, False, None)],
    }
    service = ScheduleService(FakeCalendarClient(mapping), FakeWeatherClient())
    message = service.weekend_message()
    assert "A game 1" in message
    assert "A game 2" in message
    assert "Non basketball" not in message


def test_day_events_text_formats_all_day_with_pin():
    target = dt.datetime(2026, 2, 20, 12, 0, tzinfo=dt.UTC)
    mapping = {
        target.date(): [
            EventView(
                start=target.replace(hour=0, minute=0),
                end=target.replace(hour=23, minute=59),
                line="all-day - School trip",
                is_basketball=False,
                is_all_day=True,
            ),
        ]
    }
    service = ScheduleService(FakeCalendarClient(mapping), FakeWeatherClient())
    message = service.day_events_text(target)
    assert "📌 School trip" in message
    assert "all-day -" not in message


def test_morning_digest_uses_route_icons():
    target = dt.datetime.now(dt.UTC)
    mapping = {
        target.date(): [
            EventView(
                start=target.replace(hour=8),
                end=target.replace(hour=14),
                line="School lessons",
                is_basketball=False,
                is_all_day=False,
            ),
        ]
    }
    service = ScheduleService(FakeCalendarClient(mapping), FakeWeatherClient())
    digest = service.morning_digest({"lat": 1, "lon": 2}, {"lat": 3, "lon": 4})
    assert "🏫" in digest
    assert "🏠" in digest
