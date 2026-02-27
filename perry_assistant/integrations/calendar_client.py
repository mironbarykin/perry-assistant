from __future__ import annotations

import datetime as dt
import logging
import pickle
import re
from dataclasses import asdict
from typing import Any
from urllib.parse import quote_plus

from googleapiclient.discovery import build
from telegram.helpers import escape_markdown

from perry_assistant.config import AppConfig
from perry_assistant.constants import BERLIN_TZ, REFEREE_CALENDAR_NAME
from perry_assistant.domain.models import EventView, RefereeAssignment


logger = logging.getLogger(__name__)

RSO_MAP_QUERY = "Goerresstrasse 6, 40670 Meerbusch"
SMG_MAP_QUERY = "Moenkesweg 58, 40670 Meerbusch"


def parse_google_datetime(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        if len(raw) == 10:
            return dt.datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=dt.UTC)
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def utc_day_bounds(target_date: dt.datetime) -> tuple[str, str]:
    local = target_date if target_date.tzinfo else target_date.replace(tzinfo=BERLIN_TZ)
    local = local.astimezone(BERLIN_TZ)
    start_local = dt.datetime(local.year, local.month, local.day, 0, 0, 0, tzinfo=BERLIN_TZ)
    end_local = dt.datetime(local.year, local.month, local.day, 23, 59, 59, tzinfo=BERLIN_TZ)
    return start_local.astimezone(dt.UTC).isoformat(), end_local.astimezone(dt.UTC).isoformat()


