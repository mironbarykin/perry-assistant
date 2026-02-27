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
        item.start for item in events if item.start is not None and "practice" in clean_text(item.line)
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

    def day_events_text(self, date: dt.datetime, label: str = "events", is_admin: bool = True) -> str:
        events = self._calendar.get_events_for_date(date)
        visible_events = self._visible_events(events, is_admin=is_admin)
        if not visible_events:
            return f"No {label} found."

        date_str = date.strftime("%A, %Y-%m-%d")
        lines = [self._display_line(item) for item in visible_events]
        return f"{date_str}\n" + "\n".join(lines)

    def today_message(self, is_admin: bool = False) -> str:
        now = dt.datetime.now(dt.UTC)
        return self.day_events_text(now, label="events", is_admin=is_admin)

    def tomorrow_message(self, is_admin: bool = False) -> str:
        target = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)
        return self.day_events_text(target, label="tomorrow events", is_admin=is_admin)

    def weekend_message(self, is_admin: bool = False) -> str:
        now = dt.datetime.now(dt.UTC)
        saturday = now + dt.timedelta((5 - now.weekday()) % 7)
        sunday = saturday + dt.timedelta(days=1)

        sat_events = self._visible_events(self._calendar.get_events_for_date(saturday), is_admin=is_admin)
        sun_events = self._visible_events(self._calendar.get_events_for_date(sunday), is_admin=is_admin)

        sat_text = "\n".join(self._display_line(item) for item in sat_events if item.is_basketball)
        sun_text = "\n".join(self._display_line(item) for item in sun_events if item.is_basketball)

        sat_date = saturday.strftime("%A, %Y-%m-%d")
        sun_date = sunday.strftime("%A, %Y-%m-%d")
        return (
            f"Weekend basketball events ({saturday.day}-{sunday.day})\n"
            f"Saturday: {sat_date}\n{sat_text or 'No events'}\n\n"
            f"Sunday: {sun_date}\n{sun_text or 'No events'}"
        )

    def morning_digest(
        self,
        home_coords: dict[str, float],
        school_coords: dict[str, float],
        current_coords: dict[str, float] | None = None,
        location_city_label: str = "home",
        yesterday_usage_line: str | None = None,
    ) -> str:
        today = dt.datetime.now(BERLIN_TZ)
        events = self._calendar.get_events_for_date(today)
        events_text = "\n".join(self._display_line(item) for item in events) if events else "No events"
        lines = [f"Good morning. Schedule for today:\n{events_text}"]

        active_coords = current_coords or home_coords
        school_events = [event for event in events if "school" in clean_text(event.line) and event.start]
        if school_events:
            first_school_start = min(event.start for event in school_events if event.start)
            end_candidates = [event.end or event.start for event in school_events if event.start]
            last_school_end = max(end_candidates) if end_candidates else None

            first_target = first_school_start - dt.timedelta(hours=1)
            first_weather = self._weather.get_weather(active_coords, first_target)
            lines.append(f"🏠- {weather_message(first_weather)}")

            if last_school_end:
                second_weather = self._weather.get_weather(school_coords, last_school_end)
                lines.append(f"🏫- {weather_message(second_weather)}")

        gap_warning = check_school_practice_gap(events)
        if gap_warning:
            lines.append(gap_warning)

        lines.append(f"Location changed? /setweatherloc")
        if yesterday_usage_line:
            lines.append(yesterday_usage_line)
        return "\n\n".join(lines)

    @staticmethod
    def _display_line(event: EventView) -> str:
        if event.is_all_day:
            line = event.line.strip()
            if line.lower().startswith("all-day - "):
                line = line[10:].strip()
            return line if line.startswith("📌 ") else f"📌 {line}"
        return event.line

    @staticmethod
    def _visible_events(events: list[EventView], is_admin: bool) -> list[EventView]:
        if is_admin:
            return sorted(events, key=lambda item: (not item.is_all_day, item.start is None, item.start))

        visible: list[EventView] = []
        for item in events:
            line = item.line.strip()
            if not item.is_all_day and line[:1].upper() == "P":
                continue
            visible.append(item)
        return sorted(visible, key=lambda item: (not item.is_all_day, item.start is None, item.start))
