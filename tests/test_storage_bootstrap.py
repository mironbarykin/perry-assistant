from pathlib import Path

from perry_assistant.storage.bootstrap import bootstrap_data
from perry_assistant.storage.json_store import read_json, write_json


def test_bootstrap_creates_files(app_config):
    bootstrap_data(app_config)
    assert app_config.notification_file.exists()
    assert app_config.parents_file.exists()
    assert app_config.processed_emails_file.exists()
    assert app_config.referee_events_file.exists()
    assert app_config.school_absence_file.exists()
    assert app_config.school_timetable_file.exists()
    assert app_config.weather_location_file.exists()
    assert app_config.game_message_rules_file.exists()
    assert app_config.game_message_state_file.exists()
    assert app_config.uportal_seen_rows_file.exists()
    assert app_config.uportal_window_state_file.exists()
    assert app_config.uportal_ignored_rows_file.exists()
    assert app_config.uportal_game_catalog_file.exists()


def test_legacy_school_absence_migration(app_config):
    app_config.data_dir.mkdir(parents=True, exist_ok=True)
    legacy_file = app_config.data_dir / "school_absence.json"
    write_json(legacy_file, [{"date": "2026-02-19", "subject": "Math", "excused": False}])

    bootstrap_data(app_config)
    migrated = read_json(app_config.school_absence_file, [])
    assert migrated
    assert migrated[0]["subject"] == "Math"
    assert not legacy_file.exists()