class CalendarClient:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._service_cache = None
        self._calendar_list_cache: list[dict[str, Any]] | None = None
        self._calendar_list_cache_expires_at = dt.datetime.min.replace(tzinfo=dt.UTC)

    def _service(self):
        if self._service_cache is not None:
            return self._service_cache
        creds = None
        if self._config.token_pickle_file.exists():
            with self._config.token_pickle_file.open("rb") as token_file:
                creds = pickle.load(token_file)
        self._service_cache = build("calendar", "v3", credentials=creds)
        return self._service_cache

    def get_all_calendars(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        now = dt.datetime.now(dt.UTC)
        if not force_refresh and self._calendar_list_cache is not None and now < self._calendar_list_cache_expires_at:
            return list(self._calendar_list_cache)

        service = self._service()
        items = service.calendarList().list().execute().get("items", [])
        self._calendar_list_cache = items
        self._calendar_list_cache_expires_at = now + dt.timedelta(minutes=10)
        return list(items)

    def get_calendar_id_by_name(self, calendar_name: str = REFEREE_CALENDAR_NAME) -> str:
        calendars = self.get_all_calendars()
        selected = select_calendar_id(calendars, calendar_name)
        if selected:
            return selected
        return "primary"

    def get_events_for_date(self, target_date: dt.datetime) -> list[EventView]:
        service = self._service()
        start, end = utc_day_bounds(target_date)

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
        summary = escape_markdown(event.get("summary", "No Title"), version=1)
        start_raw = event.get("start", {}).get("dateTime", event.get("start", {}).get("date"))
        end_raw = event.get("end", {}).get("dateTime", event.get("end", {}).get("date"))
        location = event.get("location")

        is_all_day = "date" in event.get("start", {})
        start_dt = parse_google_datetime(start_raw)
        end_dt = parse_google_datetime(end_raw)

        if is_all_day:
            return EventView(
                start=start_dt,
                line=f"all-day - {summary}",
                is_basketball=is_basketball,
                is_all_day=True,
                end=end_dt,
            )

        start_text = start_dt.strftime("%H:%M") if start_dt else ""
        end_text = end_dt.strftime("%H:%M") if end_dt else ""
        time_text = f"{start_text}-{end_text}" if start_text and end_text else start_text

        address = ""
        if location:
            label, map_query = _location_link_parts(location)
            escaped_label = escape_markdown(label, version=1)
            gmaps_url = f"https://maps.google.com/?q={quote_plus(map_query)}"
            address = f" @ [{escaped_label}]({gmaps_url})"

        line = f"{cal_symbol} {time_text} - {summary}{address}".strip()
        return EventView(start=start_dt, line=line, is_basketball=is_basketball, is_all_day=False, end=end_dt)

    def get_referee_events_for_day(self, target_date: dt.datetime) -> list[dict[str, Any]]:
        service = self._service()
        calendar_id = self.get_calendar_id_by_name(REFEREE_CALENDAR_NAME)
        start, end = utc_day_bounds(target_date)

        return service.events().list(
            calendarId=calendar_id,
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy="startTime",
        ).execute().get("items", [])

    def get_future_referee_game_events(self, start_time: dt.datetime | None = None) -> list[dict[str, Any]]:
        service = self._service()
        calendar_id = self.get_calendar_id_by_name(REFEREE_CALENDAR_NAME)
        start = (start_time or dt.datetime.now(dt.UTC)).astimezone(dt.UTC).isoformat()
        events = service.events().list(
            calendarId=calendar_id,
            timeMin=start,
            singleEvents=True,
            orderBy="startTime",
            maxResults=2500,
        ).execute().get("items", [])
        return [event for event in events if "referee game" in event.get("summary", "").lower()]

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
        summary = referee_game_summary(assignment)
        description = build_assignment_description(assignment)

        event = {
            "summary": summary,
            "description": description,
            "location": sanitize_event_location(location),
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
            "summary": referee_game_summary(assignment),
            "description": build_assignment_description(assignment),
            "location": sanitize_event_location(location),
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
        summary = referee_game_summary(assignment)
        if not summary.startswith("CANCELLED:"):
            summary = f"CANCELLED: {summary}"
        patch = {"summary": summary, "colorId": cancel_color_id}
        updated = service.events().patch(calendarId=calendar_id, eventId=event_id, body=patch).execute()
        return updated.get("id")


def _location_link_parts(location: str) -> tuple[str, str]:
    normalized = _normalize_location(location)
    if "goerresstrasse" in normalized or "rso" in normalized:
        return "RSO", RSO_MAP_QUERY
    if "moenkesweg" in normalized or "monkesweg" in normalized or "smg" in normalized:
        return "SMG", SMG_MAP_QUERY
    return location, location


def _normalize_location(value: str) -> str:
    return (
        value.lower()
        .replace("\u00e4", "ae")
        .replace("\u00f6", "oe")
        .replace("\u00fc", "ue")
        .replace("\u00df", "ss")
        .replace("\u00c3\u00a4", "ae")
        .replace("\u00c3\u00b6", "oe")
        .replace("\u00c3\u00bc", "ue")
        .replace("\u00c3\u009f", "ss")
    )


def assignment_datetime(assignment: RefereeAssignment) -> dt.datetime | None:
    if not assignment.date or not assignment.time:
        return None
    return dt.datetime.strptime(
        f"{assignment.date} {assignment.time}",
        "%d.%m.%Y %H:%M",
    ).replace(tzinfo=BERLIN_TZ)


def referee_game_summary(assignment: RefereeAssignment) -> str:
    return f"{league_short_name(assignment)} Referee Game"


def league_short_name(assignment: RefereeAssignment) -> str:
    if assignment.liga:
        bracket_match = re.search(r"\(([^()]+)\)", assignment.liga)
        if bracket_match:
            value = bracket_match.group(1).strip()
            if value:
                return value
        token_match = re.search(r"[A-Za-z0-9-]+", assignment.liga)
        if token_match:
            return token_match.group(0)
    if assignment.spielnummer:
        return str(assignment.spielnummer).strip()
    return "GAME"


def sanitize_event_location(location: str | None) -> str | None:
    if not location:
        return location
    return re.sub(r"\s*\(\d{3}[A-Z]\d{3}\)\s*$", "", location).strip()


def select_calendar_id(calendars: list[dict[str, Any]], calendar_name: str) -> str | None:
    target = (calendar_name or "").strip().lower()
    if not target:
        return None

    exact: list[dict[str, Any]] = []
    contains: list[dict[str, Any]] = []
    basketball: list[dict[str, Any]] = []
    primary: str | None = None

    for calendar in calendars:
        summary = str(calendar.get("summary", "")).strip()
        summary_l = summary.lower()
        if calendar.get("primary"):
            primary = str(calendar.get("id"))
        if summary_l == target:
            exact.append(calendar)
            continue
        if target in summary_l or summary_l in target:
            contains.append(calendar)
        if "basketball" in target and "basketball" in summary_l:
            basketball.append(calendar)

    for bucket in (exact, contains, basketball):
        if bucket:
            non_primary = next((item for item in bucket if not item.get("primary")), None)
            picked = non_primary or bucket[0]
            return str(picked.get("id"))

    return primary


def build_assignment_description(assignment: RefereeAssignment) -> str:
    lines: list[str] = []
    payload = asdict(assignment)
    for label, key in (
        ("Type", "type"),
        ("Liga", "liga"),
        ("Spielnummer", "spielnummer"),
        ("Teams", "teams"),
        ("Halle", "hall_code"),
    ):
        value = payload.get(key)
        if value:
            lines.append(f"{label}: {value}")
    if assignment.referees:
        lines.append("Referees: " + ", ".join(assignment.referees))
    return "\n".join(lines)
