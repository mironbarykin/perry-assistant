from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from perry_assistant.config import AppConfig
from perry_assistant.constants import BERLIN_TZ
from perry_assistant.domain.models import TimetableChange, UntisCredentials, UntisPeriod
from perry_assistant.integrations.calendar_client import parse_google_datetime
from perry_assistant.integrations.untis_calendar_client import UntisCalendarClient, build_event_payload
from perry_assistant.integrations.untis_client import UntisClient
from perry_assistant.storage.json_store import read_json, write_json


logger = logging.getLogger(__name__)

# How many days ahead to check for changes
_LOOKAHEAD_DAYS = 10
_SCHOOL_GAP_MINUTES = 60
_SCHOOL_SUMMARY = "🏫 School"


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
        and a.subst_text == b.subst_text
        and a.ls_text == b.ls_text
        and a.info == b.info
    )


def _is_exam_period(period: UntisPeriod) -> bool:
    text = (period.subject or "").lower()
    return any(
        token in text
        for token in (
            "klausur",
            "exam",
            "prüfung",
            "pruefung",
            "test",
            "schulaufgabe",
            "arbeit",
            "sa",
        )
    )


def _periods_by_date(periods: list[UntisPeriod]) -> dict[str, list[UntisPeriod]]:
    """Group periods by date."""
    result: dict[str, list[UntisPeriod]] = {}
    for p in periods:
        if p.date not in result:
            result[p.date] = []
        result[p.date].append(p)
    return result


def _are_consecutive_lessons(p1: UntisPeriod, p2: UntisPeriod) -> bool:
    """Check if p2 immediately follows p1 (back-to-back)."""
    return p1.end_time == p2.start_time


def _are_same_lesson_type(p1: UntisPeriod, p2: UntisPeriod) -> bool:
    """Check if two periods are the same lesson (subject, teacher, room)."""
    return (
        p1.subject == p2.subject
        and p1.teacher == p2.teacher
        and p1.room == p2.room
        and p1.code == p2.code
    )


def _merge_doubled_lessons(periods: list[UntisPeriod]) -> list[UntisPeriod]:
    """
    Detect and merge back-to-back doubled lessons (same subject, teacher, room).
    Returns modified list where doubled lessons are merged into one period.
    """
    if len(periods) < 2:
        return periods

    result: list[UntisPeriod] = []
    i = 0
    while i < len(periods):
        current = periods[i]
        
        # Check if next period is a consecutive identical lesson
        if i + 1 < len(periods):
            next_period = periods[i + 1]
            if _are_consecutive_lessons(current, next_period) and _are_same_lesson_type(current, next_period):
                # Merge: keep current but extend end_time to include next
                merged = UntisPeriod(
                    id=current.id,
                    date=current.date,
                    start_time=current.start_time,
                    end_time=next_period.end_time,
                    subject=current.subject,
                    teacher=current.teacher,
                    room=current.room,
                    code=current.code,
                    lesson_number=None,  # Can't reliably merge lesson numbers
                    subst_text=current.subst_text or next_period.subst_text,
                    ls_text=current.ls_text or next_period.ls_text,
                    info=current.info or next_period.info,
                )
                # Mark as doubled so we can display "x2" later
                merged._doubled = True  # type: ignore
                result.append(merged)
                i += 2
                continue
        
        result.append(current)
        i += 1

    return result


def _is_full_day_change(
    old_periods: list[UntisPeriod],
    new_periods: list[UntisPeriod],
    date: str,
) -> bool:
    """
    Check if a full day changed from completely empty to completely empty.
    This happens during holidays: entire day added or cancelled should be ignored.
    """
    old_day = [p for p in old_periods if p.date == date and p.code != "cancelled"]
    new_day = [p for p in new_periods if p.date == date and p.code != "cancelled"]
    
    # If both are empty, it's a full-day change (holiday)
    # If one was empty and now has content (or vice versa), skip notification
    old_empty = len(old_day) == 0
    new_empty = len(new_day) == 0
    
    return old_empty and new_empty


