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
_DOUBLE_LESSON_GAP_MINUTES = 10
_KURZSTUNDEN_MINUTES = 30
_SCHOOL_SUMMARY = "🏫 School"
_IGNORED_SUBJECTS = {"R", 'Nach', 'mdl'}
_KURZSTUNDEN_BEGINN = ['07:55', '08:30', '09:15', '09:50', '10:35', '11:10', '11:50', '12:25']
_NORMALSTUNDEN_BEGINN = ['07:55', '08:45', '09:45', '10:35', '11:35', '12:25', '13:20', '14:05']

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
        and a.lesson_count == b.lesson_count
        and a.period_type == b.period_type
    )


def _is_exam_period(period: UntisPeriod) -> bool:
    """Detect if a period is an exam based on webuntis period type."""
    # The webuntis API period.type returns "ex" for examinations
    if period.period_type == "ex":
        return True
    text = " ".join(
        part for part in (period.subject, period.subst_text, period.ls_text, period.info) if part
    ).lower()
    return any(marker in text for marker in ("klausur", "prüfung", "pruefung", "exam"))


def _is_ignored_subject(period: UntisPeriod) -> bool:
    """Check if period subject is in the ignored subjects list."""
    if not period.subject:
        return False
    subject_code = period.subject.split()[0]
    return subject_code in _IGNORED_SUBJECTS


def _periods_by_date(periods: list[UntisPeriod]) -> dict[str, list[UntisPeriod]]:
    """Group periods by date."""
    result: dict[str, list[UntisPeriod]] = {}
    for period in periods:
        result.setdefault(period.date, []).append(period)
    return result


def _lesson_signature(period: UntisPeriod) -> tuple[str, str, str, str | None]:
    return (period.subject, period.teacher, period.room, period.code)


def _merge_doubled_lessons(periods: list[UntisPeriod]) -> list[UntisPeriod]:
    """
    Merge repeated lesson runs into a single period with lesson_count > 1.

    Lessons are grouped by date and signature, then merged by start/end time so
    the order in the raw Untis payload does not matter.
    """
    merged_periods: list[UntisPeriod] = []
    for _, day_periods in sorted(_periods_by_date(periods).items()):
        groups: dict[tuple[str, str, str, str | None], list[UntisPeriod]] = {}
        for period in sorted(day_periods, key=lambda p: (p.start_time, p.end_time, p.subject, p.teacher, p.room, p.id)):
            groups.setdefault(_lesson_signature(period), []).append(period)

        for group_periods in groups.values():
            group_periods.sort(key=lambda p: (p.start_time, p.end_time, p.id))
            run: list[UntisPeriod] = [group_periods[0]]
            for period in group_periods[1:]:
                previous = run[-1]
                gap_minutes = _time_gap_minutes(previous.end_time, period.start_time)
                if 0 <= gap_minutes <= _DOUBLE_LESSON_GAP_MINUTES:
                    run.append(period)
                    continue
                merged_periods.append(_merge_period_run(run))
                run = [period]
            merged_periods.append(_merge_period_run(run))

    merged_periods.sort(key=lambda p: (p.date, p.start_time, p.end_time, p.subject, p.teacher, p.room, p.id))
    return merged_periods


def _merge_period_run(periods: list[UntisPeriod]) -> UntisPeriod:
    first = periods[0]
    if len(periods) == 1:
        return first
    return UntisPeriod(
        id=first.id,
        date=first.date,
        start_time=first.start_time,
        end_time=periods[-1].end_time,
        subject=first.subject,
        teacher=first.teacher,
        room=first.room,
        code=first.code,
        lesson_number=first.lesson_number,
        subst_text=_merge_text_values(period.subst_text for period in periods),
        ls_text=_merge_text_values(period.ls_text for period in periods),
        info=_merge_text_values(period.info for period in periods),
        lesson_count=len(periods),
    )


def _merge_text_values(values) -> str | None:
    parts: list[str] = []
    for value in values:
        if not value:
            continue
        if value not in parts:
            parts.append(value)
    if not parts:
        return None
    return "\n".join(parts)


