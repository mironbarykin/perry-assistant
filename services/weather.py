from .consts import OPENWEATHER_API_KEY

def get_weather(location: dict, target_dt: datetime.datetime) -> dict:
    """Fetch weather data for a location and time."""
    url = (
        f"https://api.openweathermap.org/data/2.5/forecast?"
        f"lat={location['lat']}&lon={location['lon']}"
        f"&appid={OPENWEATHER_API_KEY}&units=metric"
    )
    data = requests.get(url).json()

    if "list" not in data:
        return {
            "temp": None,
            "wind_speed": None,
            "wind_deg": None,
            "rain": False,
            "desc": f"API error: {data.get('message', 'unknown')}"
        }

    forecasts = data["list"]
    target_ts = int(target_dt.timestamp())
    chosen = min(forecasts, key=lambda f: abs(int(f["dt"]) - target_ts))

    main = chosen["main"]
    wind = chosen["wind"]
    weather_desc = chosen["weather"][0]["description"].lower()

    return {
        "temp": main["temp"],
        "wind_speed": wind["speed"],
        "wind_deg": wind["deg"],
        "rain": "rain" in weather_desc,
        "desc": weather_desc,
    }

def weather_message(weather: dict, route_angle=30) -> str:
    """Evaluate biking conditions and return advice."""
    if not weather or weather.get("temp") is None:
        return "⚫ Weather data unavailable!"

    temp = weather.get("temp")
    wind = weather.get("wind_speed")
    wind_deg = weather.get("wind_deg") if wind_deg is None else wind_deg
    rain = weather.get("rain")

    score = 0

    if temp < 0:
        score += 3
        temp_msg = f"T-{temp}°C ❄️"
    elif temp > 30:
        score += 3
        temp_msg = f"T-{temp}°C 🔥"
    elif 0 <= temp < 10 or 22 < temp <= 30:
        score += 1
        temp_msg = f"T-{temp}°C 🌡️"
    else:
        temp_msg = f"T-{temp}°C 👍"

    if wind is None:
        wind_msg = "No data 💨"
    else:
        diff = None

        if wind_deg is not None:
            blow_to = (wind_deg + 180) % 360
            diff = abs(blow_to - route_angle)
            diff = min(diff, 360 - diff)
            if diff <= 45:
                wind_msg = f"Tailwind ({wind} m/s) 👍"
                score -= 1
            elif diff >= 135:
                wind_msg = f"<b>Headwind ({wind} m/s) 👎</b>"
                if wind > 12:
                    score += 2
                elif wind > 2:
                    score += 1  
                score += 1
            else:
                if wind > 12:
                    score += 2
                if wind > 5.5:
                    score += 1
                wind_msg = f"Crosswind ({wind} m/s) 💨"
        else:
            if wind > 12:
                score += 2
            if wind > 5.5:
                score += 1
            
            wind_msg = f"Wind ({wind} m/s) 💨"
        
    if rain:
        score += 2
        rain_msg = "🌧️ Rainy, <b>take rain gear ☔</b>"
    else:
        rain_msg = "😎"

    if score <= 0:
        emoji = "🟢"
    elif 1 <= score <= 2:
        emoji = "🟡"
    elif 3 <= score <= 4:
        emoji = "🟠"
    elif 5 <= score <= 6:
        emoji = "🔴"
    else:
        emoji = "⚫"

    return f"{emoji} {temp_msg} {wind_msg} {rain_msg}"