def detect_changes(
    old_periods: list[UntisPeriod],
    new_periods: list[UntisPeriod],
) -> list[TimetableChange]:
    """Compare two timetable snapshots and return a list of detected changes."""
    # Pre-process: merge doubled lessons
    old_periods = _merge_doubled_lessons(old_periods)
    new_periods = _merge_doubled_lessons(new_periods)
    
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
                elif _is_exam_period(new_p) and not _is_exam_period(old_p):
                    changes.append(TimetableChange("new_exam", new_p, old_p))
                else:
                    changes.append(TimetableChange("modified", new_p, old_p))
        else:
            # New period appeared - skip if it's a full-day holiday change
            if _is_full_day_change(old_periods, new_periods, new_p.date):
                continue
            
            if _is_exam_period(new_p):
                changes.append(TimetableChange("new_exam", new_p, None))
            else:
                changes.append(TimetableChange("modified", new_p, None))

    # Detect removed periods (not in new, but was in old and not cancelled already)
    for key, old_p in old_by_key.items():
        if key not in new_by_key and old_p.code != "cancelled":
            # Skip if it's a full-day holiday change
            if _is_full_day_change(old_periods, new_periods, old_p.date):
                continue
            changes.append(TimetableChange("cancelled", old_p, None))

    return changes


def format_change_notification(change: TimetableChange, locale: str = "de") -> str:
    """Format a single timetable change into a human-readable notification."""
    p = change.period
    date_str = _format_date(p.date)
    subj = p.subject or "?"
    start = p.start_time

    period_num = f"{p.lesson_number}. Std" if p.lesson_number else start
    
    # Check if this is a doubled lesson (merged from two consecutive lessons)
    is_doubled = getattr(p, "_doubled", False)
    subject_display = f"{subj} x2" if is_doubled else subj

    extra = _format_extra_fields(p)

    if change.change_type == "cancelled":
        return f"❌ {period_num} {subject_display} ENTFÄLLT am {date_str}{extra}"
    if change.change_type == "restored":
        return f"✅ {period_num} {subject_display} findet wieder statt am {date_str}{extra}"
    if change.change_type == "new_exam":
        return f"📝 Neue Prüfung: {period_num} {subject_display} am {date_str}{extra}"
    if change.change_type == "irregular":
        return f"⚠️ {period_num} {subject_display} Vertretung am {date_str}{extra}"
    if change.change_type == "modified":
        old = change.old_period
        if old:
            # Only show "vorher/jetzt" if teacher or room actually changed
            teacher_changed = (p.teacher or "?") != (old.teacher or "?")
            room_changed = (p.room or "?") != (old.room or "?")
            
            if teacher_changed or room_changed:
                return (
                    f"🔄 {period_num} {subject_display} geändert am {date_str}"
                    f" (vorher: {old.teacher or '?'}/{old.room or '?'}"
                    f" → jetzt: {p.teacher or '?'}/{p.room or '?'}){extra}"
                )
            else:
                # No actual change in teacher/room, just note it was modified
                return f"🔄 {period_num} {subject_display} geändert am {date_str}{extra}"
        return f"🆕 {period_num} {subject_display} hinzugefügt am {date_str}{extra}"
    return f"ℹ️ {period_num} {subject_display} am {date_str}: {change.change_type}{extra}"


