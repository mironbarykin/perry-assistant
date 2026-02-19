from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import asdict

from telegram.ext import ContextTypes

from perry_assistant.config import AppConfig
from perry_assistant.constants import CANCEL_COLOR_ID
from perry_assistant.domain.models import RefereeAssignment
from perry_assistant.integrations.calendar_client import (
    CalendarClient,
    assignment_datetime,
    parse_google_datetime,
)
from perry_assistant.integrations.gmail_client import GmailClient
from perry_assistant.integrations.gym_client import GymClient
from perry_assistant.storage.json_store import read_json, write_json
from perry_assistant.utils import clean_text


logger = logging.getLogger(__name__)


MOJIBAKE_MAP = {
    "Ã¤": "ä",
    "Ã¶": "ö",
    "Ã¼": "ü",
    "Ã„": "Ä",
    "Ã–": "Ö",
    "Ãœ": "Ü",
    "ÃŸ": "ß",
}


def _fix_mojibake(text: str) -> str:
    for bad, good in MOJIBAKE_MAP.items():
        text = text.replace(bad, good)
    return text


def detect_email_type(subject: str, body: str) -> str | None:
    subject_l = subject.lower()
    body_l = body.lower()

    if "sr-ansetzung" in subject_l:
        return "ANSETZUNG"
    if "umbesetzung" in subject_l or "umbesetzung" in body_l:
        return "UMBESETZUNG"
    if "spielverlegung/spielabsage" in subject_l or "spielverlegung" in subject_l:
        if "abgesagt" in body_l or "absage" in body_l or "aufgehoben" in body_l:
            return "ABSAGE"
        return "VERLEGUNG"
    if "ansetzungen" in subject_l and ("geändert" in subject_l or "geaendert" in subject_l):
        return "AENDERUNG"
    if "ansetzungen" in body_l and ("geändert" in body_l or "geaendert" in body_l):
        return "AENDERUNG"
    if "sr-rückzug" in subject_l or "sr-rueckzug" in subject_l or "rückzug" in subject_l:
        return "RUECKZUG"
    return None


def parse_referee_email(content: dict[str, str]) -> list[RefereeAssignment] | None:
    subject = _fix_mojibake(content.get("subject", ""))
    body = _fix_mojibake(content.get("content", ""))
    email_type = detect_email_type(subject, body)
    if not email_type:
        return None

    sections = [body]
    if "1. Ansetzung:" in body:
        sections = re.split(r"\d+\.\s*Ansetzung:", body)[1:]

    parsed: list[RefereeAssignment] = []
    for section in sections:
        data = _extract_basic_fields(section)
        data.update(_extract_old_new_fields(section))
        data["type"] = email_type

        if data.get("new_date") and data.get("new_time"):
            data["date"] = data.get("new_date")
            data["time"] = data.get("new_time")
            data["location"] = data.get("new_location") or data.get("location")
            data["hall_code"] = data.get("new_hall_code") or data.get("hall_code")
            data["address"] = data.get("new_address") or data.get("address")

        parsed.append(RefereeAssignment(**data))

    return parsed or None


def _extract_basic_fields(body: str) -> dict:
    info = {
        "date": None,
        "time": None,
        "liga": None,
        "spielnummer": None,
        "teams": None,
        "hall_code": None,
        "location": None,
        "address": None,
        "referees": None,
    }

    liga_match = re.search(r"Liga:\s*([^\n]+)", body)
    if liga_match:
        info["liga"] = liga_match.group(1).strip()

    spielnr_match = re.search(r"Spielnummer:\s*([0-9]+)", body)
    if spielnr_match:
        info["spielnummer"] = spielnr_match.group(1).strip()

    start_match = re.search(r"Spielbeginn:\s*(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})", body)
    if start_match:
        info["date"] = start_match.group(1)
        info["time"] = start_match.group(2)

    datetime_match = re.search(r"Datum,\s*Uhrzeit:\s*(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})", body)
    if datetime_match and not info["date"]:
        info["date"] = datetime_match.group(1)
        info["time"] = datetime_match.group(2)

    home_match = re.search(r"Heimmannschaft:\s*([^\n]+)", body)
    away_match = re.search(r"Gastmannschaft:\s*([^\n]+)", body)
    if home_match and away_match:
        info["teams"] = f"{home_match.group(1).strip()} - {away_match.group(1).strip()}"

    hall_match = re.search(r"Spielhalle:\s*([^\n]+?)\s*\((\d{3}[A-Z]\d{3})\)", body)
    if hall_match:
        info["location"] = hall_match.group(1).strip()
        info["hall_code"] = hall_match.group(2).strip()
        address_match = re.search(r"Spielhalle:.*\)\s*\n\s*([^\n]+)", body)
        if address_match:
            info["address"] = address_match.group(1).strip()

    refs: list[str] = []
    for label in ("SR1", "SR2", "Schiedsrichter 1", "Schiedsrichter 2"):
        ref_match = re.search(rf"{label}:\s*([^\n]+)", body)
        if not ref_match:
            ref_match = re.search(rf"{label}\s+([^\n]+)", body)
        if ref_match:
            refs.append(ref_match.group(1).strip())
    if refs:
        info["referees"] = refs

    return info


