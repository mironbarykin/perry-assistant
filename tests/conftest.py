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
        debug_mode=False,
        credentials_file=data_dir / "google_calendar_benny_access.json",
        token_pickle_file=data_dir / "token.pickle",
        notification_file=data_dir / "notification_times.json",
        parents_file=data_dir / "parents.json",
        processed_emails_file=data_dir / "processed_emails.json",
        referee_events_file=data_dir / "referee_events.json",
        gyms_cache_file=data_dir / "gyms_cache.json",
        address_cache_file=data_dir / "address_cache.json",
        weather_location_file=data_dir / "weather_location.json",
        game_message_rules_file=data_dir / "game_message_rules.json",
        game_message_state_file=data_dir / "game_message_state.json",
        uportal_seen_rows_file=data_dir / "uportal_seen_rows.json",
        uportal_window_state_file=data_dir / "uportal_window_state.json",
        uportal_ignored_rows_file=data_dir / "uportal_ignored_rows.json",
        uportal_game_catalog_file=data_dir / "uportal_game_catalog.json",
        basketball_senders=("sender@example.com",),
        home_coords={"lat": 1.0, "lon": 2.0},
        school_coords={"lat": 3.0, "lon": 4.0},
        scopes=("scope1",),
        uportal_login_name="test-user",
        uportal_login_password="test-pass",
        uportal_login_url="https://www.uportal-wbv.de/index.php?o=login&cookie=done",
        michi_id=789012,
        untis_users_file=data_dir / "untis_users.json",
        untis_timetable_state_file=data_dir / "untis_timetable_state.json",
        untis_changes_file=data_dir / "untis_changes_state.json",
        untis_kurzstunden_file=data_dir / "untis_kurzstunden.json",
        untis_server="thalia.webuntis.com",
        untis_school="test-school",
        miron_school_calendar_id="test-miron-calendar-id",
        michi_school_calendar_id="test-michi-calendar-id",
        home_address="Test Address 123, Test City",
        ors_api_key="test-ors-api-key",
        google_api_key="test-google-api-key",
    )