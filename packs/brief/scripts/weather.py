#!/usr/bin/env python3
"""Weather now and the next days, from Open-Meteo (no API key).

    python weather.py                  the configured location (config "location")
    python weather.py Aarhus           any place name
    python weather.py --days 7

Open-Meteo's free API is for non-commercial use, and its data is CC BY 4.0: the output credits it.
Exit codes: 0 ok, 2 unknown place or no connection.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from common import SetupError, run_main, settings  # noqa: E402

FORECAST = "https://api.open-meteo.com/v1/forecast"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC BY 4.0)"

# WMO weather interpretation codes, as used by Open-Meteo
WMO = {0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "rime fog",
       51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
       61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain",
       71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers",
       82: "heavy showers", 85: "snow showers", 86: "heavy snow showers", 95: "thunderstorm",
       96: "thunderstorm with hail", 99: "thunderstorm with heavy hail"}


def locate(place: str | None) -> tuple[str, float, float]:
    loc = settings().get("location") or {}
    if not place and loc.get("lat") is not None:
        return loc.get("name", "configured location"), float(loc["lat"]), float(loc["lon"])
    name = place or loc.get("name") or "Copenhagen"
    data = netlib.get_json(GEOCODE, params={"name": name, "count": 1, "language": "en"}, ttl=30 * 86400,
                           source="Open-Meteo geocoding")
    hits = data.get("results") or []
    if not hits:
        raise SetupError(f"no place called {name!r}")
    h = hits[0]
    label = ", ".join(x for x in (h.get("name"), h.get("admin1"), h.get("country_code")) if x)
    return label, h["latitude"], h["longitude"]


def forecast(lat: float, lon: float, days: int) -> dict:
    return netlib.get_json(FORECAST, ttl=900, source="Open-Meteo", params={
        "latitude": round(lat, 4), "longitude": round(lon, 4), "timezone": "auto", "forecast_days": days,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_gusts_10m,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                 "precipitation_probability_max,wind_speed_10m_max,sunrise,sunset",
        "wind_speed_unit": "ms"})


def summary(place: str | None = None, days: int = 3) -> list[str]:
    name, lat, lon = locate(place)
    d = forecast(lat, lon, days)
    c = d.get("current", {})
    lines = [f"{name}: {c.get('temperature_2m')}°C (feels {c.get('apparent_temperature')}°C), "
             f"{WMO.get(c.get('weather_code'), '?')}, wind {c.get('wind_speed_10m')} m/s "
             f"(gusts {c.get('wind_gusts_10m')})"]
    daily = d.get("daily", {})
    for i, day in enumerate(daily.get("time", [])):
        temps = f"{daily['temperature_2m_min'][i]}..{daily['temperature_2m_max'][i]}°C"
        lines.append(f"  {day}  {temps:<14}"
                     f"{WMO.get(daily['weather_code'][i], '?'):<16} rain {daily['precipitation_sum'][i]} mm "
                     f"({daily['precipitation_probability_max'][i]}%)  wind up to {daily['wind_speed_10m_max'][i]} m/s"
                     + (f"  sun {daily['sunrise'][i][-5:]}-{daily['sunset'][i][-5:]}" if i == 0 else ""))
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description="Weather from Open-Meteo.")
    ap.add_argument("place", nargs="*", help="place name (default: config location)")
    ap.add_argument("--days", type=int, default=3, help="forecast days, 1-16 (default 3)")
    a = ap.parse_args()
    for line in summary(" ".join(a.place) or None, max(1, min(16, a.days))):
        print(line)
    print(ATTRIBUTION)
    return 0


if __name__ == "__main__":
    run_main(main)
