"""Helpers shared by the brief pack's scripts: settings, formatting, descriptive statistics.

Settings come from the user's config file (python brief_config.py --init writes a commented template):
    %LOCALAPPDATA%/niklas-toolkit/config.json on Windows, ~/.config/niklas-toolkit/config.json elsewhere
"""
from __future__ import annotations

import math
import statistics
import sys
from datetime import date, datetime, timezone

import netlib

DISCLAIMER = "Information only, not investment advice. Prices can be delayed; check the source before acting."


class SetupError(Exception):
    """Missing key or setting; the message tells the user what to add. Scripts exit 2."""


def settings() -> dict:
    try:
        return netlib.load_config()
    except netlib.NetError as e:
        raise SetupError(str(e)) from e


def base_currency() -> str:
    return str(settings().get("currency", "DKK")).upper()


def fmt_money(value: float | None, currency: str = "", decimals: int | None = None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "n/a"
    if decimals is None:
        decimals = 2 if abs(value) >= 1 or value == 0 else 6 if abs(value) < 0.01 else 4
    text = f"{value:,.{decimals}f}"
    return f"{text} {currency}".strip()


def fmt_pct(value: float | None, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def fmt_time(ts: float | str | None) -> str:
    """A UNIX time or ISO string as local 'YYYY-MM-DD HH:MM'."""
    if ts is None or ts == "":
        return "unknown time"
    if isinstance(ts, (int, float)):
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    else:
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            return str(ts)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M") if (dt.hour or dt.minute) else dt.strftime("%Y-%m-%d")


def describe(closes: list[float], periods_per_year: int = 252) -> dict:
    """Descriptive statistics of a price series (oldest first). No forecasts, no signals."""
    if len(closes) < 2:
        return {"points": len(closes)}
    returns = [b / a - 1 for a, b in zip(closes, closes[1:]) if a]
    peak, max_dd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        max_dd = min(max_dd, c / peak - 1 if peak else 0)
    out = {
        "points": len(closes),
        "first": closes[0], "last": closes[-1],
        "change_pct": (closes[-1] / closes[0] - 1) * 100 if closes[0] else None,
        "low": min(closes), "high": max(closes),
        "max_drawdown_pct": max_dd * 100,
    }
    if len(returns) >= 2:
        out["volatility_annual_pct"] = statistics.stdev(returns) * math.sqrt(periods_per_year) * 100
    return out


def sparkline(values: list[float], width: int = 30) -> str:
    """A tiny text chart of the series."""
    if len(values) < 2:
        return ""
    n = len(values)
    # evenly spaced points that always include the first and the last value
    sample = values if n <= width else [values[round(i * (n - 1) / (width - 1))] for i in range(width)]
    lo, hi = min(sample), max(sample)
    bars = "▁▂▃▄▅▆▇█"
    if hi == lo:
        return bars[3] * len(sample)
    return "".join(bars[int((v - lo) / (hi - lo) * (len(bars) - 1))] for v in sample)


def run_main(main) -> None:
    """Run a script's main() with the pack's exit codes: SetupError -> 2, NetError -> 2."""
    netlib.force_utf8_output()
    try:
        sys.exit(main())
    except SetupError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except netlib.NetError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)


def today() -> date:
    return date.today()
