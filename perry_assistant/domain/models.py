from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


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
