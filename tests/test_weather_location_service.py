from __future__ import annotations

from perry_assistant.services.weather_location_service import WeatherLocationService


def test_save_and_replace_shared_location(app_config):
    service = WeatherLocationService(app_config)
    first = service.save_shared_location(lat=51.1, lon=6.7, user_id=123, city="Meerbusch")
    second = service.save_shared_location(lat=50.9, lon=6.6, user_id=123, city="Dusseldorf")

    loaded = service.get_shared_location()
    assert loaded is not None
    assert loaded.lat == second.lat
    assert loaded.lon == second.lon
    assert loaded.city == "Dusseldorf"
    assert loaded.updated_at >= first.updated_at


def test_resolve_current_location_falls_back_to_home(app_config):
    service = WeatherLocationService(app_config)
    coords, has_shared = service.resolve_current_location(app_config.home_coords)

    assert has_shared is False
    assert coords["lat"] == app_config.home_coords["lat"]
    assert coords["lon"] == app_config.home_coords["lon"]


def test_location_city_label_uses_saved_city(app_config):
    service = WeatherLocationService(app_config)
    service.save_shared_location(lat=51.1, lon=6.7, user_id=123, city="Meerbusch")
    assert service.location_city_label(fallback="home") == "Meerbusch"
