from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

from perry_assistant.constants import BERLIN_TZ


logger = logging.getLogger(__name__)

SCOPES = ("https://www.googleapis.com/auth/calendar",)


class UntisCalendarClient:
    """Google Calendar client using a service account for Untis sync only."""

    def __init__(self, service_account_file) -> None:
        self._service_account_file = service_account_file
        self._service_cache = None

    def _service(self):
        if self._service_cache is not None:
            return self._service_cache
        creds = service_account.Credentials.from_service_account_file(
            str(self._service_account_file),
            scopes=SCOPES,
        )
        self._service_cache = build("calendar", "v3", credentials=creds)
        return self._service_cache

    def list_events(self, calendar_id: str, start_dt: dt.datetime, end_dt: dt.datetime) -> list[dict[str, Any]]:
        service = self._service()
        time_min = _as_utc_iso(start_dt)
        time_max = _as_utc_iso(end_dt)
        events: list[dict[str, Any]] = []
        page_token = None
        while True:
            payload = (
                service.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page_token,
                )
                .execute()
            )
            events.extend(payload.get("items", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return events

    def create_event(self, calendar_id: str, event: dict[str, Any]) -> str | None:
        service = self._service()
        created = service.events().insert(calendarId=calendar_id, body=event).execute()
        return created.get("id")

    def update_event(self, calendar_id: str, event_id: str, patch: dict[str, Any]) -> None:
        service = self._service()
        service.events().patch(calendarId=calendar_id, eventId=event_id, body=patch).execute()

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        service = self._service()
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()


def build_event_payload(summary: str, description: str, start_dt: dt.datetime, end_dt: dt.datetime) -> dict[str, Any]:
    return {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Berlin"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Berlin"},
    }


def _as_utc_iso(value: dt.datetime) -> str:
    localized = value if value.tzinfo else value.replace(tzinfo=BERLIN_TZ)
    return localized.astimezone(dt.UTC).isoformat()