def _is_full_day_change(
    old_periods: list[UntisPeriod],
    new_periods: list[UntisPeriod],
    date: str,
) -> bool:
    """Skip only obvious whole-day transitions with no overlap."""
    old_day = [p for p in old_periods if p.date == date and p.code != "cancelled"]
    new_day = [p for p in new_periods if p.date == date and p.code != "cancelled"]
    if old_day and new_day:
        return False
    return max(len(old_day), len(new_day)) >= 3


def detect_changes(
    old_periods: list[UntisPeriod],
    new_periods: list[UntisPeriod],
) -> list[TimetableChange]:
    """Compare two timetable snapshots and return a list of detected changes."""
    old_periods = _merge_doubled_lessons(old_periods)
    new_periods = _merge_doubled_lessons(new_periods)

    changes: list[TimetableChange] = []
    old_by_date = _periods_by_date(old_periods)
    new_by_date = _periods_by_date(new_periods)

    for date in sorted(set(old_by_date) | set(new_by_date)):
        old_day = [p for p in old_by_date.get(date, []) if p.code != "cancelled"]
        new_day = [p for p in new_by_date.get(date, []) if p.code != "cancelled"]

        if _is_full_day_change(old_day, new_day, date):
            continue

        old_by_key: dict[str, UntisPeriod] = {
            _period_key(p): p for p in old_periods if p.date == date
        }
        new_by_key: dict[str, UntisPeriod] = {
            _period_key(p): p for p in new_periods if p.date == date
        }

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
                if _is_exam_period(new_p):
                    changes.append(TimetableChange("new_exam", new_p, None))
                else:
                    changes.append(TimetableChange("modified", new_p, None))

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
    subject_display = f"{subj} x{p.lesson_count}" if p.lesson_count > 1 else subj

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
            old_label = _format_teacher_room(old)
            new_label = _format_teacher_room(p)
            if old_label != new_label:
                return (
                    f"🔄 {period_num} {subject_display} geändert am {date_str}"
                    f" ({old_label} → {new_label}){extra}"
                )
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


