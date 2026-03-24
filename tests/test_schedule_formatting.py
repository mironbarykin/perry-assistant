from __future__ import annotations

import datetime as dt

from perry_assistant.constants import BERLIN_TZ
from perry_assistant.domain.models import EventView, WeatherSnapshot
from perry_assistant.services.schedule_service import ScheduleService, check_school_practice_gap


class FakeCalendarClient:
    def __init__(self, mapping: dict[dt.date, list[EventView]]) -> None:
        self.mapping = mapping

    def get_events_for_date(self, target_date: dt.datetime) -> list[EventView]:
        return self.mapping.get(target_date.date(), [])


class FakeWeatherClient:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, float], dt.datetime]] = []

    def get_weather(self, location: dict[str, float], target_dt: dt.datetime) -> WeatherSnapshot:
        self.calls.append((location, target_dt))
        return WeatherSnapshot(temp=18.0, wind_speed=2.0, wind_deg=210.0, rain=False, description="clear")


def test_school_practice_gap_warning():
    now = dt.datetime(2026, 2, 20, 12, 0, tzinfo=dt.UTC)
    events = [
        EventView(start=now.replace(hour=8), end=now.replace(hour=15), line="School day", is_basketball=False, is_all_day=False),
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


def test_day_events_text_formats_all_day_without_prefix():
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
    assert "School trip" in message
    assert "all-day -" not in message


def test_morning_digest_with_school_contains_two_weather_lines_and_location_prompt():
    target = dt.datetime.now(BERLIN_TZ).replace(hour=8, minute=30, second=0, microsecond=0)
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
    weather = FakeWeatherClient()
    service = ScheduleService(FakeCalendarClient(mapping), weather)
    digest = service.morning_digest(
        {"lat": 1, "lon": 2},
        {"lat": 3, "lon": 4},
        current_coords={"lat": 5, "lon": 6},
        location_city_label="Meerbusch",
        yesterday_usage_line="📊 Yesterday Perry was used 5 times, 2 of those by parents",
    )
    assert "School lessons" in digest
    assert "🏠 " in digest
    assert "🏫 " in digest
    assert "🏠-" not in digest
    assert "🏫-" not in digest
    assert "Location changed? /setweatherloc" in digest
    assert digest.strip().endswith("📊 Yesterday Perry was used 5 times, 2 of those by parents")
    assert len(weather.calls) == 2
    first_call = weather.calls[0]
    second_call = weather.calls[1]
    assert first_call[0] == {"lat": 1, "lon": 2}  # home_coords (not current_coords)
    assert first_call[1].hour == 6 and first_call[1].minute == 30
    assert second_call[1] == target.replace(hour=14)


def test_morning_digest_without_school_skips_weather_lines():
    target = dt.datetime.now(BERLIN_TZ).replace(hour=8, minute=30, second=0, microsecond=0)
    mapping = {
        target.date(): [
            EventView(
                start=target.replace(hour=16),
                end=target.replace(hour=18),
                line="Basketball practice",
                is_basketball=True,
                is_all_day=False,
            ),
        ]
    }
    weather = FakeWeatherClient()
    service = ScheduleService(FakeCalendarClient(mapping), weather)
    digest = service.morning_digest({"lat": 1, "lon": 2}, {"lat": 3, "lon": 4}, location_city_label="home")
    assert "🏠 " not in digest
    assert "🏠-" not in digest
    assert "🏫 " not in digest
    assert "🏫-" not in digest
    assert "Location changed? /setweatherloc" in digest
    assert len(weather.calls) == 0
