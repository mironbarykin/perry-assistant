from __future__ import annotations

import datetime as dt
from typing import Any

import requests

from perry_assistant.config import AppConfig
from perry_assistant.domain.models import WeatherSnapshot


class WeatherClient:
    def __init__(self, config: AppConfig) -> None:
        self._api_key = config.openweather_api_key

    def get_weather(self, location: dict[str, float], target_dt: dt.datetime) -> WeatherSnapshot:
        if not self._api_key:
            return WeatherSnapshot(None, None, None, False, "OPENWEATHER_API_KEY missing")

        url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={location['lat']}&lon={location['lon']}"
            f"&appid={self._api_key}&units=metric"
        )
        response = requests.get(url, timeout=15)
        data: dict[str, Any] = response.json()

        if "list" not in data:
            return WeatherSnapshot(None, None, None, False, f"API error: {data.get('message', 'unknown')}")

        forecasts = data["list"]
        target_ts = int(target_dt.timestamp())
        chosen = min(forecasts, key=lambda forecast: abs(int(forecast["dt"]) - target_ts))

        description = chosen["weather"][0]["description"].lower()
        return WeatherSnapshot(
            temp=chosen["main"].get("temp"),
            wind_speed=chosen["wind"].get("speed"),
            wind_deg=chosen["wind"].get("deg"),
            rain="rain" in description,
            description=description,
        )


def weather_message(weather: WeatherSnapshot | None, route_angle: int = 30) -> str:
    if not weather or weather.temp is None:
        return "Weather unavailable."

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

    return f"{level} | {temp_msg} | {wind_msg} | {rain_msg}"

