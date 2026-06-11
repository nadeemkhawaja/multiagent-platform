"""Current weather via wttr.in (no API key) — used by Morning Brief."""
from .registry import tool
from .web import fetch_json


@tool("weather.current", "Current conditions for a city (wttr.in, no API key needed).")
async def current_weather(city: str) -> dict:
    j = await fetch_json(f"https://wttr.in/{city}?format=j1", timeout=10.0)
    cur = j["current_condition"][0]
    temp_f = int(cur["temp_F"])
    feels_f = int(cur["FeelsLikeF"])
    desc = cur["weatherDesc"][0]["value"]
    humidity = cur["humidity"]
    wind_mph = cur["windspeedMiles"]
    return {
        "temp_f": temp_f, "feels_f": feels_f,
        "desc": desc, "humidity": humidity, "wind_mph": wind_mph,
        "summary": f"{desc}, {temp_f}°F (feels {feels_f}°F), humidity {humidity}%, wind {wind_mph} mph",
    }
