from perry_assistant.domain.models import WeatherSnapshot
from perry_assistant.integrations.weather_client import weather_message


def test_weather_message_unavailable():
    assert weather_message(None) == "Weather unavailable."
    assert weather_message(WeatherSnapshot(None, None, None, False, "")) == "Weather unavailable."


def test_weather_message_headwind_and_rain():
    weather = WeatherSnapshot(
        temp=8.0,
        wind_speed=8.0,
        wind_deg=30.0,  # route is 30, so blow_to = 210 -> headwind
        rain=True,
        description="rain",
    )
    output = weather_message(weather)
    assert "RED" in output or "ORANGE" in output
    assert "Rain expected" in output


def test_weather_message_tailwind_good_conditions():
    weather = WeatherSnapshot(
        temp=18.0,
        wind_speed=3.0,
        wind_deg=210.0,  # blow_to = 30 -> tailwind
        rain=False,
        description="clear",
    )
    output = weather_message(weather)
    assert "GREEN" in output or "YELLOW" in output
    assert "tailwind" in output

