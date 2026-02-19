from __future__ import annotations

from pathlib import Path

import pytest

from perry_assistant.config import AppConfig


@pytest.fixture
def app_config(tmp_path: Path) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        tg_token="test-token",
        data_dir=data_dir,
        logs_dir=data_dir / "logs",
        miron_id=123456,
        openweather_api_key="dummy",
        credentials_file=data_dir / "google_calendar_benny_access.json",
        token_pickle_file=data_dir / "token.pickle",
        notification_file=data_dir / "notification_times.json",
        parents_file=data_dir / "parents.json",
        processed_emails_file=data_dir / "processed_emails.json",
        referee_events_file=data_dir / "referee_events.json",
        gyms_cache_file=data_dir / "gyms_cache.json",
        school_absence_file=data_dir / "school_absences.json",
        school_timetable_file=data_dir / "school_timetable.json",
        basketball_senders=("sender@example.com",),
        home_coords={"lat": 1.0, "lon": 2.0},
        school_coords={"lat": 3.0, "lon": 4.0},
        scopes=("scope1",),
    )

