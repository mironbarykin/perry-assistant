from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import requests

from perry_assistant.config import AppConfig
from perry_assistant.storage.json_store import read_json, write_json


@dataclass(frozen=True, slots=True)
class SharedLocation:
    lat: float
    lon: float
    city: str | None
    updated_at: str
    updated_by: int


class WeatherLocationService:
    def __init__(self, config: AppConfig) -> None:
        self._file = config.weather_location_file

    def get_shared_location(self) -> SharedLocation | None:
        payload = read_json(self._file, {})
        if not isinstance(payload, dict):
            return None
        lat = payload.get("lat")
        lon = payload.get("lon")
        city = payload.get("city")
        updated_at = payload.get("updated_at")
        updated_by = payload.get("updated_by")
        if not isinstance(lat, (float, int)) or not isinstance(lon, (float, int)):
            return None
        if not isinstance(updated_at, str) or not updated_at:
            return None
        if not isinstance(updated_by, int):
            return None
        return SharedLocation(
            lat=float(lat),
            lon=float(lon),
            city=city if isinstance(city, str) and city.strip() else None,
            updated_at=updated_at,
            updated_by=updated_by,
        )

    def save_shared_location(self, lat: float, lon: float, user_id: int, city: str | None = None) -> SharedLocation:
        payload = {
            "lat": float(lat),
            "lon": float(lon),
            "city": city.strip() if isinstance(city, str) and city.strip() else "",
            "updated_at": dt.datetime.now(dt.UTC).isoformat(),
            "updated_by": int(user_id),
        }
        write_json(self._file, payload)
        return SharedLocation(
            lat=payload["lat"],
            lon=payload["lon"],
            city=payload["city"] or None,
            updated_at=payload["updated_at"],
            updated_by=payload["updated_by"],
        )

    def resolve_current_location(self, home_coords: dict[str, float]) -> tuple[dict[str, float], bool]:
        shared = self.get_shared_location()
        if shared:
            return {"lat": shared.lat, "lon": shared.lon}, True
        return {"lat": float(home_coords["lat"]), "lon": float(home_coords["lon"])}, False

    def location_city_label(self, fallback: str = "home") -> str:
        shared = self.get_shared_location()
        if shared and shared.city:
            return shared.city
        return fallback

    def resolve_city_name(self, lat: float, lon: float) -> str | None:
        try:
            response = requests.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={
                    "lat": float(lat),
                    "lon": float(lon),
                    "format": "jsonv2",
                    "zoom": 10,
                    "addressdetails": 1,
                },
                headers={"User-Agent": "perry-assistant/1.0"},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            return None

        address = payload.get("address", {})
        if not isinstance(address, dict):
            return None
        for key in ("city", "town", "village", "municipality", "county", "state"):
            value = address.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