def _format_extra_fields(p: UntisPeriod) -> str:
    """Return a formatted string with extra period fields (subst_text, ls_text, info)."""
    parts: list[str] = []
    if p.subst_text:
        parts.append(f"Vertretungstext: {p.subst_text}")
    if p.ls_text and "block" not in p.ls_text.lower():
        parts.append(f"Stundentext: {p.ls_text}")
    if p.info:
        parts.append(f"Info: {p.info}")
    if not parts:
        return ""
    return "\n  " + "\n  ".join(parts)


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
    returns the list of changes. Google Calendar sync for Miron and Michi
    uses a service account and runs as part of the refresh flow.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._users_file = config.untis_users_file
        self._state_file = config.untis_timetable_state_file
        self._changes_file = config.untis_changes_file
        self._server = config.untis_server
        self._school = config.untis_school
        self._service_account_file = config.data_dir / "yoursbennybot-986b4f0e0d1b.json"
        self._calendar_client: UntisCalendarClient | None = None

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

    def _load_changes_state(self) -> dict[str, list[dict]]:
        return read_json(self._changes_file, {})

    def _save_changes_state(self, state: dict[str, list[dict]]) -> None:
        write_json(self._changes_file, state)

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

    def _make_calendar_client(self) -> UntisCalendarClient:
        if self._calendar_client is None:
            self._calendar_client = UntisCalendarClient(self._service_account_file)
        return self._calendar_client

    def check_user_for_changes(
        self,
        user_id: int,
    ) -> list[TimetableChange]:
        """
        Fetch current timetable for *user_id*, compare with stored state,
        persist the new state and return the detected changes.

        Returns an empty list if the user has no credentials or the fetch fails.
        """
        try:
            return self.refresh_user_timetable(user_id)
        except Exception as exc:
            logger.error("Untis fetch failed for user %s: %s", user_id, exc)
            return []

    def check_all_users_for_changes(self) -> dict[int, list[TimetableChange]]:
        """Run change detection for every registered user."""
        result: dict[int, list[TimetableChange]] = {}
        for uid_str in self.load_all_users():
            uid = int(uid_str)
            changes = self.check_user_for_changes(uid)
            if changes:
                result[uid] = changes
        return result

    def refresh_user_timetable(self, user_id: int) -> list[TimetableChange]:
        """
        Fetch and persist the latest timetable for a user.

        If this is the first successful sync (no stored state yet), the
        timetable is saved as baseline and no changes are returned.
        If the old timetable is empty, return no changes and replace 
        the old timetable with the new one.
        """
        creds = self.get_credentials(user_id)
        if not creds:
            return []

        today = dt.date.today()
        end = today + dt.timedelta(days=_LOOKAHEAD_DAYS)

        client = self._make_client(creds)
        new_periods = client.fetch_timetable(today, end)
        self._sync_calendar_if_needed(user_id, new_periods, today, end)

        state = self._load_state()
        if str(user_id) not in state:
            self.save_user_timetable(user_id, new_periods)
            return []

        today_str = today.isoformat()
        old_periods = [p for p in self.load_user_timetable(user_id) if p.date >= today_str]
        
        if len(old_periods) == 0:
            self.save_user_timetable(user_id, new_periods)
            return []

        changes = detect_changes(old_periods, new_periods)
        if changes:
            self._store_detected_changes(user_id, changes, today, end)
        self.save_user_timetable(user_id, new_periods)
        return changes

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
                color = "🔴"
            elif p.code == "irregular":
                status = " ⚠️ Vertretung"
                color = "🟡"
            else:
                color = "🟢"
            ln = p.lesson_number
            prefix = f"{ln}." if ln else p.start_time
            line = f"  {color} {prefix} {p.subject or '?'} ({p.start_time}-{p.end_time}){status}"
            if p.subst_text:
                line += f"\n    ↳ {p.subst_text}"
            if p.ls_text and "block" not in p.ls_text.lower():
                line += f"\n    ↳ {p.ls_text}"
            if p.info:
                line += f"\n    ℹ️ {p.info}"
            lines.append(line)

        cancelled = [p for p in today_periods if p.code == "cancelled"]
        if cancelled:
            lines.append(f"\n⚠️ {len(cancelled)} Stunde(n) entfallen heute!")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Change reminders (stored changes)
    # ------------------------------------------------------------------

    def _store_detected_changes(
        self,
        user_id: int,
        changes: list[TimetableChange],
        start: dt.date,
        end: dt.date,
    ) -> None:
        state = self._load_changes_state()
        records = state.get(str(user_id), [])
        existing: dict[str, dict] = {self._change_key(item): item for item in records}
        for change in changes:
            payload = self._change_to_dict(change)
            existing[self._change_key(payload)] = payload
        filtered = self._filter_change_records(list(existing.values()), start, end)
        state[str(user_id)] = filtered
        self._save_changes_state(state)

    def get_upcoming_changes(
        self,
        user_id: int,
        start: dt.date,
        end: dt.date,
    ) -> list[TimetableChange]:
        state = self._load_changes_state()
        records = state.get(str(user_id), [])
        filtered = self._filter_change_records(records, start, end)
        if filtered != records:
            state[str(user_id)] = filtered
            self._save_changes_state(state)
        return [self._change_from_dict(item) for item in filtered]

    def get_changes_for_date(self, user_id: int, target: dt.date) -> list[TimetableChange]:
        return self.get_upcoming_changes(user_id, target, target)

    def _filter_change_records(
        self,
        records: list[dict],
        start: dt.date,
        end: dt.date,
    ) -> list[dict]:
        start_str = start.isoformat()
        end_str = end.isoformat()
        filtered: list[dict] = []
        for item in records:
            period = item.get("period", {})
            date_str = period.get("date")
            if not date_str:
                continue
            if start_str <= date_str <= end_str:
                filtered.append(item)
        return filtered

    def _change_to_dict(self, change: TimetableChange) -> dict:
        return {
            "change_type": change.change_type,
            "period": change.period.to_dict(),
            "old_period": change.old_period.to_dict() if change.old_period else None,
            "detected_at": dt.datetime.now(dt.UTC).isoformat(),
        }

    def _change_from_dict(self, data: dict) -> TimetableChange:
        period = UntisPeriod.from_dict(data["period"])
        old_raw = data.get("old_period")
        old_period = UntisPeriod.from_dict(old_raw) if old_raw else None
        return TimetableChange(data["change_type"], period, old_period)

    def _change_key(self, data: dict) -> str:
        change_type = data.get("change_type", "")
        period = data.get("period", {})
        return f"{change_type}:{period.get('id')}:{period.get('date')}:{period.get('start_time')}"

    # ------------------------------------------------------------------
    # Google Calendar sync helpers
    # ------------------------------------------------------------------

    def build_miron_calendar_events(
        self,
        periods: list[UntisPeriod],
        date_str: str,
    ) -> list[dict]:
        '''
        For Miron: merge consecutive periods (with <=60-minute gap) into single events.
        Returns a list of dicts with 'start', 'end', 'summary', 'description'.
        '''
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
            # Treat as continuous if gap is at most 60 minutes
            gap_minutes = _time_gap_minutes(prev.end_time, p.start_time)
            if gap_minutes <= _SCHOOL_GAP_MINUTES:
                block.append(p)
            else:
                events.append(_make_school_event(block, date_str, summary=_SCHOOL_SUMMARY))
                block = [p]
        events.append(_make_school_event(block, date_str, summary=_SCHOOL_SUMMARY))
        return events

    def build_michi_calendar_events(
        self,
        periods: list[UntisPeriod],
        date_str: str,
    ) -> list[dict]:
        '''
        For Michi: merge consecutive same-subject periods (double periods).
        Returns list of dicts with 'start', 'end', 'summary', 'description'.
        '''
        day_periods = sorted(
            [p for p in periods if p.date == date_str and p.code != "cancelled"],
            key=lambda p: p.start_time,
        )
        if not day_periods:
            return []

        events: list[dict] = []
        block = [day_periods[0]]
        for p in day_periods[1:]:
            prev = block[-1]
            gap_minutes = _time_gap_minutes(prev.end_time, p.start_time)
            if p.subject == prev.subject and gap_minutes <= _SCHOOL_GAP_MINUTES:
                block.append(p)
            else:
                events.append(_make_school_event(block, date_str, summary=_michi_subject(block)))
                block = [p]
        events.append(_make_school_event(block, date_str, summary=_michi_subject(block)))
        return events

    # ------------------------------------------------------------------
    # Google Calendar sync (Untis service account)
    # ------------------------------------------------------------------

    def _sync_calendar_if_needed(
        self,
        user_id: int,
        periods: list[UntisPeriod],
        start: dt.date,
        end: dt.date,
    ) -> None:
        if user_id == self._config.miron_id:
            calendar_id = self._config.miron_school_calendar_id
            mode = "miron"
        elif user_id == self._config.michi_id:
            calendar_id = self._config.michi_school_calendar_id
            mode = "michi"
        else:
            return

        if not calendar_id:
            logger.debug("Untis calendar sync skipped: missing calendar ID for %s", mode)
            return
        if not self._service_account_file.exists():
            logger.warning("Untis calendar sync skipped: service account file missing.")
            return

        try:
            client = self._make_calendar_client()
            start_dt = dt.datetime.combine(start, dt.time(0, 0, tzinfo=BERLIN_TZ))
            end_dt = dt.datetime.combine(end, dt.time(23, 59, 59, tzinfo=BERLIN_TZ))
            existing = client.list_events(calendar_id, start_dt, end_dt)

            if mode == "miron":
                target = self._build_miron_event_specs(periods, start, end)
                self._reconcile_miron_calendar(client, calendar_id, target, existing)
            else:
                target = self._build_michi_event_specs(periods, start, end)
                self._reconcile_michi_calendar(client, calendar_id, target, existing, periods)
        except Exception as exc:
            logger.warning("Untis calendar sync failed for %s: %s", mode, exc)

    def _build_miron_event_specs(
        self,
        periods: list[UntisPeriod],
        start: dt.date,
        end: dt.date,
    ) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for day in _date_range(start, end):
            for event in self.build_miron_calendar_events(periods, day.isoformat()):
                specs.append(_event_spec_from_payload(event))
        return specs

    def _build_michi_event_specs(
        self,
        periods: list[UntisPeriod],
        start: dt.date,
        end: dt.date,
    ) -> list[dict[str, Any]]:
        specs: list[dict[str, Any]] = []
        for day in _date_range(start, end):
            for event in self.build_michi_calendar_events(periods, day.isoformat()):
                specs.append(_event_spec_from_payload(event))
        return specs

    def _reconcile_miron_calendar(
        self,
        client: UntisCalendarClient,
        calendar_id: str,
        target: list[dict[str, Any]],
        existing: list[dict[str, Any]],
    ) -> None:
        existing_map = _build_existing_event_map(existing, summary_filter=_SCHOOL_SUMMARY)
        target_map = {item["key"]: item for item in target}

        for key, item in target_map.items():
            if key in existing_map:
                existing_event = existing_map[key]
                if existing_event.get("description", "") != item.get("description", ""):
                    client.update_event(calendar_id, existing_event["id"], {"description": item["description"]})
            else:
                payload = build_event_payload(item["summary"], item["description"], item["start_dt"], item["end_dt"])
                client.create_event(calendar_id, payload)

        for key, existing_event in existing_map.items():
            if key not in target_map:
                client.delete_event(calendar_id, existing_event["id"])

    def _reconcile_michi_calendar(
        self,
        client: UntisCalendarClient,
        calendar_id: str,
        target: list[dict[str, Any]],
        existing: list[dict[str, Any]],
        periods: list[UntisPeriod],
    ) -> None:
        existing_map = _build_existing_event_map(existing)
        target_map = {item["key"]: item for item in target}
        target_subjects = _subjects_by_date(periods)
        windows = _school_windows_by_date(periods)

        for key, item in target_map.items():
            if key in existing_map:
                existing_event = existing_map[key]
                if existing_event.get("description", "") != item.get("description", ""):
                    client.update_event(calendar_id, existing_event["id"], {"description": item["description"]})
            else:
                payload = build_event_payload(item["summary"], item["description"], item["start_dt"], item["end_dt"])
                client.create_event(calendar_id, payload)

        for key, existing_event in existing_map.items():
            if key in target_map:
                continue
            summary = existing_event.get("summary", "")
            start_dt = existing_event.get("start_dt")
            end_dt = existing_event.get("end_dt")
            if not summary or not start_dt or not end_dt:
                continue
            date_str = start_dt.astimezone(BERLIN_TZ).date().isoformat()
            window = windows.get(date_str)
            if not window:
                continue
            if summary not in target_subjects.get(date_str, set()):
                continue
            if start_dt < window[0] or end_dt > window[1]:
                continue
            client.delete_event(calendar_id, existing_event["id"])


