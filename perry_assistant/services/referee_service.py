from __future__ import annotations

import datetime as dt
import html
import logging
import re
from dataclasses import asdict
from urllib.parse import quote_plus

from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from perry_assistant.config import AppConfig
from perry_assistant.constants import CANCEL_COLOR_ID
from perry_assistant.domain.models import RefereeAssignment
from perry_assistant.integrations.calendar_client import (
    CalendarClient,
    assignment_datetime,
    league_short_name,
    parse_google_datetime,
    sanitize_event_location,
)
from perry_assistant.integrations.gmail_client import GmailClient
from perry_assistant.integrations.gym_client import GymClient
from perry_assistant.storage.json_store import read_json, write_json
from perry_assistant.utils import clean_text


logger = logging.getLogger(__name__)

ICON_BUSY = "\U0001F645\u200d\u2642\ufe0f"  # 🙅‍♂️
ICON_CLOSE = "\U0001F44C"  # 👌
ICON_FREE = "\U0001F44D"  # 👍
ICON_UNKNOWN = "\u2754"  # ❔


MOJIBAKE_MAP = {
    "ÃƒÂ¤": "Ã¤",
    "ÃƒÂ¶": "Ã¶",
    "ÃƒÂ¼": "Ã¼",
    "Ãƒâ€ž": "Ã„",
    "Ãƒâ€“": "Ã–",
    "ÃƒÅ“": "Ãœ",
    "ÃƒÅ¸": "ÃŸ",
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
    if "ansetzungen" in subject_l and ("geÃ¤ndert" in subject_l or "geaendert" in subject_l):
        return "AENDERUNG"
    if "ansetzungen" in body_l and ("geÃ¤ndert" in body_l or "geaendert" in body_l):
        return "AENDERUNG"
    if "sr-rÃ¼ckzug" in subject_l or "sr-rueckzug" in subject_l or "rÃ¼ckzug" in subject_l:
        return "RUECKZUG"
    return None


def parse_referee_email(content: dict[str, str]) -> list[RefereeAssignment] | None:
    subject = _fix_mojibake(content.get("subject", ""))
    body = _fix_mojibake(content.get("content", ""))
    email_type = detect_email_type(subject, body)
    if not email_type:
        return None

    sections = [body]
    if re.search(r"\d+\.\s*Ansetzung:", body):
        sections = [part for part in re.split(r"\d+\.\s*Ansetzung:\s*", body) if part.strip()]

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

        if not any(data.get(key) for key in ("date", "time", "liga", "spielnummer", "teams", "hall_code")):
            continue
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

    liga_match = re.search(r"Liga:\s*([^\n]+)", body, re.IGNORECASE)
    if liga_match:
        info["liga"] = liga_match.group(1).strip()

    spielnr_match = re.search(r"Spiel(?:-Nr\.?|nummer)\s*:\s*([^\n]+)", body, re.IGNORECASE)
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

    date_match = re.search(
        r"Datum:\s*(?:[A-Za-zÄÖÜäöü]{2,4},\s*)?(\d{2}\.\d{2}\.\d{4})",
        body,
        re.IGNORECASE,
    )
    time_match = re.search(r"Zeit:\s*(\d{2}:\d{2})", body, re.IGNORECASE)
    if date_match and not info["date"]:
        info["date"] = date_match.group(1)
    if time_match and not info["time"]:
        info["time"] = time_match.group(1)

    home_match = re.search(r"Heimmannschaft:\s*([^\n]+)", body)
    away_match = re.search(r"Gastmannschaft:\s*([^\n]+)", body)
    if home_match and away_match:
        info["teams"] = f"{home_match.group(1).strip()} - {away_match.group(1).strip()}"
    else:
        teams_match = re.search(r"Begegnung:\s*([^\n]+)", body, re.IGNORECASE)
        if teams_match:
            info["teams"] = teams_match.group(1).strip()

    hall_match = re.search(r"Spielhalle:\s*([^\n]+?)\s*\((\d{3}[A-Z]\d{3})\)", body)
    if hall_match:
        info["location"] = hall_match.group(1).strip()
        info["hall_code"] = hall_match.group(2).strip()
        address_match = re.search(r"Spielhalle:.*\)\s*\n\s*([^\n]+)", body)
        if address_match:
            info["address"] = address_match.group(1).strip()
    else:
        hall_code_match = re.search(r"Halle:\s*(\d{3}[A-Z]\d{3})", body, re.IGNORECASE)
        if hall_code_match:
            hall_code = hall_code_match.group(1).strip()
            info["hall_code"] = hall_code
            info["location"] = hall_code
        else:
            hall_location_match = re.search(r"Halle:\s*([^\n]+)", body, re.IGNORECASE)
            if hall_location_match:
                info["location"] = hall_location_match.group(1).strip()

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
        location_for_event = self._event_location(assignment)
        when_where_line = self._when_where_line(assignment)

        if assignment_type == "ANSETZUNG":
            event_id = self._calendar.create_referee_event(assignment, location_for_event)
            if event_id:
                self._update_event_map(None, assignment, event_id)
            conflict = self._check_game_conflict(assignment_datetime(assignment))
            icon = self._icon_for_conflict(conflict)
            message = self._notification_text(
                icon=icon,
                assignment=assignment,
                assignment_type=assignment_type,
                when_where_line=when_where_line,
                multiple=multiple,
            )
            await self._notify_admin(context, message, disable_notification=conflict == "BLOCK")
            return

        if assignment_type == "UMBESETZUNG":
            icon, _status_text, available = self._umbesetzung_availability(assignment)
            message = self._notification_text(
                icon=icon,
                assignment=assignment,
                assignment_type=assignment_type,
                when_where_line=when_where_line,
                multiple=multiple,
            )
            await self._notify_admin(context, message, disable_notification=not available)
            return

        if assignment_type in {"VERLEGUNG", "AENDERUNG"}:
            event_id = self._find_existing_event(assignment)
            available, reason = self._check_availability(assignment)
            icon = ICON_FREE if available else ICON_BUSY
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
                suffix = ""
            else:
                suffix = " (event not found)"
            message = self._notification_text(
                icon=icon,
                assignment=assignment,
                assignment_type=assignment_type,
                when_where_line=when_where_line,
                multiple=multiple,
                header_suffix=suffix,
            )
            if reason and not available:
                message = f"{message}\n{reason}"
            await self._notify_admin(context, message)
            return

        if assignment_type in {"ABSAGE", "RUECKZUG"}:
            event_id = self._find_existing_event(assignment)
            if event_id:
                self._calendar.cancel_referee_event(event_id, assignment, CANCEL_COLOR_ID)
                suffix = " (cancelled)"
            else:
                suffix = " (event not found)"
            message = self._notification_text(
                icon=ICON_UNKNOWN,
                assignment=assignment,
                assignment_type=assignment_type,
                when_where_line=when_where_line,
                multiple=multiple,
                header_suffix=suffix,
            )
            await self._notify_admin(context, message)
            return

        message = self._notification_text(
            icon=ICON_UNKNOWN,
            assignment=assignment,
            assignment_type=assignment_type,
            when_where_line=when_where_line,
            multiple=multiple,
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
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            disable_notification=disable_notification,
        )

    def _notification_text(
        self,
        icon: str,
        assignment: RefereeAssignment,
        assignment_type: str,
        when_where_line: str,
        multiple: bool = False,
        header_suffix: str = "",
    ) -> str:
        type_label = f"2x {assignment_type}" if multiple else assignment_type
        header = f"{icon} {type_label} @ {self._liga_short_for_notification(assignment)}"
        if assignment.spielnummer:
            header = f"{header} #{assignment.spielnummer}"
        if header_suffix:
            header = f"{header}{header_suffix}"
        return "\n".join([html.escape(header), when_where_line, html.escape(assignment.teams or "-")])

    def _liga_short_for_notification(self, assignment: RefereeAssignment) -> str:
        if not assignment.liga:
            return "-"
        return league_short_name(assignment)

    def _when_where_line(self, assignment: RefereeAssignment) -> str:
        date_text = self._weekday_date(assignment.date)
        time_text = assignment.time or "-"
        address_text, maps_url = self._notification_address_with_map(assignment)

        line = html.escape(f"{date_text} {time_text}".strip())
        if address_text:
            if maps_url:
                url = html.escape(maps_url, quote=True)
                label = html.escape(address_text)
                line = f'{line} @ <a href="{url}">{label}</a>'
            else:
                line = f"{line} @ {html.escape(address_text)}"
        return line

    def _notification_address_with_map(self, assignment: RefereeAssignment) -> tuple[str, str | None]:
        base_address = self._event_location(assignment) or assignment.location or assignment.hall_code or ""
        display_address = base_address

        if assignment.hall_code and assignment.hall_code not in display_address:
            display_address = f"{display_address} ({assignment.hall_code})".strip()

        map_query = base_address or assignment.address or assignment.location or assignment.hall_code
        maps_url = f"https://maps.google.com/?q={quote_plus(map_query)}" if map_query else None
        return display_address.strip(), maps_url

    @staticmethod
    def _weekday_date(date_text: str | None) -> str:
        if not date_text:
            return "-"
        try:
            parsed = dt.datetime.strptime(date_text, "%d.%m.%Y")
        except ValueError:
            return date_text
        return parsed.strftime("%A %d.%m.%Y")

    @staticmethod
    def _icon_for_conflict(conflict: str) -> str:
        if conflict == "BLOCK":
            return ICON_BUSY
        if conflict == "WARN":
            return ICON_CLOSE
        if conflict == "OK":
            return ICON_FREE
        return ICON_UNKNOWN

    def _event_location(self, assignment: RefereeAssignment) -> str | None:
        if assignment.address:
            return sanitize_event_location(assignment.address)
        if assignment.hall_code:
            gym = self._gym.get_gym_address(assignment.hall_code)
            if gym:
                return sanitize_event_location(gym)
        if assignment.location:
            return sanitize_event_location(assignment.location)
        return assignment.hall_code

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

        teams = clean_text(assignment.teams)
        hall_code = clean_text(assignment.hall_code)

        for event in self._calendar.get_referee_events_for_day(target_dt):
            event_id = self._matching_event_id(event, target_dt, teams, hall_code)
            if event_id:
                return event_id

        future_events = self._calendar.get_future_referee_game_events(target_dt - dt.timedelta(hours=6))
        for event in future_events:
            event_id = self._matching_event_id(event, target_dt, teams, hall_code)
            if event_id:
                return event_id
        return None

    def _matching_event_id(
        self,
        event: dict[str, object],
        target_dt: dt.datetime,
        teams: str,
        hall_code: str,
    ) -> str | None:
        start_raw = event.get("start", {}).get("dateTime") if isinstance(event.get("start"), dict) else None
        event_start = parse_google_datetime(start_raw)
        if not event_start:
            return None
        if abs((event_start - target_dt).total_seconds()) >= 7200:
            return None

        summary = clean_text(str(event.get("summary", "")))
        description = clean_text(str(event.get("description", "")))
        location = clean_text(str(event.get("location", "")))

        if teams and teams not in summary and teams not in description:
            return None
        if hall_code and hall_code not in description and hall_code not in location:
            return None

        event_id = event.get("id")
        return str(event_id) if event_id else None

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

    def _umbesetzung_availability(self, assignment: RefereeAssignment) -> tuple[str, str, bool]:
        target_start = assignment_datetime(assignment)
        if not target_start:
            return ICON_BUSY, "BUSY (missing date/time).", False

        target_end = target_start + dt.timedelta(hours=2)
        min_gap_hours: float | None = None

        for event_start, event_end in self._availability_event_intervals(target_start):
            gap_hours = self._interval_gap_hours(target_start, target_end, event_start, event_end)
            if min_gap_hours is None or gap_hours < min_gap_hours:
                min_gap_hours = gap_hours

        if min_gap_hours is None:
            return ICON_FREE, "FREE (no nearby calendar events).", True
        if min_gap_hours < 1:
            return ICON_BUSY, f"BUSY ({min_gap_hours:.1f}h gap).", False
        if min_gap_hours < 2:
            return ICON_CLOSE, f"FREE but close ({min_gap_hours:.1f}h gap).", True
        return ICON_FREE, f"FREE ({min_gap_hours:.1f}h gap).", True

    def _availability_event_intervals(
        self,
        target_start: dt.datetime,
    ) -> list[tuple[dt.datetime, dt.datetime]]:
        intervals: list[tuple[dt.datetime, dt.datetime]] = []

        referee_events = self._calendar.get_future_referee_game_events(target_start - dt.timedelta(hours=6))
        for event in referee_events:
            start_raw = event.get("start", {}).get("dateTime")
            end_raw = event.get("end", {}).get("dateTime")
            event_start = parse_google_datetime(start_raw)
            if not event_start:
                continue
            event_end = parse_google_datetime(end_raw) or (event_start + dt.timedelta(hours=2))
            intervals.append((event_start, event_end))

        for day_offset in (-1, 0, 1):
            day = target_start + dt.timedelta(days=day_offset)
            for event in self._calendar.get_events_for_date(day):
                if event.is_all_day or not event.start:
                    continue
                event_end = event.end or (event.start + dt.timedelta(hours=2))
                intervals.append((event.start, event_end))

        return intervals

    @staticmethod
    def _interval_gap_hours(
        start_a: dt.datetime,
        end_a: dt.datetime,
        start_b: dt.datetime,
        end_b: dt.datetime,
    ) -> float:
        if end_a <= start_b:
            return (start_b - end_a).total_seconds() / 3600
        if end_b <= start_a:
            return (start_a - end_b).total_seconds() / 3600
        return 0.0

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
