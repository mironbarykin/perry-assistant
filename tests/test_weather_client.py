from __future__ import annotations

import datetime as dt

from perry_assistant.integrations.weather_client import WeatherClient


def test_get_weather_payload_selects_closest_observation(app_config, monkeypatch):
    client = WeatherClient(app_config)
    target = dt.datetime(2026, 2, 27, 8, 30, tzinfo=dt.UTC)

    monkeypatch.setattr(
        client,
        "_fetch_payload",
        lambda location, target_dt: {  # noqa: ARG005
            "weather": [
                {
                    "timestamp": "2026-02-27T07:00:00+00:00",
                    "temperature": 5.0,
                    "wind_speed": 1.0,
                    "wind_direction": 100,
                    "precipitation": 0.0,
                    "condition": "clear",
                },
                {
                    "timestamp": "2026-02-27T08:00:00+00:00",
                    "temperature": 7.5,
                    "wind_speed": 2.0,
                    "wind_direction": 110,
                    "precipitation": 1.2,
                    "condition": "rain",
                },
            ],
            "sources": [{"id": 42}],
        },
    )

    payload = client.get_weather_payload({"lat": 1.0, "lon": 2.0}, target)
    snapshot = payload["snapshot"]
    assert snapshot.temp == 7.5
    assert snapshot.wind_speed == 2.0
    assert snapshot.wind_deg == 110.0
    assert snapshot.rain is True
    assert payload["sources"] == [{"id": 42}]