def _event_spec_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    start_dt = dt.datetime.fromisoformat(payload["start"]).replace(tzinfo=BERLIN_TZ)
    end_dt = dt.datetime.fromisoformat(payload["end"]).replace(tzinfo=BERLIN_TZ)
    summary = payload.get("summary", "")
    description = payload.get("description", "")
    return {
        "summary": summary,
        "description": description,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "key": _event_key(summary, start_dt, end_dt),
    }


def _build_existing_event_map(
    existing: list[dict[str, Any]],
    summary_filter: str | None = None,
) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for event in existing:
        summary = str(event.get("summary", "") or "")
        if summary_filter and summary != summary_filter:
            continue
        start_raw = event.get("start", {}).get("dateTime")
        end_raw = event.get("end", {}).get("dateTime")
        if not start_raw or not end_raw:
            continue
        start_dt = parse_google_datetime(start_raw)
        end_dt = parse_google_datetime(end_raw)
        if not start_dt or not end_dt:
            continue
        start_dt = start_dt.astimezone(BERLIN_TZ)
        end_dt = end_dt.astimezone(BERLIN_TZ)
        key = _event_key(summary, start_dt, end_dt)
        mapped[key] = {
            "id": event.get("id"),
            "summary": summary,
            "description": event.get("description", ""),
            "start_dt": start_dt,
            "end_dt": end_dt,
        }
    return mapped


