from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from perry_assistant.config import AppConfig
from perry_assistant.constants import BERLIN_TZ
from perry_assistant.domain.models import TimetableChange, UntisCredentials, UntisPeriod
from perry_assistant.integrations.untis_client import UntisClient
from perry_assistant.storage.json_store import read_json, write_json


logger = logging.getLogger(__name__)

# How many days ahead to check for changes
_LOOKAHEAD_DAYS = 14


def _period_key(period: UntisPeriod) -> str:
    return f"{period.date}_{period.start_time}_{period.subject}"


def _periods_equal(a: UntisPeriod, b: UntisPeriod) -> bool:
    return (
        a.code == b.code
        and a.subject == b.subject
        and a.teacher == b.teacher
        and a.room == b.room
        and a.start_time == b.start_time
        and a.end_time == b.end_time
    )


def detect_changes(
    old_periods: list[UntisPeriod],
    new_periods: list[UntisPeriod],
) -> list[TimetableChange]:
    """Compare two timetable snapshots and return a list of detected changes."""
    changes: list[TimetableChange] = []

    old_by_key: dict[str, UntisPeriod] = {_period_key(p): p for p in old_periods}
    new_by_key: dict[str, UntisPeriod] = {_period_key(p): p for p in new_periods}

    # Detect cancelled, restored, or modified
    for key, new_p in new_by_key.items():
        if key in old_by_key:
            old_p = old_by_key[key]
            if not _periods_equal(old_p, new_p):
                if new_p.code == "cancelled" and old_p.code != "cancelled":
                    changes.append(TimetableChange("cancelled", new_p, old_p))
                elif old_p.code == "cancelled" and new_p.code != "cancelled":
                    changes.append(TimetableChange("restored", new_p, old_p))
                else:
                    changes.append(TimetableChange("modified", new_p, old_p))
        else:
            # New period appeared
            if new_p.subject.lower() in {"ex", "exam", "sa", "klausur"}:
                changes.append(TimetableChange("new_exam", new_p, None))
            else:
                changes.append(TimetableChange("modified", new_p, None))

    # Detect removed periods (not in new, but was in old and not cancelled already)
    for key, old_p in old_by_key.items():
        if key not in new_by_key and old_p.code != "cancelled":
            changes.append(TimetableChange("cancelled", old_p, None))

    return changes


def format_change_notification(change: TimetableChange, locale: str = "de") -> str:
    """Format a single timetable change into a human-readable notification."""
    p = change.period
    date_str = _format_date(p.date)
    subj = p.subject or "?"
    start = p.start_time

    period_num = f"{p.lesson_number}. Std" if p.lesson_number else start

    if change.change_type == "cancelled":
        return f"❌ {period_num} {subj} ist ENTFÄLLT am {date_str}"
    if change.change_type == "restored":
        return f"✅ {period_num} {subj} findet wieder statt am {date_str}"
    if change.change_type == "new_exam":
        return f"📝 Neue Prüfung: {period_num} {subj} am {date_str}"
    if change.change_type == "irregular":
        return f"⚠️ {period_num} {subj} Vertretung am {date_str}"
    if change.change_type == "modified":
        old = change.old_period
        if old:
            return (
                f"🔄 {period_num} {subj} geändert am {date_str}"
                f" (vorher: {old.teacher or '?'}/{old.room or '?'}"
                f" → jetzt: {p.teacher or '?'}/{p.room or '?'})"
            )
        return f"🆕 {period_num} {subj} hinzugefügt am {date_str}"
    return f"ℹ️ {period_num} {subj} am {date_str}: {change.change_type}"


def _format_date(date_str: str) -> str:
    """Convert YYYY-MM-DD to DD.MM."""
    try:
        d = dt.date.fromisoformat(date_str)
        return d.strftime("%d.%m")
    except ValueError:
        return date_str


