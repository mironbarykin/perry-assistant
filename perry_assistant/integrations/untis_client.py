from __future__ import annotations

import ast
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


def _period_to_model(period, subject_map: dict[int, str], room_map: dict[int, str]) -> UntisPeriod:
    subject = ""
    teacher = ""
    room = ""

    raw_subjects = _get_raw_value(period, "su")
    subject_id = _first_id(_extract_id_list(raw_subjects))
    if subject_id is not None:
        subject = _lookup_name(subject_id, subject_map)

    raw_rooms = _get_raw_value(period, "ro")
    room_id = _first_id(_extract_id_list(raw_rooms))
    if room_id is not None:
        room = _lookup_name(room_id, room_map)

    raw_teachers = _get_raw_value(period, "te")
    teacher_id = _first_id(_extract_id_list(raw_teachers))
    sg = _get_raw_value(period, "sg")
    teacher = _derive_teacher_code(sg, teacher_id)

    raw_code = None
    try:
        raw_code = period.code()
    except Exception:
        raw_code = None

    subst_text = _get_subst_text(period)
    code = _derive_status_code(raw_code, subst_text)

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
        lesson_number=None,
    )


def _safe_call(value) -> object | None:
    try:
        return value() if callable(value) else value
    except Exception:
        return None


def _parse_literal(value: object) -> object | None:
    if isinstance(value, str):
        try:
            return ast.literal_eval(value)
        except Exception:
            return None
    return value


def _extract_id_list(value: object | None) -> list[object]:
    if value is None:
        return []
    value = _parse_literal(value)
    if isinstance(value, (list, tuple)):
        return list(value)
    if isinstance(value, dict):
        return [value]
    return []


def _first_id(items: list[object]) -> int | None:
    for item in items:
        if isinstance(item, dict) and "id" in item:
            try:
                return int(item["id"])
            except Exception:
                return None
        if hasattr(item, "id"):
            try:
                return int(getattr(item, "id"))
            except Exception:
                return None
    return None


def _get_raw_value(period, key: str) -> object | None:
    data = getattr(period, "_data", None)
    if isinstance(data, dict) and key in data:
        return data.get(key)
    return None


def _get_subst_text(period) -> str:
    raw = None
    if hasattr(period, "substText"):
        raw = _safe_call(getattr(period, "substText"))
    if raw is None:
        raw = _get_raw_value(period, "substText")
    return str(raw) if raw else ""


def _derive_status_code(raw_code: str | None, subst_text: str) -> str | None:
    if raw_code:
        code = str(raw_code).lower()
        if code == "cancelled":
            return "cancelled"
        if code == "irregular":
            return "irregular"

    if subst_text:
        if "eigenverantwortliches arbeiten" in subst_text.lower():
            return "cancelled"
        return "irregular"

    return None


def _derive_teacher_code(sg: object | None, teacher_id: int | None) -> str:
    if isinstance(sg, str) and "_" in sg:
        return sg.split("_")[-1].strip()
    if teacher_id is not None:
        return str(teacher_id)
    return ""


def _lookup_name(item_id: int, mapping: dict[int, str]) -> str:
    if item_id in mapping:
        return mapping[item_id]
    return str(item_id)


def _build_name_map(session, method_names: tuple[str, ...]) -> dict[int, str]:
    for name in method_names:
        attr = getattr(session, name, None)
        if attr is None:
            continue
        try:
            items = attr() if callable(attr) else attr
        except Exception as exc:
            logger.debug("Untis session.%s failed: %s", name, exc)
            continue
        if not items:
            return {}
        result: dict[int, str] = {}
        for item in items:
            item_id = getattr(item, "id", None)
            item_name = getattr(item, "name", None)
            if item_id is None or item_name is None:
                continue
            try:
                result[int(item_id)] = str(item_name)
            except Exception:
                continue
        return result
    return {}


def _describe_identity(obj: object | None) -> str:
    if obj is None:
        return "None"
    parts = [obj.__class__.__name__]
    for attr in ("id", "name", "full_name", "personType", "type"):
        if hasattr(obj, attr):
            try:
                parts.append(f"{attr}={getattr(obj, attr)}")
            except Exception:
                parts.append(f"{attr}=?")
    return "<" + " ".join(parts) + ">"


def _resolve_student(session) -> object:
    """Resolve the logged-in student object for timetable requests."""
    user = getattr(session, "user", None)
    if user is not None and hasattr(user, "id"):
        logger.debug("Untis session user: %s", _describe_identity(user))
        return user

    candidate_methods = ("students", "get_students", "children", "get_children", "childs")
    for name in candidate_methods:
        attr = getattr(session, name, None)
        if attr is None:
            continue
        try:
            students = attr() if callable(attr) else attr
        except Exception as exc:
            logger.debug("Untis session.%s failed: %s", name, exc)
            continue
        if students:
            resolved = students[0] if isinstance(students, (list, tuple)) else students
            logger.debug("Untis resolved student via %s: %s", name, _describe_identity(resolved))
            return resolved

    raise ValueError(
        "Could not resolve student for WebUntis session. "
        "Please log in with a student account."
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
            ).login() as session:
                subject_map = _build_name_map(session, ("get_subjects", "subjects"))
                room_map = _build_name_map(session, ("get_rooms", "rooms"))
                try:
                    logger.debug("Untis trying session.my_timetable for %s", self._username)
                    raw_periods = session.my_timetable(start=start, end=end)
                except Exception as exc:
                    logger.debug(
                        "Untis session.my_timetable failed for %s: %s",
                        self._username,
                        exc,
                    )
                    student = _resolve_student(session)
                    raw_periods = session.timetable_extended(
                        start=start,
                        end=end,
                        student=student,
                    )
                return [_period_to_model(p, subject_map, room_map) for p in raw_periods]
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
            ).login():
                return True
        except Exception:
            return False
