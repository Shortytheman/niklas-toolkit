#!/usr/bin/env python3
"""US and international economic data from FRED (Federal Reserve Bank of St. Louis), with your own free key.

    python fred.py DFF                       a series: latest values and a summary
    python fred.py CPIAUCSL --last 24        more observations
    python fred.py search mortgage rate      find series ids
    python fred.py rates                     a few common series (shortcut, see PRESETS)

Key: free at https://fred.stlouisfed.org/docs/api/api_key.html, put in the environment or config.json
keys.FRED_API_KEY. FRED's terms require the notice the output prints; some series belong to third parties whose
own terms apply beyond personal use (FRED marks them as copyrighted).

Information only. Exit codes: 0 ok, 2 no key, unknown series or network problem.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from common import SetupError, run_main, sparkline  # noqa: E402

API = "https://api.stlouisfed.org/fred"
NOTICE = "This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis."
PRESETS = {"rates": ["DFF", "DGS10", "MORTGAGE30US"], "inflation": ["CPIAUCSL"], "jobs": ["UNRATE", "PAYEMS"]}


def key() -> str:
    k = netlib.get_key("FRED_API_KEY")
    if not k:
        raise SetupError("FRED needs a free API key: https://fred.stlouisfed.org/docs/api/api_key.html. Put it in "
                         f'the environment as FRED_API_KEY or in {netlib.config_path()} under "keys"')
    return k


def call(path: str, **params) -> dict:
    try:
        return netlib.get_json(f"{API}/{path}", ttl=3600, source="FRED",
                               params={"api_key": key(), "file_type": "json", **params})
    except netlib.NetError as e:
        if e.status == 400:
            raise SetupError(f"FRED refused the request ({e}); check the series id") from e
        raise


def series(series_id: str, last: int) -> tuple[dict, list[tuple[str, float | None]]]:
    info = (call("series", series_id=series_id).get("seriess") or [{}])[0]
    obs = call("series/observations", series_id=series_id, sort_order="desc", limit=last).get("observations", [])
    values = [(o["date"], None if o["value"] in (".", "") else float(o["value"])) for o in reversed(obs)]
    return info, values


def show(series_id: str, last: int) -> None:
    info, values = series(series_id, last)
    print(f"{series_id}: {info.get('title', '?')} ({info.get('units_short') or info.get('units', '')}, "
          f"{info.get('frequency', '')}, updated {str(info.get('last_updated', ''))[:10]})")
    if "copyright" in (info.get("notes") or "").lower():
        print("  Note: FRED marks this series as third-party copyrighted; its owner's terms apply beyond personal use.")
    known = [v for _, v in values if v is not None]
    for date, v in values[-8:]:
        print(f"  {date}  {'n/a' if v is None else f'{v:,.2f}'}")
    if len(known) >= 3:
        change = known[-1] - known[0]
        print(f"  {sparkline(known)}  first {known[0]:,.2f}, last {known[-1]:,.2f}, change {change:+,.2f} over "
              f"{len(values)} observations")


def main() -> int:
    ap = argparse.ArgumentParser(description="Economic data from FRED (bring your own free key).")
    ap.add_argument("command", help="a series id (DFF, CPIAUCSL ...), a shortcut (" + ", ".join(PRESETS) + "), or search")
    ap.add_argument("words", nargs="*", help="search words")
    ap.add_argument("--last", type=int, default=12, help="observations to fetch (default 12)")
    a = ap.parse_args()
    if a.command == "search":
        if not a.words:
            raise SetupError("give search words, e.g. fred.py search mortgage rate")
        found = call("series/search", search_text=" ".join(a.words), limit=15, order_by="popularity",
                     sort_order="desc").get("seriess", [])
        for s in found:
            print(f"  {s['id']:<14} {s['title'][:80]}  ({s.get('frequency_short', '')}, {s.get('units_short', '')})")
        if not found:
            print("  no series found")
    else:
        for sid in PRESETS.get(a.command.lower(), [a.command.upper()]):
            show(sid, a.last)
            print()
    print(NOTICE)
    return 0


if __name__ == "__main__":
    run_main(main)