def _event_key(summary: str, start_dt: dt.datetime, end_dt: dt.datetime) -> str:
    return f"{summary}:{start_dt.isoformat()}:{end_dt.isoformat()}"


def _subjects_by_date(periods: list[UntisPeriod]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for p in periods:
        if p.code == "cancelled":
            continue
        result.setdefault(p.date, set()).add(p.subject or "Schule")
    return result


def _school_windows_by_date(periods: list[UntisPeriod]) -> dict[str, tuple[dt.datetime, dt.datetime]]:
    windows: dict[str, tuple[dt.datetime, dt.datetime]] = {}
    grouped: dict[str, list[UntisPeriod]] = {}
    for p in periods:
        if p.code == "cancelled":
            continue
        grouped.setdefault(p.date, []).append(p)
    for date_str, items in grouped.items():
        items.sort(key=lambda p: p.start_time)
        start = dt.datetime.fromisoformat(f"{date_str}T{items[0].start_time}:00").replace(tzinfo=BERLIN_TZ)
        end = dt.datetime.fromisoformat(f"{date_str}T{items[-1].end_time}:00").replace(tzinfo=BERLIN_TZ)
        windows[date_str] = (start, end)
    return windows


def _date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    days = (end - start).days
    return [start + dt.timedelta(days=offset) for offset in range(days + 1)]


def _michi_subject(block: list[UntisPeriod]) -> str:
    if not block:
        return "Schule"
    return block[0].subject or "Schule"


def _time_gap_minutes(end_time: str, start_time: str) -> int:
    """Return gap in minutes between two HH:MM strings."""
    try:
        e = dt.datetime.strptime(end_time, "%H:%M")
        s = dt.datetime.strptime(start_time, "%H:%M")
        delta = (s - e).total_seconds() / 60
        return int(delta)
    except ValueError:
        return 999


def _make_school_event(block: list[UntisPeriod], date_str: str, summary: str | None = None) -> dict:
    subjects = ", ".join(p.subject for p in block if p.subject)
    start = block[0].start_time
    end = block[-1].end_time
    return {
        "summary": summary or subjects or "Schule",
        "description": "\n".join(
            f"{p.start_time}-{p.end_time} {p.subject} ({p.teacher}, {p.room})" for p in block
        ),
        "start": f"{date_str}T{start}:00",
        "end": f"{date_str}T{end}:00",
    }
