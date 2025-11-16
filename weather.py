

def wind_direction_effect(wind_deg: float, route_angle: int = 30) -> str:
    """Return tailwind/headwind/crosswind based on wind coming from wind_deg."""
    blow_to = (wind_deg + 180) % 360
    diff = abs(blow_to - route_angle)
    diff = min(diff, 360 - diff)

    if diff <= 45:
        return "tailwind"
    elif diff >= 135:
        return "headwind"
    else:
        return "crosswind"

def bike_advice(weather: dict, wind_deg=None, route_angle=30) -> str:
    """Evaluate biking conditions and return advice."""
    if not weather or weather.get("temp") is None:
        return "⚫ Weather data unavailable, impossible to use bike 🚲"

    temp = weather.get("temp")
    wind = weather.get("wind_speed")
    rain = weather.get("rain")

    score = 0  # lower is better

    # --- Temperature evaluation ---
    if temp < 0:
        score += 3
        temp_msg = "Too cold ❄️"
    elif temp > 35:
        score += 3
        temp_msg = "Too hot 🔥"
    elif 0 <= temp < 10 or 30 < temp <= 35:
        score += 1
        temp_msg = "Temperature is a bit extreme 🌡️"
    else:
        temp_msg = "Temperature is good 👍"

    temp_msg += f" ({temp}°C)"

    # --- Wind direction evaluation ---
    if wind is None:
        wind_msg = "Wind data unavailable 🌬️"
    else:            
        if wind_deg is not None:
            effect = wind_direction_effect(wind_deg, route_angle)
            if effect == "tailwind":
                score -= 1  # makes biking easier
                wind_msg = "👍 Tailwind"
            elif effect == "headwind":
                score += 1  # makes biking harder
                wind_msg = "<b>👎 Headwind</b>"
            else:
                wind_msg = "👈 Crosswind"
        else:
            wind_msg = "💨 Wind"

        if wind > 25:
            score += 3
        elif 15 < wind <= 25:
            score += 2
        elif 5 < wind <= 15:
            score += 1

        wind_msg += f" ({wind} m/s)"

    # --- Rain evaluation ---
    if rain:
        score += 2
        rain_msg = "🌧️ Rainy, <b>take rain gear ☔</b>"
    else:
        rain_msg = "☀️ No rain"

    # --- Overall emoji based on score ---
    if score <= 0:
        emoji = "🟢"
    elif 1 <= score <= 2:
        emoji = "🟡"
    elif 3 <= score <= 4:
        emoji = "🟠"
    elif 5 <= score <= 6:
        emoji = "🔴"
    else:  # score >= 7
        emoji = "⚫"

    return f"{emoji} {temp_msg} {wind_msg} {rain_msg}"
