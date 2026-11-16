#!/usr/bin/env python3
"""Exchange rates: ECB euro reference rates, with Frankfurter as fallback. No API key.

    python fx.py 100 USD DKK            convert 100 USD to DKK
    python fx.py USD                    1 USD in the base currency (config "currency", default DKK)
    python fx.py --table                the base currency against the watchlist (config watchlist.fx)
    python fx.py --history EUR DKK --days 90

ECB reference rates are published once per working day around 16:00 CET and are "for information purposes
only": fine for overviews and bookkeeping estimates, not for trading. Cross rates (USD->DKK) go through EUR.

Exit codes: 0 ok, 2 unknown currency or no source reachable.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from common import SetupError, base_currency, describe, fmt_money, fmt_pct, run_main, settings, sparkline  # noqa: E402

ECB_DAILY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
ECB_90D = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"
FRANKFURTER = "https://api.frankfurter.dev/v1"
NS = {"e": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}


def parse_ecb(xml_text: str) -> dict[str, dict[str, float]]:
    """{date: {currency: units per 1 EUR}} with EUR itself = 1."""
    root = ET.fromstring(xml_text)
    out = {}
    for day in root.iter("{%s}Cube" % NS["e"]):
        if "time" in day.attrib:
            rates = {c.attrib["currency"]: float(c.attrib["rate"]) for c in day if "currency" in c.attrib}
            rates["EUR"] = 1.0
            out[day.attrib["time"]] = rates
    return out


def latest_rates() -> tuple[str, dict[str, float], str]:
    """(date, rates per EUR, source name). ECB first, Frankfurter (also ECB-based) as fallback."""
    try:
        days = parse_ecb(netlib.get_text(ECB_DAILY, ttl=3600, source="ECB"))
        day = max(days)
        return day, days[day], "ECB euro reference rates"
    except (netlib.NetError, ET.ParseError, ValueError):
        data = netlib.get_json(f"{FRANKFURTER}/latest", params={"base": "EUR"}, ttl=3600, source="Frankfurter")
        rates = dict(data.get("rates", {}))
        rates["EUR"] = 1.0
        return data.get("date", "?"), rates, "Frankfurter (ECB-based)"


def history(days: int) -> tuple[dict[str, dict[str, float]], str]:
    if days <= 90:
        try:
            return parse_ecb(netlib.get_text(ECB_90D, ttl=3600, source="ECB")), "ECB euro reference rates"
        except (netlib.NetError, ET.ParseError, ValueError):
            pass
    start = (date.today() - timedelta(days=days)).isoformat()
    data = netlib.get_json(f"{FRANKFURTER}/{start}..", params={"base": "EUR"}, ttl=3600, source="Frankfurter")
    out = {}
    for day, rates in data.get("rates", {}).items():
        rates = dict(rates)
        rates["EUR"] = 1.0
        out[day] = rates
    return out, "Frankfurter (ECB-based)"


def cross(rates: dict[str, float], frm: str, to: str) -> float:
    for c in (frm, to):
        if c not in rates:
            raise SetupError(f"unknown currency {c}; known: {', '.join(sorted(rates))}")
    return rates[to] / rates[frm]


def convert(amount: float, frm: str, to: str) -> tuple[float, str, str]:
    """amount in `to`, plus the rate date and source, for other scripts (portfolio, brief)."""
    day, rates, source = latest_rates()
    return amount * cross(rates, frm.upper(), to.upper()), day, source


def main() -> int:
    ap = argparse.ArgumentParser(description="Exchange rates from the ECB (fallback: Frankfurter).")
    ap.add_argument("args", nargs="*", help="[AMOUNT] FROM [TO]")
    ap.add_argument("--table", action="store_true", help="base currency against the watchlist")
    ap.add_argument("--history", nargs=2, metavar=("FROM", "TO"), help="rate history for a pair")
    ap.add_argument("--days", type=int, default=30, help="days of history (default 30)")
    a = ap.parse_args()

    base = base_currency()
    if a.history:
        frm, to = (c.upper() for c in a.history)
        days, source = history(a.days)
        cutoff = (date.today() - timedelta(days=a.days)).isoformat()
        series = [(d, cross(r, frm, to)) for d, r in sorted(days.items()) if d >= cutoff]
        if not series:
            raise SetupError("no rates in that period")
        stats = describe([v for _, v in series])
        print(f"{frm}/{to} over {a.days} days ({series[0][0]} to {series[-1][0]}, {len(series)} rates)")
        print(f"  {sparkline([v for _, v in series])}")
        print(f"  first {stats['first']:.4f}  last {stats['last']:.4f}  change {fmt_pct(stats['change_pct'])}  "
              f"low {stats['low']:.4f}  high {stats['high']:.4f}")
        print(f"Source: {source}. Reference rates, for information only.")
        return 0

    day, rates, source = latest_rates()
    if a.table or not a.args:
        watch = [c.upper() for c in settings().get("watchlist", {}).get("fx", ["EUR", "USD", "GBP", "SEK", "NOK"])]
        print(f"1 unit in {base}, {day}:")
        for c in watch:
            if c != base:
                print(f"  {c:<4} {cross(rates, c, base):>10.4f} {base}")
        print(f"Source: {source}. Reference rates, for information only.")
        return 0

    parts = a.args
    try:
        amount = float(parts[0].replace(",", "."))
        parts = parts[1:]
    except ValueError:
        amount = 1.0
    if not parts:
        raise SetupError("give a currency, e.g. fx.py 100 USD DKK")
    frm = parts[0].upper()
    to = (parts[1] if len(parts) > 1 else base).upper()
    rate = cross(rates, frm, to)
    print(f"{fmt_money(amount, frm)} = {fmt_money(amount * rate, to)}   (1 {frm} = {rate:.6g} {to}, {day})")
    print(f"Source: {source}. Reference rates, for information only.")
    return 0


if __name__ == "__main__":
    run_main(main)
