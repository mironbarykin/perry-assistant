from __future__ import annotations

import datetime as dt

import pytest

from perry_assistant.domain.models import TimetableChange, UntisCredentials, UntisPeriod
from perry_assistant.services.untis_service import (
    UntisService,
    detect_changes,
    format_change_notification,
    _merge_doubled_lessons,
    _time_gap_minutes,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _period(
    date: str = "2026-03-12",
    start: str = "08:00",
    end: str = "08:45",
    subject: str = "MATH",
    teacher: str = "Mueller",
    room: str = "101",
    code: str | None = None,
    lesson_number: int | None = 1,
    lesson_count: int = 1,
    pid: int = 1,
) -> UntisPeriod:
    return UntisPeriod(
        id=pid,
        date=date,
        start_time=start,
        end_time=end,
        subject=subject,
        teacher=teacher,
        room=room,
        code=code,
        lesson_number=lesson_number,
        lesson_count=lesson_count,
    )


# ---------------------------------------------------------------------------
# detect_changes
# ---------------------------------------------------------------------------

class TestDetectChanges:
    def test_no_changes_empty(self):
        assert detect_changes([], []) == []

    def test_no_changes_identical(self):
        p = _period()
        assert detect_changes([p], [p]) == []

    def test_detects_cancellation(self):
        old = _period(code=None)
        new = _period(code="cancelled")
        changes = detect_changes([old], [new])
        assert len(changes) == 1
        assert changes[0].change_type == "cancelled"

    def test_detects_restoration(self):
        old = _period(code="cancelled")
        new = _period(code=None)
        changes = detect_changes([old], [new])
        assert len(changes) == 1
        assert changes[0].change_type == "restored"

    def test_detects_teacher_change(self):
        old = _period(teacher="Mueller")
        new = _period(teacher="Schmidt")
        changes = detect_changes([old], [new])
        assert len(changes) == 1
        assert changes[0].change_type == "modified"

    def test_detects_room_change(self):
        old = _period(room="101")
        new = _period(room="205")
        changes = detect_changes([old], [new])
        assert len(changes) == 1
        assert changes[0].change_type == "modified"
        assert changes[0].old_period is not None
        assert changes[0].old_period.room == "101"

    def test_new_period_detected(self):
        new = _period(date="2026-03-13", start="10:00", end="10:45", subject="PHYS", pid=99)
        changes = detect_changes([], [new])
        assert len(changes) == 1
        assert changes[0].change_type in {"modified", "new_exam"}

    def test_new_exam_detected(self):
        new = _period(subject="Klausur", pid=50)
        changes = detect_changes([], [new])
        assert len(changes) == 1
        assert changes[0].change_type == "new_exam"

    def test_removed_period_detected(self):
        old = _period(pid=10)
        changes = detect_changes([old], [])
        assert len(changes) == 1
        assert changes[0].change_type == "cancelled"

    def test_already_cancelled_removal_ignored(self):
        old = _period(code="cancelled", pid=10)
        changes = detect_changes([old], [])
        assert changes == []

    def test_multiple_changes(self):
        p1_old = _period(subject="MATH", pid=1)
        p2_old = _period(subject="BIO", start="09:00", end="09:45", pid=2)
        p1_new = _period(subject="MATH", code="cancelled", pid=1)
        p3_new = _period(subject="PHYS", start="10:00", end="10:45", pid=3)
        changes = detect_changes([p1_old, p2_old], [p1_new, p3_new])
        change_types = {c.change_type for c in changes}
        assert "cancelled" in change_types
        assert "modified" in change_types or "new_exam" in change_types

    def test_interleaved_double_lessons_are_merged_by_signature_and_time(self):
        periods = [
            _period(date="2026-05-08", start="07:55", end="08:40", subject="CH G3", teacher="KB", room="R001", pid=701602),
            _period(date="2026-05-08", start="11:35", end="12:20", subject="D G4", teacher="ADL", room="R002", pid=507443),
            _period(date="2026-05-08", start="07:55", end="08:40", subject="MU G1", teacher="ADL", room="R124", pid=595760),
            _period(date="2026-05-08", start="08:45", end="09:30", subject="CH G3", teacher="KB", room="R001", pid=701605),
            _period(date="2026-05-08", start="12:25", end="13:10", subject="D G4", teacher="ADL", room="R002", pid=507446),
            _period(date="2026-05-08", start="08:45", end="09:30", subject="MU G1", teacher="ADL", room="R124", pid=595763),
            _period(date="2026-05-08", start="09:35", end="10:20", subject="CH G3", teacher="KB", room="R001", pid=701608),
        ]
        merged = _merge_doubled_lessons(periods)
        counts = {period.subject: period.lesson_count for period in merged}
        assert counts["CH G3"] == 3
        assert counts["MU G1"] == 2
        assert counts["D G4"] == 2


# ---------------------------------------------------------------------------
# format_change_notification
# ---------------------------------------------------------------------------

class TestFormatChangeNotification:
    def test_cancelled(self):
        p = _period(code="cancelled", lesson_number=1, subject="MATH", date="2026-03-12")
        ch = TimetableChange("cancelled", p, None)
        msg = format_change_notification(ch)
        assert "ENTFÄLLT" in msg
        assert "MATH" in msg
        assert "12.03" in msg

    def test_restored(self):
        p = _period(lesson_number=2, subject="BIO", date="2026-03-12")
        ch = TimetableChange("restored", p, None)
        msg = format_change_notification(ch)
        assert "wieder statt" in msg

    def test_modified_double_lesson_uses_room_change_format(self):
        old = _period(subject="SP G6", teacher="RUF", room="R302", start="07:55", end="09:30", lesson_count=2)
        new = _period(subject="SP G6", teacher="RUF", room="R301", start="07:55", end="09:30", lesson_count=2)
        ch = TimetableChange("modified", new, old)
        msg = format_change_notification(ch)
        assert "SP G6 x2" in msg
        assert "(RUF/R302 → jetzt: RUF/R301)" in msg
        assert "vorher" not in msg

    def test_modified_double_lesson_omits_room_change_format_when_unchanged(self):
        old = _period(subject="SP G6", teacher="RUF", room="R302", start="07:55", end="09:30", lesson_count=2)
        new = _period(subject="SP G6", teacher="RUF", room="R302", start="07:55", end="09:30", lesson_count=2)
        new.info = "Sport drinnen > Basketball"
        ch = TimetableChange("modified", new, old)
        msg = format_change_notification(ch)
        assert "SP G6 x2" in msg
        assert "→ jetzt:" not in msg
        assert "Info: Sport drinnen > Basketball" in msg

    def test_new_exam(self):
        p = _period(subject="Klausur", date="2026-03-15")
        ch = TimetableChange("new_exam", p, None)
        msg = format_change_notification(ch)
        assert "Prüfung" in msg
        assert "15.03" in msg

    def test_modified_with_old(self):
        old = _period(teacher="Mueller", room="101")
        new = _period(teacher="Schmidt", room="202")
        ch = TimetableChange("modified", new, old)
        msg = format_change_notification(ch)
        assert "Mueller" in msg
        assert "Schmidt" in msg

    def test_uses_lesson_number_when_available(self):
        p = _period(lesson_number=3, subject="GEO")
        ch = TimetableChange("cancelled", p, None)
        msg = format_change_notification(ch)
        assert "3." in msg

    def test_uses_start_time_when_no_lesson_number(self):
        p = _period(lesson_number=None, start="11:30", subject="GEO")
        ch = TimetableChange("cancelled", p, None)
        msg = format_change_notification(ch)
        assert "11:30" in msg


# ---------------------------------------------------------------------------
# UntisService – credentials & state persistence
# ---------------------------------------------------------------------------

class TestUntisServiceCredentials:
    def test_save_and_load_credentials(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        creds = UntisCredentials(
            server="thalia.webuntis.com",
            school="TestSchool",
            username="student1",
            password="secret",
        )
        svc.save_credentials(42, creds)
        loaded = svc.get_credentials(42)
        assert loaded is not None
        assert loaded.username == "student1"
        assert loaded.password == "secret"

    def test_has_credentials_false_initially(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        assert svc.has_credentials(999) is False

    def test_has_credentials_true_after_save(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        creds = UntisCredentials(server="s", school="sc", username="u", password="p")
        svc.save_credentials(10, creds)
        assert svc.has_credentials(10) is True

    def test_delete_credentials(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        creds = UntisCredentials(server="s", school="sc", username="u", password="p")
        svc.save_credentials(10, creds)
        removed = svc.delete_credentials(10)
        assert removed is True
        assert svc.has_credentials(10) is False

    def test_delete_nonexistent_credentials(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        assert svc.delete_credentials(999) is False


class TestUntisServiceTimetableState:
    def test_save_and_load_timetable(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        periods = [_period(pid=1), _period(pid=2, subject="BIO")]
        svc.save_user_timetable(7, periods)
        loaded = svc.load_user_timetable(7)
        assert len(loaded) == 2
        subjects = {p.subject for p in loaded}
        assert "MATH" in subjects
        assert "BIO" in subjects

    def test_empty_timetable_initially(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        assert svc.load_user_timetable(999) == []


# ---------------------------------------------------------------------------
# UntisService – refresh_user_timetable
# ---------------------------------------------------------------------------

class _DummyClient:
    def __init__(self, periods: list[UntisPeriod]):
        self._periods = periods

    def fetch_timetable(self, start: dt.date, end: dt.date) -> list[UntisPeriod]:
        return self._periods


class TestUntisServiceRefresh:
    def test_refresh_first_sync_baseline(self, app_config, monkeypatch):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        creds = UntisCredentials(
            server="thalia.webuntis.com",
            school="TestSchool",
            username="student1",
            password="secret",
        )
        svc.save_credentials(42, creds)
        periods = [_period(subject="MATH")]

        monkeypatch.setattr(svc, "_make_client", lambda _: _DummyClient(periods))

        changes = svc.refresh_user_timetable(42)
        assert changes == []
        loaded = svc.load_user_timetable(42)
        assert len(loaded) == 1
        assert loaded[0].subject == "MATH"

    def test_refresh_detects_changes(self, app_config, monkeypatch):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        creds = UntisCredentials(
            server="thalia.webuntis.com",
            school="TestSchool",
            username="student1",
            password="secret",
        )
        svc.save_credentials(55, creds)

        old = _period(teacher="Mueller")
        svc.save_user_timetable(55, [old])
        new = _period(teacher="Schmidt")

        monkeypatch.setattr(svc, "_make_client", lambda _: _DummyClient([new]))

        changes = svc.refresh_user_timetable(55)
        assert len(changes) == 1
        assert changes[0].change_type == "modified"

    def test_refresh_ignores_yesterday_periods(self, app_config, monkeypatch):
        """Periods from yesterday must not be reported as new cancellations."""
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        creds = UntisCredentials(
            server="thalia.webuntis.com",
            school="TestSchool",
            username="student1",
            password="secret",
        )
        svc.save_credentials(77, creds)

        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        today = dt.date.today().isoformat()

        # Stored timetable contains a period from yesterday (normal, not cancelled)
        old_yesterday = _period(date=yesterday, subject="SP", pid=10)
        old_today = _period(date=today, subject="MATH", pid=11)
        svc.save_user_timetable(77, [old_yesterday, old_today])

        # The fresh fetch only returns today's period (yesterday is gone naturally)
        new_today = _period(date=today, subject="MATH", pid=11)
        monkeypatch.setattr(svc, "_make_client", lambda _: _DummyClient([new_today]))

        changes = svc.refresh_user_timetable(77)
        # Yesterday's period disappearing must NOT produce a cancellation
        assert all(c.period.date != yesterday for c in changes)


# ---------------------------------------------------------------------------
# UntisService – daily digest
# ---------------------------------------------------------------------------

class TestDailyDigest:
    def test_digest_empty(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        msg = svc.daily_digest_for_user(42)
        assert "keine" in msg.lower()

    def test_digest_shows_subjects(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        today = dt.date.today().isoformat()
        periods = [_period(date=today, subject="MATH"), _period(date=today, subject="BIO", pid=2)]
        svc.save_user_timetable(5, periods)
        msg = svc.daily_digest_for_user(5)
        assert "MATH" in msg
        assert "BIO" in msg

    def test_digest_marks_cancelled(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        today = dt.date.today().isoformat()
        periods = [_period(date=today, code="cancelled")]
        svc.save_user_timetable(6, periods)
        msg = svc.daily_digest_for_user(6)
        assert "ENTFÄLLT" in msg


# ---------------------------------------------------------------------------
# Calendar event builders
# ---------------------------------------------------------------------------

class TestCalendarEventBuilders:
    def test_miron_merges_consecutive(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        date = "2026-03-13"
        periods = [
            _period(date=date, start="08:00", end="08:45", subject="MATH", pid=1),
            _period(date=date, start="08:45", end="09:30", subject="BIO", pid=2),
        ]
        events = svc.build_miron_calendar_events(periods, date)
        assert len(events) == 1
        assert "MATH" in events[0]["summary"]
        assert "BIO" in events[0]["summary"]

    def test_miron_splits_big_gap(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        date = "2026-03-13"
        periods = [
            _period(date=date, start="08:00", end="08:45", subject="MATH", pid=1),
            _period(date=date, start="12:00", end="12:45", subject="BIO", pid=2),
        ]
        events = svc.build_miron_calendar_events(periods, date)
        assert len(events) == 2

    def test_michi_separate_events(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        date = "2026-03-13"
        periods = [
            _period(date=date, start="08:00", end="08:45", subject="MATH", pid=1),
            _period(date=date, start="08:45", end="09:30", subject="BIO", pid=2),
        ]
        events = svc.build_michi_calendar_events(periods, date)
        assert len(events) == 2
        assert events[0]["summary"] == "MATH"
        assert events[1]["summary"] == "BIO"

    def test_cancelled_excluded_from_calendar(self, app_config):
        app_config.data_dir.mkdir(parents=True, exist_ok=True)
        svc = UntisService(app_config)
        date = "2026-03-13"
        periods = [_period(date=date, code="cancelled")]
        assert svc.build_miron_calendar_events(periods, date) == []
        assert svc.build_michi_calendar_events(periods, date) == []


# ---------------------------------------------------------------------------
# _time_gap_minutes helper
# ---------------------------------------------------------------------------

def test_time_gap_minutes_zero():
    assert _time_gap_minutes("08:45", "08:45") == 0


def test_time_gap_minutes_positive():
    assert _time_gap_minutes("08:45", "09:30") == 45


def test_time_gap_minutes_invalid():
    assert _time_gap_minutes("bad", "09:00") == 999
