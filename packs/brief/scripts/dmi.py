#!/usr/bin/env python3
"""Measured weather right now from the nearest DMI station (Danish Meteorological Institute). No API key.

    python dmi.py                     nearest station to the configured location
    python dmi.py Aarhus              nearest station to a place in Denmark
    python dmi.py --station 06180     a station by id

weather.py gives forecasts (a model); this gives what a real station measured in the last hour. DMI open data
is free to use with credit to DMI (CC BY 4.0). Exit codes: 0 ok, 2 no station or no connection.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from common import SetupError, fmt_time, run_main  # noqa: E402

API = "https://opendataapi.dmi.dk/v2/metObs/collections"
ATTRIBUTION = "Data: DMI, Danish Meteorological Institute (CC BY 4.0)"
SHOW = [("temp_dry", "temperature", "°C"), ("humidity", "humidity", "%"), ("wind_speed", "wind", "m/s"),
        ("wind_max", "gusts", "m/s"), ("precip_past1h", "rain last hour", "mm"), ("pressure_at_sea", "pressure", "hPa"),
        ("visibility", "visibility", "m"), ("cloud_cover", "cloud cover", "%"), ("sun_last1h_glob", "sunshine last hour", "min")]


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def stations() -> list[dict]:
    """Active stations, one entry per id (the list repeats a station for each validity period)."""
    data = netlib.get_json(f"{API}/station/items", params={"status": "Active", "limit": 10000}, ttl=7 * 86400,
                           source="DMI", timeout=60)
    best: dict[str, dict] = {}
    for f in data.get("features", []):
        p = f.get("properties", {})
        coords = (f.get("geometry") or {}).get("coordinates")
        if not coords or p.get("validTo"):
            continue
        best[p["stationId"]] = {"id": p["stationId"], "name": p.get("name", "?"), "lon": coords[0], "lat": coords[1],
                                "params": set(p.get("parameterId") or [])}
    return list(best.values())


FULL = {"temp_dry", "wind_speed", "precip_past1h"}
FULL_DETOUR_KM = 20  # accept a station this much farther away if it measures wind and rain too


def nearest(lat: float, lon: float) -> tuple[dict, float]:
    """The nearest station measuring temperature; a full station (temperature, wind, rain) is preferred when it
    is at most FULL_DETOUR_KM farther away, because many close stations measure only temperature."""
    all_st = stations()
    temp = [s for s in all_st if "temp_dry" in s["params"]]
    if not temp:
        raise SetupError("DMI returned no active stations")
    dist = lambda s: distance_km(lat, lon, s["lat"], s["lon"])  # noqa: E731
    closest = min(temp, key=dist)
    full = [s for s in all_st if FULL <= s["params"]]
    if full:
        best_full = min(full, key=dist)
        if dist(best_full) <= dist(closest) + FULL_DETOUR_KM:
            return best_full, dist(best_full)
    return closest, dist(closest)


def fmt_value(key: str, value) -> str:
    if not isinstance(value, (int, float)):
        return str(value)
    decimals = 0 if key in ("humidity", "pressure_at_sea", "visibility", "cloud_cover", "sun_last1h_glob") else 1
    return f"{value:.{decimals}f}"


def latest(station_id: str) -> dict[str, tuple[float, str]]:
    """parameter -> (value, observed time) for the newest observation of each parameter in the last hour."""
    data = netlib.get_json(f"{API}/observation/items", ttl=300, source="DMI",
                           params={"stationId": station_id, "period": "latest-hour", "limit": 1000})
    out: dict[str, tuple[float, str]] = {}
    for f in data.get("features", []):
        p = f.get("properties", {})
        key, when = p.get("parameterId"), p.get("observed", "")
        if key and (key not in out or when > out[key][1]):
            out[key] = (p.get("value"), when)
    return out


def summary(place: str | None = None, station_id: str | None = None) -> list[str]:
    if station_id:
        match = [s for s in stations() if s["id"] == station_id]
        if not match:
            raise SetupError(f"no active DMI station {station_id}")
        station, dist = match[0], None
    else:
        import weather  # reuse the configured location and the place-name lookup
        name, lat, lon = weather.locate(place)
        station, dist = nearest(lat, lon)
        if dist > 60:
            raise SetupError(f"the nearest DMI station is {dist:.0f} km from {name}; DMI covers Denmark, Greenland "
                             f"and the Faroe Islands")
    obs = latest(station["id"])
    if not obs:
        return [f"DMI {station['name']} ({station['id']}): no observations in the last hour"]
    parts = [f"{label} {fmt_value(k, obs[k][0])}{'' if unit in ('°C', '%') else ' '}{unit}"
             for k, label, unit in SHOW if k in obs]
    newest = max(t for _, t in obs.values())
    where = f", {dist:.0f} km away" if dist is not None else ""
    return [f"DMI {station['name']} ({station['id']}{where}), measured {fmt_time(newest)}:", "  " + ", ".join(parts)]


def main() -> int:
    ap = argparse.ArgumentParser(description="Measured weather from the nearest DMI station.")
    ap.add_argument("place", nargs="*", help="place in Denmark (default: config location)")
    ap.add_argument("--station", help="DMI station id, e.g. 06180")
    a = ap.parse_args()
    for line in summary(" ".join(a.place) or None, a.station):
        print(line)
    print(ATTRIBUTION)
    return 0


if __name__ == "__main__":
    run_main(main)
