from __future__ import annotations

import csv
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Any

from telegram.ext import ContextTypes

from perry_assistant.config import AppConfig
from perry_assistant.constants import BERLIN_TZ
from perry_assistant.integrations.weather_client import WeatherClient
from perry_assistant.services.weather_location_service import WeatherLocationService


logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    "captured_at_utc",
    "captured_at_local",
    "slot",
    "location_label",
    "location_source",
    "lat",
    "lon",
    "weather_timestamp",
    "temperature",
    "dew_point",
    "relative_humidity",
    "pressure_msl",
    "cloud_cover",
    "visibility",
    "wind_speed",
    "wind_direction",
    "wind_gust_speed",
    "precipitation",
    "sunshine",
    "condition",
    "icon",
    "fallback_source_ids",
    "observation_json",
    "sources_json",
    "raw_payload_json",
]


class WeatherArchiveService:
    def __init__(
        self,
        config: AppConfig,
        weather_client: WeatherClient,
        location_service: WeatherLocationService,
    ) -> None:
        self._config = config
        self._weather = weather_client
        self._location = location_service

    async def process_scheduled_capture(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        self.capture_now()

    def capture_now(self) -> None:
        now_local = dt.datetime.now(BERLIN_TZ)
        now_utc = now_local.astimezone(dt.UTC)
        slot = f"{now_local.hour:02d}:00"
        current_coords, has_shared = self._location.resolve_current_location(self._config.home_coords)

        home_payload = self._weather.get_weather_payload(self._config.home_coords, now_local)
        current_payload = (
            home_payload
            if self._same_coords(current_coords, self._config.home_coords)
            else self._weather.get_weather_payload(current_coords, now_local)
        )

        rows = [
            self._build_row(
                now_utc=now_utc,
                now_local=now_local,
                slot=slot,
                location_label="home",
                location_source="home",
                coords=self._config.home_coords,
                weather_payload=home_payload,
            ),
            self._build_row(
                now_utc=now_utc,
                now_local=now_local,
                slot=slot,
                location_label="current",
                location_source="shared" if has_shared else "home_fallback",
                coords=current_coords,
                weather_payload=current_payload,
            ),
        ]
        self._append_rows(self._csv_path_for_year(now_local.year), rows)

    def _build_row(
        self,
        now_utc: dt.datetime,
        now_local: dt.datetime,
        slot: str,
        location_label: str,
        location_source: str,
        coords: dict[str, float],
        weather_payload: dict[str, Any],
    ) -> dict[str, str]:
        observation = weather_payload.get("observation", {}) if isinstance(weather_payload, dict) else {}
        sources = weather_payload.get("sources", []) if isinstance(weather_payload, dict) else []
        raw_payload = weather_payload.get("raw_payload", {}) if isinstance(weather_payload, dict) else {}
        return {
            "captured_at_utc": now_utc.isoformat(),
            "captured_at_local": now_local.isoformat(),
            "slot": slot,
            "location_label": location_label,
            "location_source": location_source,
            "lat": f"{float(coords['lat']):.6f}",
            "lon": f"{float(coords['lon']):.6f}",
            "weather_timestamp": str(observation.get("timestamp", "")),
            "temperature": self._value(observation.get("temperature")),
            "dew_point": self._value(observation.get("dew_point")),
            "relative_humidity": self._value(observation.get("relative_humidity")),
            "pressure_msl": self._value(observation.get("pressure_msl")),
            "cloud_cover": self._value(observation.get("cloud_cover")),
            "visibility": self._value(observation.get("visibility")),
            "wind_speed": self._value(observation.get("wind_speed")),
            "wind_direction": self._value(observation.get("wind_direction")),
            "wind_gust_speed": self._value(observation.get("wind_gust_speed")),
            "precipitation": self._value(observation.get("precipitation")),
            "sunshine": self._value(observation.get("sunshine")),
            "condition": str(observation.get("condition", "")),
            "icon": str(observation.get("icon", "")),
            "fallback_source_ids": json.dumps(observation.get("fallback_source_ids", []), ensure_ascii=False),
            "observation_json": json.dumps(observation, ensure_ascii=False),
            "sources_json": json.dumps(sources, ensure_ascii=False),
            "raw_payload_json": json.dumps(raw_payload, ensure_ascii=False),
        }

    @staticmethod
    def _value(raw: Any) -> str:
        if raw is None:
            return ""
        if isinstance(raw, float):
            return f"{raw:.3f}"
        return str(raw)

    def _csv_path_for_year(self, year: int) -> Path:
        return self._config.data_dir / f"weather_data_{year}.csv"

    def _append_rows(self, path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new_file = not path.exists() or path.stat().st_size == 0
        with path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            if is_new_file:
                writer.writeheader()
            for row in rows:
                writer.writerow(row)
        logger.info("Weather archive updated: %s (+%d rows)", path, len(rows))

    @staticmethod
    def _same_coords(left: dict[str, float], right: dict[str, float]) -> bool:
        return (
            round(float(left["lat"]), 5) == round(float(right["lat"]), 5)
            and round(float(left["lon"]), 5) == round(float(right["lon"]), 5)
        )
