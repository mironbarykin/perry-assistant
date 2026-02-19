from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class AppConfig:
    tg_token: str
    data_dir: Path
    logs_dir: Path
    miron_id: int
    openweather_api_key: str | None
    credentials_file: Path
    token_pickle_file: Path
    notification_file: Path
    parents_file: Path
    processed_emails_file: Path
    referee_events_file: Path
    gyms_cache_file: Path
    school_absence_file: Path
    school_timetable_file: Path
    basketball_senders: tuple[str, ...]
    home_coords: dict[str, float]
    school_coords: dict[str, float]
    scopes: tuple[str, ...]


def _to_path(value: str | None, default: str) -> Path:
    if value:
        return Path(value).expanduser()
    return Path(default).expanduser()


def load_config() -> AppConfig:
    data_dir = _to_path(os.getenv("DATA_DIR"), "./data")
    logs_dir = data_dir / "logs"

    tg_token = os.getenv("TG_TOKEN")
    if not tg_token:
        raise ValueError("TG_TOKEN is required.")

    return AppConfig(
        tg_token=tg_token,
        data_dir=data_dir,
        logs_dir=logs_dir,
        miron_id=int(os.getenv("MIRON_ID", "1955285579")),
        openweather_api_key=os.getenv("OPENWEATHER_API_KEY"),
        credentials_file=data_dir / "google_calendar_benny_access.json",
        token_pickle_file=data_dir / "token.pickle",
        notification_file=data_dir / "notification_times.json",
        parents_file=data_dir / "parents.json",
        processed_emails_file=data_dir / "processed_emails.json",
        referee_events_file=data_dir / "referee_events.json",
        gyms_cache_file=data_dir / "gyms_cache.json",
        school_absence_file=data_dir / "school_absences.json",
        school_timetable_file=data_dir / "school_timetable.json",
        basketball_senders=(
            "*@uportal-wbv.de",
            "noreply@basketball-bund.net",
            "bekettgregory@gmail.com",
        ),
        home_coords={"lat": 51.261838, "lon": 6.677088},
        school_coords={"lat": 51.305463, "lon": 6.743720},
        scopes=(
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/gmail.readonly",
        ),
    )

