from __future__ import annotations

import datetime as dt

from perry_assistant.constants import BERLIN_TZ
from perry_assistant.domain.models import EventView
from perry_assistant.integrations.calendar_client import CalendarClient
from perry_assistant.integrations.weather_client import WeatherClient, weather_message
from perry_assistant.utils import clean_text


def check_school_practice_gap(events: list[EventView]) -> str | None:
    school_end_times = [
        item.end for item in events if item.end is not None and "school" in clean_text(item.line)
    ]
    practice_start_times = [
        item.start
        for item in events
        if item.start is not None and "practice" in clean_text(item.line)
    ]

    if not school_end_times or not practice_start_times:
        return None

    school_end = max(school_end_times)
    practice_start = min(practice_start_times)
    gap_hours = (practice_start - school_end).total_seconds() / 3600
    if gap_hours < 2:
        return "Warning: less than 2 hours between school and practice."
    return None


class ScheduleService:
    def __init__(self, calendar_client: CalendarClient, weather_client: WeatherClient) -> None:
        self._calendar = calendar_client
        self._weather = weather_client

    def day_events_text(self, date: dt.datetime, label: str = "events") -> str:
        events = self._calendar.get_events_for_date(date)
        if not events:
            return f"No {label} found."
        return "\n".join(item.line for item in events)

    def today_message(self) -> str:
        now = dt.datetime.now(dt.UTC)
        return f"Today's events:\n{self.day_events_text(now, 'today events')}"

    def tomorrow_message(self) -> str:
        target = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
        return f"Tomorrow's events:\n{self.day_events_text(target, 'tomorrow events')}"

    def weekend_message(self) -> str:
        now = dt.datetime.now(dt.UTC)
        saturday = now + dt.timedelta((5 - now.weekday()) % 7)
        sunday = saturday + dt.timedelta(days=1)
        sat_events = [
            item.line for item in self._calendar.get_events_for_date(saturday) if item.is_basketball
        ]
        sun_events = [
            item.line for item in self._calendar.get_events_for_date(sunday) if item.is_basketball
        ]
        sat_text = "\n".join(sat_events) if sat_events else "No events"
        sun_text = "\n".join(sun_events) if sun_events else "No events"
        return (
            f"Weekend basketball events ({saturday.day}-{sunday.day})\n"
            f"Saturday:\n{sat_text}\n\n"
            f"Sunday:\n{sun_text}"
        )

    def morning_digest(self, home_coords: dict[str, float], school_coords: dict[str, float]) -> str:
        today = dt.datetime.now(BERLIN_TZ)
        events = self._calendar.get_events_for_date(today)
        events_text = "\n".join(item.line for item in events) if events else "No events"
        lines = [f"Good morning. Schedule for today:\n{events_text}"]

        school_events = [event for event in events if "school" in clean_text(event.line)]
        school_end = max((event.end for event in school_events if event.end), default=None)

        home_target = today.replace(hour=7, minute=0, second=0, microsecond=0)
        home_weather = self._weather.get_weather(home_coords, home_target)
        lines.append(f"Home route weather: {weather_message(home_weather)}")

        if school_end:
            school_weather = self._weather.get_weather(school_coords, school_end)
            lines.append(f"School end weather: {weather_message(school_weather)}")
        else:
            lines.append("No school event today.")

        gap_warning = check_school_practice_gap(events)
        if gap_warning:
            lines.append(gap_warning)
        return "\n\n".join(lines)

