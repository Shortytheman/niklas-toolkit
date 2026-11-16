#!/usr/bin/env python3
"""Danish public holidays, computed offline from the date of Easter (no network).

    python holidays_dk.py              the next holidays from today
    python holidays_dk.py 2027         a whole year
    python holidays_dk.py --workdays 2026-12-01 2026-12-31    count working days between two dates

Official holidays (helligdage) are marked; common days off that are not official (Christmas Eve, New Year's
Eve, Constitution Day) are listed as "customary" because whether you have them off depends on your agreement.
Store Bededag (Great Prayer Day) is a holiday only up to 2023; it was abolished from 2024.

Exit codes: 0 ok, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402


def easter(year: int) -> date:
    """Gregorian Easter Sunday (Anonymous Gregorian algorithm / Meeus-Jones-Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def holidays(year: int) -> list[tuple[date, str, bool]]:
    """(date, Danish name / English name, official) sorted by date."""
    e = easter(year)
    days = [
        (date(year, 1, 1), "Nytårsdag / New Year's Day", True),
        (e - timedelta(days=3), "Skærtorsdag / Maundy Thursday", True),
        (e - timedelta(days=2), "Langfredag / Good Friday", True),
        (e, "Påskedag / Easter Sunday", True),
        (e + timedelta(days=1), "2. påskedag / Easter Monday", True),
        (e + timedelta(days=39), "Kristi himmelfartsdag / Ascension Day", True),
        (e + timedelta(days=49), "Pinsedag / Whit Sunday", True),
        (e + timedelta(days=50), "2. pinsedag / Whit Monday", True),
        (date(year, 6, 5), "Grundlovsdag / Constitution Day", False),
        (date(year, 12, 24), "Juleaftensdag / Christmas Eve", False),
        (date(year, 12, 25), "Juledag / Christmas Day", True),
        (date(year, 12, 26), "2. juledag / Boxing Day", True),
        (date(year, 12, 31), "Nytårsaftensdag / New Year's Eve", False),
    ]
    if year <= 2023:
        days.append((e + timedelta(days=26), "Store bededag / Great Prayer Day", True))
    return sorted(days)


def upcoming(start: date, count: int = 5) -> list[tuple[date, str, bool]]:
    out = [h for y in (start.year, start.year + 1) for h in holidays(y) if h[0] >= start]
    return out[:count]


def workdays(start: date, end: date, customary: bool = False) -> int:
    """Weekdays from start to end inclusive that are not official holidays (and not customary days off when
    `customary` is True)."""
    off = {d for y in range(start.year, end.year + 1) for d, _, official in holidays(y) if official or customary}
    n, day = 0, start
    while day <= end:
        if day.weekday() < 5 and day not in off:
            n += 1
        day += timedelta(days=1)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Danish public holidays, computed offline.")
    ap.add_argument("year", nargs="?", type=int, help="list a whole year")
    ap.add_argument("--workdays", nargs=2, metavar=("FROM", "TO"), help="count working days (YYYY-MM-DD)")
    ap.add_argument("--next", type=int, default=5, help="how many upcoming holidays (default 5)")
    a = ap.parse_args(argv)
    netlib.force_utf8_output()

    if a.workdays:
        try:
            start, end = (date.fromisoformat(x) for x in a.workdays)
        except ValueError:
            print("ERROR: dates must be YYYY-MM-DD", file=sys.stderr)
            return 2
        print(f"{workdays(start, end)} working days from {start} to {end} "
              f"({workdays(start, end, customary=True)} if Christmas Eve, New Year's Eve and Constitution Day "
              f"are also off)")
        return 0
    rows = holidays(a.year) if a.year else upcoming(date.today(), a.next)
    today = date.today()
    for d, name, official in rows:
        when = "today" if d == today else f"in {(d - today).days} days" if d > today else ""
        print(f"  {d}  {d.strftime('%a')}  {name}{'' if official else '  (customary, not official)'}"
              f"{'  ' + when if when and not a.year else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