def _weekday_name(date_str: str) -> str:
    """Return German weekday name for YYYY-MM-DD string."""
    names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    try:
        d = dt.date.fromisoformat(date_str)
        return names[d.weekday()]
    except ValueError:
        return ""


class UntisService:
    """
    Per-user Untis timetable service.

    Stores credentials and previous timetable state on disk.
    Fetches the current timetable, compares with the stored state, and
    returns the list of changes.  Google Calendar sync for Miron and Michi
    is triggered externally via the calendar_client passed in.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._users_file = config.untis_users_file
        self._state_file = config.untis_timetable_state_file
        self._server = config.untis_server
        self._school = config.untis_school

    # ------------------------------------------------------------------
    # Credential management
    # ------------------------------------------------------------------

    def load_all_users(self) -> dict[str, dict]:
        """Return {str(user_id): {username, password}} mapping."""
        return read_json(self._users_file, {})

    def save_credentials(self, user_id: int, creds: UntisCredentials) -> None:
        users = self.load_all_users()
        users[str(user_id)] = {
            "username": creds.username,
            "password": creds.password,
            "server": creds.server,
            "school": creds.school,
        }
        write_json(self._users_file, users)

    def delete_credentials(self, user_id: int) -> bool:
        users = self.load_all_users()
        if str(user_id) not in users:
            return False
        del users[str(user_id)]
        write_json(self._users_file, users)
        return True

    def get_credentials(self, user_id: int) -> UntisCredentials | None:
        users = self.load_all_users()
        raw = users.get(str(user_id))
        if not raw:
            return None
        return UntisCredentials(
            server=raw.get("server") or self._server,
            school=raw.get("school") or self._school,
            username=raw["username"],
            password=raw["password"],
        )

    def has_credentials(self, user_id: int) -> bool:
        return self.get_credentials(user_id) is not None

    # ------------------------------------------------------------------
    # Timetable state persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, list[dict]]:
        return read_json(self._state_file, {})

    def _save_state(self, state: dict[str, list[dict]]) -> None:
        write_json(self._state_file, state)

    def load_user_timetable(self, user_id: int) -> list[UntisPeriod]:
        state = self._load_state()
        raw = state.get(str(user_id), [])
        periods = []
        for item in raw:
            try:
                periods.append(UntisPeriod.from_dict(item))
            except Exception:
                pass
        return periods

    def save_user_timetable(self, user_id: int, periods: list[UntisPeriod]) -> None:
        state = self._load_state()
        state[str(user_id)] = [p.to_dict() for p in periods]
        self._save_state(state)

    # ------------------------------------------------------------------
    # Fetching & change detection
    # ------------------------------------------------------------------

    def _make_client(self, creds: UntisCredentials) -> UntisClient:
        return UntisClient(
            server=creds.server,
            school=creds.school,
            username=creds.username,
            password=creds.password,
        )

    def check_user_for_changes(
        self,
        user_id: int,
    ) -> list[TimetableChange]:
        """
        Fetch current timetable for *user_id*, compare with stored state,
        persist the new state and return the detected changes.

        Returns an empty list if the user has no credentials or the fetch fails.
        """
        creds = self.get_credentials(user_id)
        if not creds:
            return []

        today = dt.date.today()
        end = today + dt.timedelta(days=_LOOKAHEAD_DAYS)

        client = self._make_client(creds)
        try:
            new_periods = client.fetch_timetable(today, end)
        except Exception as exc:
            logger.error("Untis fetch failed for user %s: %s", user_id, exc)
            return []

        old_periods = self.load_user_timetable(user_id)
        changes = detect_changes(old_periods, new_periods)
        self.save_user_timetable(user_id, new_periods)
        return changes

    def check_all_users_for_changes(self) -> dict[int, list[TimetableChange]]:
        """Run change detection for every registered user."""
        result: dict[int, list[TimetableChange]] = {}
        for uid_str in self.load_all_users():
            uid = int(uid_str)
            changes = self.check_user_for_changes(uid)
            if changes:
                result[uid] = changes
        return result

    # ------------------------------------------------------------------
    # Daily digest
    # ------------------------------------------------------------------

    def daily_digest_for_user(self, user_id: int) -> str:
        """Return a short digest of today's timetable for a user."""
        periods = self.load_user_timetable(user_id)
        today_str = dt.date.today().isoformat()
        today_periods = [p for p in periods if p.date == today_str]
        today_periods.sort(key=lambda p: p.start_time)

        if not today_periods:
            return "📅 Heute keine Stunden laut Stundenplan."

        lines = ["📅 *Stundenplan heute:*"]
        for p in today_periods:
            status = ""
            if p.code == "cancelled":
                status = " ❌ ENTFÄLLT"
            elif p.code == "irregular":
                status = " ⚠️ Vertretung"
            ln = p.lesson_number
            prefix = f"{ln}." if ln else p.start_time
            lines.append(f"  {prefix} {p.subject or '?'} ({p.start_time}-{p.end_time}){status}")

        cancelled = [p for p in today_periods if p.code == "cancelled"]
        if cancelled:
            lines.append(f"\n⚠️ {len(cancelled)} Stunde(n) entfallen heute!")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Google Calendar sync helpers
    # ------------------------------------------------------------------

    def build_miron_calendar_events(
        self,
        periods: list[UntisPeriod],
        date_str: str,
    ) -> list[dict]:
        """
        For Miron: merge consecutive periods (with ≤30-minute gap) into single events.
        Returns a list of dicts with 'start', 'end', 'summary', 'description'.
        """
        day_periods = sorted(
            [p for p in periods if p.date == date_str and p.code != "cancelled"],
            key=lambda p: p.start_time,
        )
        if not day_periods:
            return []

        # Merge consecutive / small-gap blocks
        events = []
        block = [day_periods[0]]
        for p in day_periods[1:]:
            prev = block[-1]
            # Treat as continuous if gap is 0 or at most 2 slots (≈30 min)
            gap_minutes = _time_gap_minutes(prev.end_time, p.start_time)
            if gap_minutes <= 30:
                block.append(p)
            else:
                events.append(_make_school_event(block, date_str))
                block = [p]
        events.append(_make_school_event(block, date_str))
        return events

    def build_michi_calendar_events(
        self,
        periods: list[UntisPeriod],
        date_str: str,
    ) -> list[dict]:
        """
        For Michi: each period is a separate calendar event.
        Returns list of dicts with 'start', 'end', 'summary', 'description'.
        """
        day_periods = sorted(
            [p for p in periods if p.date == date_str and p.code != "cancelled"],
            key=lambda p: p.start_time,
        )
        return [
            {
                "summary": p.subject or "Schule",
                "description": f"Lehrer: {p.teacher}\nRaum: {p.room}",
                "start": f"{date_str}T{p.start_time}:00",
                "end": f"{date_str}T{p.end_time}:00",
            }
            for p in day_periods
        ]


def _time_gap_minutes(end_time: str, start_time: str) -> int:
    """Return gap in minutes between two HH:MM strings."""
    try:
        e = dt.datetime.strptime(end_time, "%H:%M")
        s = dt.datetime.strptime(start_time, "%H:%M")
        delta = (s - e).total_seconds() / 60
        return int(delta)
    except ValueError:
        return 999


def _make_school_event(block: list[UntisPeriod], date_str: str) -> dict:
    subjects = ", ".join(p.subject for p in block if p.subject)
    start = block[0].start_time
    end = block[-1].end_time
    return {
        "summary": subjects or "Schule",
        "description": "\n".join(
            f"{p.start_time}-{p.end_time} {p.subject} ({p.teacher}, {p.room})" for p in block
        ),
        "start": f"{date_str}T{start}:00",
        "end": f"{date_str}T{end}:00",
    }