def _extract_old_new_fields(body: str) -> dict:
    info = {
        "old_date": None,
        "old_time": None,
        "old_location": None,
        "old_hall_code": None,
        "old_address": None,
        "new_date": None,
        "new_time": None,
        "new_location": None,
        "new_hall_code": None,
        "new_address": None,
    }

    old_dt = re.search(
        r"Von bisher:.*?Datum,\s*Uhrzeit:\s*(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})",
        body,
        re.S,
    )
    if old_dt:
        info["old_date"] = old_dt.group(1)
        info["old_time"] = old_dt.group(2)
        old_hall = re.search(
            r"Von bisher:.*?Spielhalle:\s*([^\n]+?)\s*\((\d{3}[A-Z]\d{3})\)",
            body,
            re.S,
        )
        if old_hall:
            info["old_location"] = old_hall.group(1).strip()
            info["old_hall_code"] = old_hall.group(2).strip()
            old_addr = re.search(r"Von bisher:.*?Spielhalle:.*\)\s*\n\s*([^\n]+)", body, re.S)
            if old_addr:
                info["old_address"] = old_addr.group(1).strip()

    new_dt = re.search(
        r"auf neu:.*?Datum,\s*Uhrzeit:\s*(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})",
        body,
        re.S | re.IGNORECASE,
    )
    if new_dt:
        info["new_date"] = new_dt.group(1)
        info["new_time"] = new_dt.group(2)
        new_hall = re.search(
            r"auf neu:.*?Spielhalle:\s*([^\n]+?)\s*\((\d{3}[A-Z]\d{3})\)",
            body,
            re.S | re.IGNORECASE,
        )
        if new_hall:
            info["new_location"] = new_hall.group(1).strip()
            info["new_hall_code"] = new_hall.group(2).strip()
            new_addr = re.search(
                r"auf neu:.*?Spielhalle:.*\)\s*\n\s*([^\n]+)",
                body,
                re.S | re.IGNORECASE,
            )
            if new_addr:
                info["new_address"] = new_addr.group(1).strip()

    return info


