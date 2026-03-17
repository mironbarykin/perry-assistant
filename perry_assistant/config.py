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
    debug_mode: bool
    credentials_file: Path
    token_pickle_file: Path
    notification_file: Path
    parents_file: Path
    processed_emails_file: Path
    referee_events_file: Path
    gyms_cache_file: Path
    school_absence_file: Path
    school_timetable_file: Path
    weather_location_file: Path
    game_message_rules_file: Path
    game_message_state_file: Path
    uportal_seen_rows_file: Path
    uportal_window_state_file: Path
    uportal_ignored_rows_file: Path
    uportal_game_catalog_file: Path
    basketball_senders: tuple[str, ...]
    home_coords: dict[str, float]
    school_coords: dict[str, float]
    scopes: tuple[str, ...]
    uportal_login_name: str | None
    uportal_login_password: str | None
    uportal_login_url: str
    michi_id: int
    untis_users_file: Path
    untis_timetable_state_file: Path
    untis_changes_file: Path
    untis_server: str
    untis_school: str
    miron_school_calendar_id: str
    michi_school_calendar_id: str


def _to_path(value: str | None, default: str) -> Path:
    if value:
        return Path(value).expanduser()
    return Path(default).expanduser()


def _to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


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
        debug_mode=_to_bool(os.getenv("PERRY_DEBUG"), default=False),
        credentials_file=data_dir / "google_calendar_benny_access.json",
        token_pickle_file=data_dir / "token.pickle",
        notification_file=data_dir / "notification_times.json",
        parents_file=data_dir / "parents.json",
        processed_emails_file=data_dir / "processed_emails.json",
        referee_events_file=data_dir / "referee_events.json",
        gyms_cache_file=data_dir / "gyms_cache.json",
        school_absence_file=data_dir / "school_absences.json",
        school_timetable_file=data_dir / "school_timetable.json",
        weather_location_file=data_dir / "weather_location.json",
        game_message_rules_file=data_dir / "game_message_rules.json",
        game_message_state_file=data_dir / "game_message_state.json",
        uportal_seen_rows_file=data_dir / "uportal_seen_rows.json",
        uportal_window_state_file=data_dir / "uportal_window_state.json",
        uportal_ignored_rows_file=data_dir / "uportal_ignored_rows.json",
        uportal_game_catalog_file=data_dir / "uportal_game_catalog.json",
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
        uportal_login_name=os.getenv("UPORTAL_LOGIN_NAME"),
        uportal_login_password=os.getenv("UPORTAL_LOGIN_PASSWORD"),
        uportal_login_url=os.getenv(
            "UPORTAL_LOGIN_URL",
            "https://www.uportal-wbv.de/index.php?o=login&cookie=done",
        ),
        michi_id=int(os.getenv("MICHI_ID", "6805836861")),
        untis_users_file=data_dir / "untis_users.json",
        untis_timetable_state_file=data_dir / "untis_timetable_state.json",
        untis_changes_file=data_dir / "untis_changes_state.json",
        untis_server=os.getenv("UNTIS_SERVER", "theodor-fliedner-gymnasium.webuntis.com"),
        untis_school=os.getenv("UNTIS_SCHOOL", "theodor-fliedner-gymnasium"),
        miron_school_calendar_id=os.getenv("MIRON_SCHOOL_CALENDAR_ID", "d7797cf00146740f692501cf7b0082ffc0e434430aa665e58c73ab89d59fe88a"),
        michi_school_calendar_id=os.getenv("MICHI_SCHOOL_CALENDAR_ID", "michael.kaushanski"),
    )
