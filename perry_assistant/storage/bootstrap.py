from __future__ import annotations

import logging
import shutil
from pathlib import Path

from perry_assistant.config import AppConfig
from perry_assistant.storage.json_store import read_json, write_json


logger = logging.getLogger(__name__)


def _ensure_json_file(path: Path, default_data) -> None:
    if not path.exists():
        write_json(path, default_data)


def bootstrap_data(config: AppConfig) -> None:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.logs_dir.mkdir(parents=True, exist_ok=True)


    _ensure_json_file(config.notification_file, {})
    _ensure_json_file(config.parents_file, [])
    _ensure_json_file(config.processed_emails_file, [])
    _ensure_json_file(config.referee_events_file, {})
    _ensure_json_file(config.gyms_cache_file, {})
    _ensure_json_file(config.weather_location_file, {})
    _ensure_json_file(config.game_message_rules_file, _default_game_message_rules())
    _ensure_json_file(config.game_message_state_file, _default_game_message_state())
    _ensure_json_file(config.uportal_seen_rows_file, {})
    _ensure_json_file(config.uportal_window_state_file, {})
    _ensure_json_file(config.uportal_ignored_rows_file, {})
    _ensure_json_file(config.uportal_game_catalog_file, {})
    _ensure_json_file(config.untis_users_file, {})
    _ensure_json_file(config.untis_timetable_state_file, {})
    _ensure_json_file(config.untis_changes_file, {})

    _copy_if_missing(Path("google_calendar_benny_access.json"), config.credentials_file)
    _copy_if_missing(Path("token.pickle"), config.token_pickle_file)


def _copy_if_missing(src: Path, dst: Path) -> None:
    if dst.exists() or not src.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dst)
    logger.info("Copied %s -> %s", src, dst)


def _default_game_message_rules() -> dict:
    return {
        "referee": {
            "arrival_minutes_by_league_regex": [
                {"pattern": ".*", "min": 30, "max": 40},
            ],
            "phrases": {
                "greetings": [
                    "Hi {name},",
                    "Hallo {name},",
                ],
                "arrival": [
                    "Ich werde ca. {min}-{max} Minuten vor dem Tipoff da sein.",
                    "Ich bin ungef\u00e4hr {min}-{max} Minuten vor dem Tipoff in der Halle.",
                ],
                "closings": [
                    "Bis dann! VG Miron ;)",
                    "Bis sp\u00e4ter! VG Miron ;)",
                ],
            },
        },
        "coach": {
            "team_rules": {
                "U16": {"meeting_minutes": 50, "send_parents": True, "send_players": True},
                "U12": {"meeting_minutes": 45, "send_parents": True, "send_players": False},
            },
            "home_10am_override_minutes": 60,
            "greetings_parents": [
                "Hallo zusammen!",
                "Hi zusammen!",
            ],
            "greetings_players": [
                "Hi Jungs!",
                "Hey Team!",
            ],
            "jersey_placeholders": {
                "U16": {"bring": "NAME", "wash": "NAME"},
                "U12": {"bring": "NAME", "wash": "NAME"},
            },
        },
    }


def _default_game_message_state() -> dict:
    return {
        "scheduled_weekday": {},
        "sent_keys": [],
    }
