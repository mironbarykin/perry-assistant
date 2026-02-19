from __future__ import annotations

import datetime as dt
import logging
import pickle
from dataclasses import asdict
from typing import Any
from urllib.parse import quote_plus

from googleapiclient.discovery import build

from perry_assistant.config import AppConfig
from perry_assistant.constants import BERLIN_TZ, REFEREE_CALENDAR_NAME
from perry_assistant.domain.models import EventView, RefereeAssignment


logger = logging.getLogger(__name__)


def parse_google_datetime(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        if len(raw) == 10:
            return dt.datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=dt.UTC)
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


class CalendarClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def _service(self):
        creds = None
        if self._config.token_pickle_file.exists():
            with self._config.token_pickle_file.open("rb") as token_file:
                creds = pickle.load(token_file)
        return build("calendar", "v3", credentials=creds)

    def get_all_calendars(self) -> list[dict[str, Any]]:
        service = self._service()
        return service.calendarList().list().execute().get("items", [])

    def get_calendar_id_by_name(self, calendar_name: str = REFEREE_CALENDAR_NAME) -> str:
        calendars = self.get_all_calendars()
        for calendar in calendars:
            if calendar.get("summary", "").lower() == calendar_name.lower():
                return calendar["id"]
        for calendar in calendars:
            if calendar.get("primary"):
                return calendar["id"]
        return "primary"

    def get_events_for_date(self, target_date: dt.datetime) -> list[EventView]:
        service = self._service()
        start = target_date.astimezone(dt.UTC).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ).isoformat()
        end = target_date.astimezone(dt.UTC).replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=0,
        ).isoformat()

        events_all: list[EventView] = []
        for calendar in self.get_all_calendars():
            cal_symbol = (calendar.get("summary", "?") or "?")[0]
            is_basketball = "basketball" in calendar.get("summary", "").lower()
            events = service.events().list(
                calendarId=calendar["id"],
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy="startTime",
            ).execute().get("items", [])

            for event in events:
                event_view = self._format_event(event, cal_symbol, is_basketball)
                if event_view.is_all_day:
                    if event_view.start and event_view.start.date() == target_date.date():
                        events_all.append(event_view)
                else:
                    events_all.append(event_view)

        return sorted(events_all, key=lambda item: (not item.is_all_day, item.start is None, item.start))

    def _format_event(self, event: dict[str, Any], cal_symbol: str, is_basketball: bool) -> EventView:
        summary = event.get("summary", "No Title")
        start_raw = event.get("start", {}).get("dateTime", event.get("start", {}).get("date"))
        end_raw = event.get("end", {}).get("dateTime", event.get("end", {}).get("date"))
        location = event.get("location")

        is_all_day = "date" in event.get("start", {})
        start_dt = parse_google_datetime(start_raw)
        end_dt = parse_google_datetime(end_raw)

        if is_all_day:
            return EventView(start=start_dt, line=f"[all-day] {summary}", is_basketball=is_basketball, is_all_day=True, end=end_dt)

        start_text = start_dt.strftime("%H:%M") if start_dt else ""
        end_text = end_dt.strftime("%H:%M") if end_dt else ""
        if start_text and end_text:
            time_text = f"{start_text}-{end_text}"
        else:
            time_text = start_text

        address = ""
        if is_basketball and location:
            gmaps_url = f"https://maps.google.com/?q={quote_plus(location)}"
            address = f" ({gmaps_url})"

        line = f"{cal_symbol} {time_text} - {summary}{address}".strip()
        return EventView(start=start_dt, line=line, is_basketball=is_basketball, is_all_day=False, end=end_dt)

    def get_referee_events_for_day(self, target_date: dt.datetime) -> list[dict[str, Any]]:
        service = self._service()
        calendar_id = self.get_calendar_id_by_name(REFEREE_CALENDAR_NAME)

        start = target_date.astimezone(dt.UTC).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        ).isoformat()
        end = target_date.astimezone(dt.UTC).replace(
            hour=23,
            minute=59,
            second=59,
            microsecond=0,
        ).isoformat()

        return service.events().list(
            calendarId=calendar_id,
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])

    def get_event(self, event_id: str) -> dict[str, Any]:
        service = self._service()
        calendar_id = self.get_calendar_id_by_name(REFEREE_CALENDAR_NAME)
        return service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    def create_referee_event(self, assignment: RefereeAssignment, location: str | None) -> str | None:
        service = self._service()
        calendar_id = self.get_calendar_id_by_name(REFEREE_CALENDAR_NAME)

        start_dt = assignment_datetime(assignment)
        if not start_dt:
            return None
        end_dt = start_dt + dt.timedelta(hours=2)
        summary = f"Game: {assignment.teams}" if assignment.teams else "Game"
        description = build_assignment_description(assignment)

        event = {
            "summary": summary,
            "description": description,
            "location": location,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Berlin"},
        }
        created = service.events().insert(calendarId=calendar_id, body=event).execute()
        return created.get("id")

    def update_referee_event(self, event_id: str, assignment: RefereeAssignment, location: str | None) -> str | None:
        service = self._service()
        calendar_id = self.get_calendar_id_by_name(REFEREE_CALENDAR_NAME)
        start_dt = assignment_datetime(assignment)
        patch: dict[str, Any] = {
            "summary": f"Game: {assignment.teams}" if assignment.teams else "Game",
            "description": build_assignment_description(assignment),
            "location": location,
        }
        if start_dt:
            end_dt = start_dt + dt.timedelta(hours=2)
            patch["start"] = {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Berlin"}
            patch["end"] = {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Berlin"}
        updated = service.events().patch(calendarId=calendar_id, eventId=event_id, body=patch).execute()
        return updated.get("id")

    def cancel_referee_event(self, event_id: str, assignment: RefereeAssignment, cancel_color_id: str) -> str | None:
        service = self._service()
        calendar_id = self.get_calendar_id_by_name(REFEREE_CALENDAR_NAME)
        summary = f"Game: {assignment.teams}" if assignment.teams else "Game"
        if not summary.startswith("CANCELLED:"):
            summary = f"CANCELLED: {summary}"
        patch = {"summary": summary, "colorId": cancel_color_id}
        updated = service.events().patch(calendarId=calendar_id, eventId=event_id, body=patch).execute()
        return updated.get("id")


def assignment_datetime(assignment: RefereeAssignment) -> dt.datetime | None:
    if not assignment.date or not assignment.time:
        return None
    return dt.datetime.strptime(
        f"{assignment.date} {assignment.time}",
        "%d.%m.%Y %H:%M",
    ).replace(tzinfo=BERLIN_TZ)


def build_assignment_description(assignment: RefereeAssignment) -> str:
    lines: list[str] = []
    payload = asdict(assignment)
    for label, key in (
        ("Type", "type"),
        ("Liga", "liga"),
        ("Spielnummer", "spielnummer"),
        ("Halle", "hall_code"),
    ):
        value = payload.get(key)
        if value:
            lines.append(f"{label}: {value}")
    if assignment.referees:
        lines.append("Referees: " + ", ".join(assignment.referees))
    return "\n".join(lines)