class RefereeService:
    def __init__(
        self,
        config: AppConfig,
        gmail_client: GmailClient,
        calendar_client: CalendarClient,
        gym_client: GymClient,
    ) -> None:
        self._config = config
        self._gmail = gmail_client
        self._calendar = calendar_client
        self._gym = gym_client

    async def process_new_emails(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        processed_ids = read_json(self._config.processed_emails_file, [])
        processed_ids = processed_ids[-100:]
        processed_set = set(processed_ids)

        messages = self._gmail.get_basketball_email_ids(max_results=20)

        for meta in messages:
            msg_id = meta.get("id")
            if not msg_id or msg_id in processed_set:
                continue

            content = self._gmail.get_message_content(msg_id)
            assignments = parse_referee_email(content)
            if not assignments:
                processed_ids.append(msg_id)
                processed_set.add(msg_id)
                processed_ids = processed_ids[-100:]
                continue

            multiple = len(assignments) > 1
            for assignment in assignments:
                await self._handle_assignment(context, assignment, multiple)

            processed_ids.append(msg_id)
            processed_set.add(msg_id)
            processed_ids = processed_ids[-100:]
            write_json(self._config.processed_emails_file, processed_ids)

    async def _handle_assignment(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        assignment: RefereeAssignment,
        multiple: bool,
    ) -> None:
        assignment_type = assignment.type
        prefix = "BASKETBALL 2x" if multiple else "BASKETBALL"
        location_text = self._notification_location(assignment)
        location_for_event = self._event_location(assignment)

        if assignment_type == "ANSETZUNG":
            event_id = self._calendar.create_referee_event(assignment, location_for_event)
            if event_id:
                self._update_event_map(None, assignment, event_id)
            conflict_icon = self._check_game_conflict(assignment_datetime(assignment))
            message = (
                f"{conflict_icon} {prefix} ANSETZUNG\n"
                f"{assignment.liga or '-'}\n"
                f"{assignment.teams or '-'}\n"
                f"{assignment.date or '-'} {assignment.time or '-'} {location_text}"
            )
            await self._notify_admin(context, message, disable_notification="BLOCK" in message)
            return

        if assignment_type == "UMBESETZUNG":
            available, reason = self._check_availability(assignment)
            status = "Available" if available else "Not available"
            if reason:
                status = f"{status} - {reason}"
            message = (
                f"{prefix} UMBESETZUNG\n"
                f"{assignment.liga or '-'}\n"
                f"{assignment.teams or '-'}\n"
                f"{assignment.date or '-'} {assignment.time or '-'} {location_text}\n"
                f"{status}"
            )
            await self._notify_admin(context, message, disable_notification=not available)
            return

        if assignment_type in {"VERLEGUNG", "AENDERUNG"}:
            event_id = self._find_existing_event(assignment)
            available, reason = self._check_availability(assignment)
            warning = f"\nWarning: {reason}" if not available and reason else ""
            if event_id:
                self._calendar.update_referee_event(event_id, assignment, location_for_event)
                old_assignment = None
                if assignment.old_date and assignment.old_time:
                    old_assignment = RefereeAssignment(
                        type=assignment.type,
                        date=assignment.old_date,
                        time=assignment.old_time,
                        teams=assignment.teams,
                        hall_code=assignment.old_hall_code or assignment.hall_code,
                    )
                self._update_event_map(old_assignment, assignment, event_id)
                found_text = ""
            else:
                found_text = " (event not found)"
            message = (
                f"{prefix} {assignment_type}{found_text}\n"
                f"{assignment.liga or '-'}\n"
                f"{assignment.teams or '-'}\n"
                f"{assignment.date or '-'} {assignment.time or '-'} {location_text}{warning}"
            )
            await self._notify_admin(context, message)
            return

        if assignment_type in {"ABSAGE", "RUECKZUG"}:
            event_id = self._find_existing_event(assignment)
            if event_id:
                self._calendar.cancel_referee_event(event_id, assignment, CANCEL_COLOR_ID)
                text_suffix = "\nMarked as cancelled."
            else:
                text_suffix = " (event not found)"
            message = (
                f"{prefix} {assignment_type}{text_suffix}\n"
                f"{assignment.liga or '-'}\n"
                f"{assignment.teams or '-'}\n"
                f"{assignment.date or '-'} {assignment.time or '-'} {location_text}"
            )
            await self._notify_admin(context, message)
            return

        message = (
            f"{prefix} {assignment_type}\n"
            f"{assignment.liga or '-'}\n"
            f"{assignment.teams or '-'}\n"
            f"{assignment.date or '-'} {assignment.time or '-'} {location_text}"
        )
        await self._notify_admin(context, message)

    async def _notify_admin(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        text: str,
        disable_notification: bool = False,
    ) -> None:
        await context.bot.send_message(
            chat_id=self._config.miron_id,
            text=text,
            disable_notification=disable_notification,
        )

    def _event_location(self, assignment: RefereeAssignment) -> str | None:
        if assignment.hall_code:
            gym = self._gym.get_gym_address(assignment.hall_code)
            if gym:
                return f"{gym} ({assignment.hall_code})"
            if assignment.location:
                return f"{assignment.location} ({assignment.hall_code})"
            return assignment.hall_code
        return assignment.address or assignment.location

    def _notification_location(self, assignment: RefereeAssignment) -> str:
        if not assignment.hall_code:
            return f"@ {assignment.location}" if assignment.location else ""
        if assignment.hall_code == assignment.location:
            gym = self._gym.get_gym_address(assignment.hall_code)
            return f"@ {gym or assignment.hall_code} ({assignment.hall_code})"
        return f"@ {assignment.location or '-'} ({assignment.hall_code})"

    def _load_event_map(self) -> dict[str, str]:
        return read_json(self._config.referee_events_file, {})

    def _save_event_map(self, payload: dict[str, str]) -> None:
        write_json(self._config.referee_events_file, payload)

    def _build_key(self, assignment: RefereeAssignment | None) -> str | None:
        if not assignment:
            return None
        if not assignment.date or not assignment.time or not assignment.teams or not assignment.hall_code:
            return None
        return clean_text(f"{assignment.date}|{assignment.time}|{assignment.teams}|{assignment.hall_code}")

    def _update_event_map(
        self,
        old_assignment: RefereeAssignment | None,
        new_assignment: RefereeAssignment,
        event_id: str,
    ) -> None:
        data = self._load_event_map()
        old_key = self._build_key(old_assignment)
        if old_key and old_key in data:
            data.pop(old_key, None)
        new_key = self._build_key(new_assignment)
        if new_key:
            data[new_key] = event_id
        self._save_event_map(data)

    def _find_existing_event(self, assignment: RefereeAssignment) -> str | None:
        data = self._load_event_map()
        old_assignment = RefereeAssignment(
            type=assignment.type,
            date=assignment.old_date,
            time=assignment.old_time,
            teams=assignment.teams,
            hall_code=assignment.old_hall_code or assignment.hall_code,
        )
        for candidate in (old_assignment, assignment):
            key = self._build_key(candidate)
            if not key:
                continue
            event_id = data.get(key)
            if not event_id:
                continue
            try:
                self._calendar.get_event(event_id)
                return event_id
            except Exception:  # noqa: BLE001
                logger.warning("Mapped event id %s no longer exists.", event_id)

        target_dt = assignment_datetime(assignment)
        if not target_dt:
            return None
        events = self._calendar.get_referee_events_for_day(target_dt)
        teams = clean_text(assignment.teams)
        for event in events:
            start_raw = event.get("start", {}).get("dateTime")
            event_start = parse_google_datetime(start_raw)
            if not event_start:
                continue
            summary = clean_text(event.get("summary", ""))
            if teams and teams in summary and abs((event_start - target_dt).total_seconds()) < 3600:
                event_id = event.get("id")
                if event_id:
                    return event_id
        return None

    def _check_availability(self, assignment: RefereeAssignment) -> tuple[bool, str | None]:
        target_dt = assignment_datetime(assignment)
        if not target_dt:
            return True, None

        new_loc = assignment.hall_code or assignment.location or ""
        for event in self._calendar.get_referee_events_for_day(target_dt):
            start_raw = event.get("start", {}).get("dateTime")
            event_start = parse_google_datetime(start_raw)
            if not event_start:
                continue
            event_location = event.get("location", "") or ""
            same_location = (
                clean_text(new_loc) in clean_text(event_location)
                or clean_text(event_location) in clean_text(new_loc)
            )
            buffer_hours = 2 if same_location else 3
            diff_hours = abs((event_start - target_dt).total_seconds()) / 3600
            if diff_hours < buffer_hours:
                return False, f"Conflict within {buffer_hours}h."
        return True, None

    def _check_game_conflict(self, new_game_dt: dt.datetime | None) -> str:
        if not new_game_dt:
            return "UNKNOWN"
        events = self._calendar.get_events_for_date(new_game_dt)
        times = [
            event.start
            for event in events
            if event.start and ("game" in event.line.lower() or "practice" in event.line.lower())
        ]
        if not times:
            return "OK"

        min_diff = min(abs((candidate - new_game_dt).total_seconds()) / 3600 for candidate in times)
        if min_diff < 2:
            return "BLOCK"
        if min_diff < 3:
            return "WARN"
        return "OK"


def assignment_to_dict(assignment: RefereeAssignment) -> dict:
    return asdict(assignment)
