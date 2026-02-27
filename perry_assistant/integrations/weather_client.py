from __future__ import annotations

import datetime as dt
import time
from typing import Any

import requests

from perry_assistant.config import AppConfig
from perry_assistant.domain.models import WeatherSnapshot


BRIGHTSKY_WEATHER_URL = "https://api.brightsky.dev/weather"


class WeatherClient:
    def __init__(self, config: AppConfig) -> None:
        self._session = requests.Session()
        self._cache: dict[tuple[float, float, str], tuple[float, dict[str, Any]]] = {}
        self._cache_ttl_seconds = 600

    def get_weather(self, location: dict[str, float], target_dt: dt.datetime) -> WeatherSnapshot:
        result = self.get_weather_payload(location, target_dt)
        return result["snapshot"]

    def get_weather_payload(self, location: dict[str, float], target_dt: dt.datetime) -> dict[str, Any]:
        try:
            payload = self._fetch_payload(location, target_dt)
            chosen = self._pick_closest_observation(payload.get("weather", []), target_dt)
            if not chosen:
                return {
                    "snapshot": WeatherSnapshot(None, None, None, False, "Bright Sky weather list is empty"),
                    "observation": {},
                    "sources": payload.get("sources", []),
                    "raw_payload": payload,
                }
            return {
                "snapshot": self._snapshot_from_observation(chosen),
                "observation": chosen,
                "sources": payload.get("sources", []),
                "raw_payload": payload,
            }
        except requests.RequestException as exc:
            return {
                "snapshot": WeatherSnapshot(None, None, None, False, f"Bright Sky request failed: {exc}"),
                "observation": {},
                "sources": [],
                "raw_payload": {},
            }
        except ValueError as exc:
            return {
                "snapshot": WeatherSnapshot(None, None, None, False, str(exc)),
                "observation": {},
                "sources": [],
                "raw_payload": {},
            }

    def _fetch_payload(self, location: dict[str, float], target_dt: dt.datetime) -> dict[str, Any]:
        target_utc = target_dt.astimezone(dt.UTC) if target_dt.tzinfo else target_dt.replace(tzinfo=dt.UTC)
        target_day = target_utc.date().isoformat()
        lat = round(float(location["lat"]), 5)
        lon = round(float(location["lon"]), 5)
        cache_key = (lat, lon, target_day)
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]

        response = self._session.get(
            BRIGHTSKY_WEATHER_URL,
            params={
                "lat": lat,
                "lon": lon,
                "date": target_day,
                "last_date": target_day,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        self._cache[cache_key] = (now + self._cache_ttl_seconds, payload)
        return payload

    def _pick_closest_observation(self, observations: list[dict[str, Any]], target_dt: dt.datetime) -> dict[str, Any]:
        if not observations:
            return {}

        target_utc = target_dt.astimezone(dt.UTC) if target_dt.tzinfo else target_dt.replace(tzinfo=dt.UTC)
        best = None
        best_delta = None
        for item in observations:
            observed = self._parse_timestamp(item.get("timestamp"))
            if not observed:
                continue
            delta = abs((observed - target_utc).total_seconds())
            if best is None or (best_delta is not None and delta < best_delta):
                best = item
                best_delta = delta
        return best or {}

    @staticmethod
    def _parse_timestamp(raw: Any) -> dt.datetime | None:
        if not isinstance(raw, str):
            return None
        try:
            return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(dt.UTC)
        except ValueError:
            return None

    def _snapshot_from_observation(self, observation: dict[str, Any]) -> WeatherSnapshot:
        description = str(
            observation.get("condition")
            or observation.get("icon")
            or observation.get("fallback_source_ids")
            or ""
        ).lower()

        precipitation = observation.get("precipitation")
        rain = bool(
            (isinstance(precipitation, (float, int)) and precipitation > 0)
            or any(token in description for token in ("rain", "drizzle", "shower", "thunder", "storm"))
        )

        return WeatherSnapshot(
            temp=self._to_float(observation.get("temperature")),
            wind_speed=self._to_float(observation.get("wind_speed")),
            wind_deg=self._to_float(observation.get("wind_direction")),
            rain=rain,
            description=description,
        )

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if isinstance(value, (float, int)):
            return float(value)
        return None


def weather_message(weather: WeatherSnapshot | None, route_angle: int = 30) -> str:
    if not weather or weather.temp is None:
        return "⚪ Weather unavailable."

    score = 0

    if weather.temp < 0:
        score += 3
        temp_msg = f"Temp {weather.temp:.1f}C (freezing)"
    elif weather.temp > 30:
        score += 3
        temp_msg = f"Temp {weather.temp:.1f}C (hot)"
    elif weather.temp < 10 or weather.temp > 22:
        score += 1
        temp_msg = f"Temp {weather.temp:.1f}C (moderate)"
    else:
        temp_msg = f"Temp {weather.temp:.1f}C (good)"

    wind_msg = "Wind unavailable"
    if weather.wind_speed is not None:
        wind_msg = f"Wind {weather.wind_speed:.1f} m/s"
        if weather.wind_deg is not None:
            blow_to = (weather.wind_deg + 180) % 360
            diff = abs(blow_to - route_angle)
            diff = min(diff, 360 - diff)
            if diff <= 45:
                score -= 1
                wind_msg += " tailwind"
            elif diff >= 135:
                score += 2 if weather.wind_speed > 12 else 1
                wind_msg += " headwind"
            else:
                if weather.wind_speed > 12:
                    score += 2
                elif weather.wind_speed > 5.5:
                    score += 1
                wind_msg += " crosswind"
        else:
            if weather.wind_speed > 12:
                score += 2
            elif weather.wind_speed > 5.5:
                score += 1

    rain_msg = "Dry"
    if weather.rain:
        score += 2
        rain_msg = "Rain expected"

    if score <= 0:
        level = "GREEN"
    elif score <= 2:
        level = "YELLOW"
    elif score <= 4:
        level = "ORANGE"
    else:
        level = "RED"

    severity_emoji = {
        "GREEN": "🟢",
        "YELLOW": "🟡",
        "ORANGE": "🟠",
        "RED": "🔴",
    }[level]
    rain_emoji = _rain_emoji(weather)
    rain_suffix = f" {rain_emoji}" if rain_emoji else ""
    wind_value = f"{weather.wind_speed:.1f}" if weather.wind_speed is not None else "-"
    return f"{severity_emoji} 🌡️ {weather.temp:.1f} ℃ 💨 {wind_value} m/s{rain_suffix}"


def _rain_emoji(weather: WeatherSnapshot) -> str | None:
    if not weather.rain:
        return None

    description = weather.description.lower()
    if "thunder" in description or "storm" in description:
        return "⛈️"
    if "drizzle" in description or "light rain" in description:
        return "☂️"
    return "🌧️"
