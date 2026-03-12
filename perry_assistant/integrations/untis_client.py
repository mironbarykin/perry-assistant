from __future__ import annotations

import datetime as dt
import logging

import webuntis
import webuntis.errors

from perry_assistant.domain.models import UntisPeriod


logger = logging.getLogger(__name__)

_USERAGENT = "perry-assistant/1.0 (school timetable bot)"


def _fmt_date(d: dt.date) -> str:
    return d.strftime("%Y-%m-%d")


def _fmt_time(t: int) -> str:
    """Convert WebUntis integer time (e.g. 800, 1315) to HH:MM string."""
    h, m = divmod(t, 100)
    return f"{h:02d}:{m:02d}"


def _period_to_model(period) -> UntisPeriod:
    subject = ""
    teacher = ""
    room = ""
    lesson_number = None

    try:
        subjects = list(period.subjects)
        if subjects:
            subject = subjects[0].name
    except Exception:
        pass

    try:
        teachers = list(period.teachers)
        if teachers:
            teacher = teachers[0].name
    except Exception:
        pass

    try:
        rooms = list(period.rooms)
        if rooms:
            room = rooms[0].name
    except Exception:
        pass

    try:
        lesson_number = period.lsnumber()
    except Exception:
        pass

    try:
        code = period.code()
    except Exception:
        code = None

    start_dt: dt.datetime = period.start
    end_dt: dt.datetime = period.end
    date_str = _fmt_date(start_dt.date())
    start_str = start_dt.strftime("%H:%M")
    end_str = end_dt.strftime("%H:%M")

    return UntisPeriod(
        id=period.id,
        date=date_str,
        start_time=start_str,
        end_time=end_str,
        subject=subject,
        teacher=teacher,
        room=room,
        code=code,
        lesson_number=lesson_number,
    )


class UntisClient:
    """Fetches timetable data for a single student from WebUntis."""

    def __init__(self, server: str, school: str, username: str, password: str) -> None:
        self._server = server
        self._school = school
        self._username = username
        self._password = password

    def fetch_timetable(
        self,
        start: dt.date,
        end: dt.date,
    ) -> list[UntisPeriod]:
        """Return timetable periods for the given date range."""
        try:
            with webuntis.Session(
                server=self._server,
                school=self._school,
                username=self._username,
                password=self._password,
                useragent=_USERAGENT,
            ) as session:
                raw_periods = session.timetable_extended(
                    start=start,
                    end=end,
                )
                return [_period_to_model(p) for p in raw_periods]
        except webuntis.errors.BadCredentialsError as exc:
            logger.warning("Untis bad credentials for %s: %s", self._username, exc)
            raise
        except Exception as exc:
            logger.error("Untis fetch failed for %s: %s", self._username, exc)
            raise

    def test_connection(self) -> bool:
        """Return True if credentials are valid."""
        try:
            with webuntis.Session(
                server=self._server,
                school=self._school,
                username=self._username,
                password=self._password,
                useragent=_USERAGENT,
            ):
                return True
        except Exception:
            return False
