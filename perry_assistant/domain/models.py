from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass(slots=True)
class EventView:
    start: dt.datetime | None
    line: str
    is_basketball: bool
    is_all_day: bool
    end: dt.datetime | None


@dataclass(slots=True)
class WeatherSnapshot:
    temp: float | None
    wind_speed: float | None
    wind_deg: float | None
    rain: bool
    description: str


@dataclass(slots=True)
class RefereeAssignment:
    type: str
    date: str | None = None
    time: str | None = None
    liga: str | None = None
    spielnummer: str | None = None
    teams: str | None = None
    hall_code: str | None = None
    location: str | None = None
    address: str | None = None
    referees: list[str] | None = None
    old_date: str | None = None
    old_time: str | None = None
    old_location: str | None = None
    old_hall_code: str | None = None
    old_address: str | None = None
    new_date: str | None = None
    new_time: str | None = None
    new_location: str | None = None
    new_hall_code: str | None = None
    new_address: str | None = None
    travel_info: TravelResult | None = None


@dataclass(slots=True)
class AbsenceRecord:
    date: str
    subject: str
    excused: bool = False


@dataclass(slots=True)
class UportalGame:
    detail_id: str
    liga: str
    number: str
    home_team: str
    away_team: str
    date: str
    time: str
    hall: str
    original_referee: str
    ust: str
    distance_km: float
    detail_url: str = ""
    is_umb_offen: bool = False
    address: str | None = None
    travel_info: TravelResult | None = None


@dataclass(slots=True)
class UntisCredentials:
    server: str
    school: str
    username: str
    password: str


@dataclass(slots=True)
class UntisPeriod:
    id: int
    date: str          # "YYYY-MM-DD"
    start_time: str    # "HH:MM"
    end_time: str      # "HH:MM"
    subject: str
    teacher: str
    room: str
    code: str | None   # None, "cancelled", "irregular"
    lesson_number: int | None = None
    subst_text: str | None = None
    ls_text: str | None = None
    info: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "date": self.date,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "subject": self.subject,
            "teacher": self.teacher,
            "room": self.room,
            "code": self.code,
            "lesson_number": self.lesson_number,
            "subst_text": self.subst_text,
            "ls_text": self.ls_text,
            "info": self.info,
        }

    @staticmethod
    def from_dict(data: dict) -> "UntisPeriod":
        return UntisPeriod(
            id=data["id"],
            date=data["date"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            subject=data["subject"],
            teacher=data["teacher"],
            room=data["room"],
            code=data.get("code"),
            lesson_number=data.get("lesson_number"),
            subst_text=data.get("subst_text"),
            ls_text=data.get("ls_text"),
            info=data.get("info"),
        )


@dataclass(slots=True)
class TimetableChange:
    change_type: str   # "cancelled", "restored", "irregular", "new_exam", "modified"
    period: UntisPeriod
    old_period: UntisPeriod | None = None


@dataclass(slots=True)
class TravelResult:
    origin_address: str
    dest_address: str
    car_duration_minutes: int | None
    car_leave_by: dt.datetime | None
    transit_departure: dt.datetime | None
    transit_arrival: dt.datetime | None
    transit_legs: list[str]
    transit_impossible: bool
    strategy: str | None = None  # "home_visit" or "direct" for double-game days
    skip_calendar_event: bool = False  # Skip calendar event for 2nd game in double-game scenario

