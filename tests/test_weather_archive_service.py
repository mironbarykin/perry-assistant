from __future__ import annotations

import csv
from pathlib import Path

from perry_assistant.services.weather_archive_service import WeatherArchiveService
from perry_assistant.services.weather_location_service import WeatherLocationService


class _FakeWeatherClient:
    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []

    def get_weather_payload(self, location, target_dt):  # noqa: ANN001
        self.calls.append((float(location["lat"]), float(location["lon"])))
        del target_dt
        return {
            "observation": {
                "timestamp": "2026-02-27T08:00:00+00:00",
                "temperature": 12.3,
                "wind_speed": 2.5,
                "wind_direction": 190,
                "condition": "cloudy",
            },
            "sources": [{"id": 1, "source_type": "observation"}],
        }


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_archive_writes_home_and_current_rows_with_home_fallback(app_config):
    weather = _FakeWeatherClient()
    location = WeatherLocationService(app_config)
    archive = WeatherArchiveService(app_config, weather, location)

    archive.capture_now()

    csv_files = list(app_config.data_dir.glob("weather_data_*.csv"))
    assert len(csv_files) == 1
    rows = _read_rows(csv_files[0])
    assert len(rows) == 2
    assert {row["location_label"] for row in rows} == {"home", "current"}
    assert next(row for row in rows if row["location_label"] == "current")["location_source"] == "home_fallback"


def test_archive_uses_latest_shared_location_for_current_row(app_config):
    weather = _FakeWeatherClient()
    location = WeatherLocationService(app_config)
    location.save_shared_location(lat=50.123456, lon=7.654321, user_id=app_config.miron_id)
    archive = WeatherArchiveService(app_config, weather, location)

    archive.capture_now()

    csv_files = list(app_config.data_dir.glob("weather_data_*.csv"))
    rows = _read_rows(csv_files[0])
    current = next(row for row in rows if row["location_label"] == "current")
    assert current["location_source"] == "shared"
    assert current["lat"] == "50.123456"
    assert current["lon"] == "7.654321"