def _format_teacher_room(period: UntisPeriod) -> str:
    teacher = period.teacher or "?"
    room = period.room or "?"
    if teacher == "?" and room == "?":
        return "?"
    if teacher == "?":
        return room
    if room == "?":
        return teacher
    return f"{teacher}/{room}"


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
        self._kurzstunden_file = config.untis_kurzstunden_file
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

    def _load_kurzstunden_dates(self) -> set[str]:
        raw = read_json(self._kurzstunden_file, [])
        if isinstance(raw, dict):
            raw = raw.get("dates", [])
        if not isinstance(raw, list):
            return set()
        return {str(item) for item in raw if item}

    def _save_kurzstunden_dates(self, dates: set[str]) -> None:
        write_json(self._kurzstunden_file, sorted(dates))

    def is_kurzstunden(self, target: dt.date) -> bool:
        return target.isoformat() in self._load_kurzstunden_dates()

    def toggle_kurzstunden(self, target: dt.date) -> bool:
        dates = self._load_kurzstunden_dates()
        key = target.isoformat()
        enabled = key not in dates
        if enabled:
            dates.add(key)
        else:
            dates.remove(key)
        self._save_kurzstunden_dates(dates)
        return enabled
    
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

    def sync_calendar_for_date(self, user_id: int, target: dt.date) -> bool:
        creds = self.get_credentials(user_id)
        if not creds:
            return False
        if user_id == self._config.miron_id:
            calendar_id = self._config.miron_school_calendar_id
            mode = "miron"
        elif user_id == self._config.michi_id:
            calendar_id = self._config.michi_school_calendar_id
            mode = "michi"
        else:
            return False
        if not calendar_id or not self._service_account_file.exists():
            return False
        try:
            client = self._make_client(creds)
            periods = client.fetch_timetable(target, target)
            calendar_client = self._make_calendar_client()
            self._sync_calendar_for_user(calendar_client, user_id, calendar_id, mode, periods, target, target)
            return True
        except Exception as exc:
            logger.warning("Untis calendar sync failed for %s: %s", mode, exc)
            return False

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
        For Miron: merge consecutive regular lesson periods (with <=60-minute gap) into single events.
        Excludes ignored subjects (R).
        Returns a list of dicts with 'start', 'end', 'summary', 'description'.
        '''
        day_periods = sorted(
            [p for p in periods if (
                p.date == date_str and
                p.code != "cancelled" and
                not _is_ignored_subject(p)
            )],
            key=lambda p: p.start_time,
        )
        if not day_periods:
            return []

        events = []
        block = [day_periods[0]]
        for p in day_periods[1:]:
            prev = block[-1]
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
        For Michi: merge consecutive same-subject regular lesson periods (double periods).
        Excludes ignored subjects.
        Returns list of dicts with 'start', 'end', 'summary', 'description'.
        '''
        day_periods = sorted(
            [p for p in periods if (
                p.date == date_str and
                p.code != "cancelled" and
                not _is_ignored_subject(p)
            )],
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
            self._sync_calendar_for_user(client, user_id, calendar_id, mode, periods, start, end)
        except Exception as exc:
            logger.warning("Untis calendar sync failed for %s: %s", mode, exc)

    def _sync_calendar_for_user(
        self,
        client: UntisCalendarClient,
        user_id: int,
        calendar_id: str,
        mode: str,
        periods: list[UntisPeriod],
        start: dt.date,
        end: dt.date,
    ) -> None:
        start_dt = dt.datetime.combine(start, dt.time(0, 0, tzinfo=BERLIN_TZ))
        end_dt = dt.datetime.combine(end, dt.time(23, 59, 59, tzinfo=BERLIN_TZ))
        existing = client.list_events(calendar_id, start_dt, end_dt)
        adjusted_periods = self._apply_kurzstunden_overrides(periods, start, end)

        if mode == "miron":
            target = self._build_miron_event_specs(adjusted_periods, start, end)
            self._reconcile_miron_calendar(client, calendar_id, target, existing)
        else:
            target = self._build_michi_event_specs(adjusted_periods, start, end)
            self._reconcile_michi_calendar(client, calendar_id, target, existing, adjusted_periods)

    def _apply_kurzstunden_overrides(
        self,
        periods: list[UntisPeriod],
        start: dt.date,
        end: dt.date,
    ) -> list[UntisPeriod]:
        kurzstunden_dates = self._load_kurzstunden_dates()
        if not kurzstunden_dates:
            return periods

        adjusted: list[UntisPeriod] = []
        period_by_date = _periods_by_date(periods)
        for day in _date_range(start, end):
            day_str = day.isoformat()
            day_periods = period_by_date.get(day_str, [])
            if day_str in kurzstunden_dates:
                sorted_day_periods = sorted(day_periods, key=lambda p: (p.start_time, p.end_time, p.id))
                adjusted.extend(_shorten_kurzstunden_day(sorted_day_periods))
            else:
                adjusted.extend(day_periods)

        adjusted.sort(key=lambda p: (p.date, p.start_time, p.end_time, p.subject, p.teacher, p.room, p.id))
        return adjusted

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
        """
        Reconciles the target school schedule with the existing Google Calendar events for Michi.
        
        It identifies which events need to be created, updated, or deleted.
        To avoid deleting personal events on the same calendar, it carefully filters
        which existing events are considered "managed" school events.
        """
        existing_map = _build_existing_event_map(existing)
        target_map = {item["key"]: item for item in target}
        
        # We need a robust list of all possible school subjects to safely identify school events.
        # We dynamically collect them from the periods fetched, and add common fallbacks.
        valid_subjects = set()
        for p in periods:
            valid_subjects.add(_michi_subject([p]))

        # 1. Create or update target events
        for key, item in target_map.items():
            if key in existing_map:
                existing_event = existing_map[key]
                # Update if description (details/teachers) changed
                if existing_event.get("description", "") != item.get("description", ""):
                    client.update_event(calendar_id, existing_event["id"], {"description": item["description"]})
            else:
                # Create if it doesn't exist
                payload = build_event_payload(item["summary"], item["description"], item["start_dt"], item["end_dt"])
                client.create_event(calendar_id, payload)

        # 2. Delete outdated existing events (e.g., cancelled classes or classes moved by Kurzstunden)
        for key, existing_event in existing_map.items():
            if key in target_map:
                continue  # Keep events that are part of the target schedule
                
            summary = existing_event.get("summary", "")
            start_dt = existing_event.get("start_dt")
            end_dt = existing_event.get("end_dt")
            if not summary or not start_dt or not end_dt:
                continue

            # Check if the event looks like a school event managed by the bot:
            # - Condition A: The summary must be a known school subject.
            #   (Previously, this used raw Untis codes which failed to match Google Calendar summaries).
            if summary not in valid_subjects:
                continue
                
            # - Condition B: It falls within typical school hours (7:00 to 17:00).
            #   (Previously, this used strict daily windows which shrank during Kurzstunden or cancellations,
            #    preventing the deletion of the old, longer events).
            start_time = start_dt.astimezone(BERLIN_TZ).time()
            if not (dt.time(7, 0) <= start_time <= dt.time(17, 0)):
                continue

            # If it's a school event but no longer in the target schedule, delete it!
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
        if p.code == "cancelled" or _is_ignored_subject(p):
            continue
        result.setdefault(p.date, set()).add(p.subject or "Schule")
    return result


def _school_windows_by_date(service: UntisService, periods: list[UntisPeriod]) -> dict[str, tuple[dt.datetime, dt.datetime]]:
    windows: dict[str, tuple[dt.datetime, dt.datetime]] = {}
    grouped: dict[str, list[UntisPeriod]] = {}
 
    if periods and service.is_kurzstunden(dt.date.fromisoformat(periods[0].date)):
        sorted_periods = sorted(periods, key=lambda p: (p.date, p.start_time, p.end_time, p.id))
        periods = _shorten_kurzstunden_day(sorted_periods)

    for p in periods:
        if p.code == "cancelled" or _is_ignored_subject(p):
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


def _shorten_kurzstunden_day(periods: list[UntisPeriod]) -> list[UntisPeriod]:
    """Function shortening the periods of a day to 30 minutes each for Kurzstunden, keeping break times."""
    adjusted: list[UntisPeriod] = []

    for period in periods:
        if period.code == "cancelled" and not _is_ignored_subject(period):
            continue

        try:
            lesson_index = _NORMALSTUNDEN_BEGINN.index(period.start_time)
        except ValueError:
            return periods

        start = _time_to_minutes(_KURZSTUNDEN_BEGINN[lesson_index])
        if start is None:
            return periods
        end = start + 30

        adjusted.append(_replace_period_times(period, start, end))

    return adjusted


def _replace_period_times(period: UntisPeriod, start_minutes: int, end_minutes: int) -> UntisPeriod:
    return UntisPeriod(
        id=period.id,
        date=period.date,
        start_time=_minutes_to_time_str(start_minutes),
        end_time=_minutes_to_time_str(end_minutes),
        subject=period.subject,
        teacher=period.teacher,
        room=period.room,
        code=period.code,
        lesson_number=period.lesson_number,
        subst_text=period.subst_text,
        ls_text=period.ls_text,
        info=period.info,
        lesson_count=period.lesson_count,
        period_type=period.period_type,
    )


def _time_to_minutes(value: str) -> int | None:
    try:
        hours, minutes = value.split(":")
        return int(hours) * 60 + int(minutes)
    except Exception:
        return None


def _minutes_to_time_str(value: int) -> str:
    hours, minutes = divmod(value, 60)
    return f"{hours:02d}:{minutes:02d}"


def _michi_subject(block: list[UntisPeriod]) -> str:
    if not block:
        return "Schule"
    lessons = {
        'M': 'Mathe',
        'VX-M': 'Mathe Vertiefung',
        'D': 'Deutsch',
        'E': 'Englisch',
        'SP': 'Sport',
        'ER': 'Religion',
        'PH': 'Physik',
        'CH': 'Chemie',
        'BI': 'Biologie',
        'GE': 'Geschichte',
        'SW': 'SoWi',
        'S0': 'Spanisch',
        'S9': 'Spanisch',
        'L': 'Latein',
        'F': 'Französisch',
        'R': 'Russisch',
        "MU": "Musik",
        "KU": "Kunst",
        'EK': 'Erdkunde',
        'Nach': 'Nachscreiben'
    }

    return lessons.get(block[0].subject.split()[0], block[0].subject)


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