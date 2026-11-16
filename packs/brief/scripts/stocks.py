#!/usr/bin/env python3
"""Stock and ETF quotes and price history, with your own free API keys. Information only.

    python stocks.py AAPL MSFT                 quotes
    python stocks.py                           the watchlist (config watchlist.stocks)
    python stocks.py --history AAPL --days 180

Providers, tried in order (config "stocks": {"providers": [...]}, default finnhub, tiingo, yahoo):
    finnhub  quotes; free key at finnhub.io (60 calls/min, personal use). Key: FINNHUB_API_KEY
    tiingo   end-of-day prices and history; free key at tiingo.com (1,000 calls/day, internal use).
             Key: TIINGO_API_KEY
    yahoo    unofficial Yahoo Finance chart endpoint; covers Nordic tickers like NOVO-B.CO. Off unless config
             "stocks": {"allow_unofficial_yahoo": true}: it has no official API or terms for this use, is
             heavily rate limited and can stop working at any time.

Keys go in the environment or config.json "keys". They are your own: free tiers are for personal use, so the
toolkit never ships or shares one. Exit codes: 0 ok, 1 some symbols had no data, 2 no provider set up.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from common import (DISCLAIMER, SetupError, describe, fmt_money, fmt_pct, fmt_time, run_main,  # noqa: E402
                    settings, sparkline)

SETUP_HELP = ("no stock data source is set up. Get a free personal key at https://finnhub.io (quotes) or "
              "https://www.tiingo.com (history), and put it in the environment or in config.json under "
              '"keys": {"FINNHUB_API_KEY": "..."} or {"TIINGO_API_KEY": "..."}. For Nordic tickers (NOVO-B.CO) '
              'you can opt in to the unofficial Yahoo source: "stocks": {"allow_unofficial_yahoo": true}. '
              "Config file: " + str(netlib.config_path()))


class NoData(Exception):
    pass


def providers() -> list[str]:
    cfg = settings().get("stocks", {})
    order = cfg.get("providers", ["finnhub", "tiingo", "yahoo"])
    out = []
    for p in order:
        if p == "finnhub" and netlib.get_key("FINNHUB_API_KEY"):
            out.append(p)
        elif p == "tiingo" and netlib.get_key("TIINGO_API_KEY"):
            out.append(p)
        elif p == "yahoo" and cfg.get("allow_unofficial_yahoo"):
            out.append(p)
    return out


# ---------------------------------------------------------------- providers: quote -> dict

def finnhub_quote(sym: str) -> dict:
    d = netlib.get_json("https://finnhub.io/api/v1/quote", ttl=60, source="Finnhub",
                        params={"symbol": sym, "token": netlib.get_key("FINNHUB_API_KEY")})
    if not d or not d.get("c"):
        raise NoData("Finnhub has no quote for this symbol (the free plan covers mainly US listings)")
    return {"price": d["c"], "change_pct": d.get("dp"), "prev_close": d.get("pc"), "time": d.get("t"),
            "currency": "", "source": "Finnhub"}


def tiingo_series(sym: str, days: int) -> tuple[list[tuple[str, float]], str]:
    start = (date.today() - timedelta(days=days)).isoformat()
    rows = netlib.get_json(f"https://api.tiingo.com/tiingo/daily/{sym.lower()}/prices", ttl=3600, source="Tiingo",
                           params={"startDate": start, "token": netlib.get_key("TIINGO_API_KEY")})
    if not isinstance(rows, list) or not rows:
        raise NoData("Tiingo has no prices for this symbol")
    return [(r["date"][:10], float(r.get("adjClose") or r["close"])) for r in rows], "USD"


def tiingo_quote(sym: str) -> dict:
    series, cur = tiingo_series(sym, 10)
    last_day, last = series[-1]
    prev = series[-2][1] if len(series) > 1 else None
    return {"price": last, "change_pct": (last / prev - 1) * 100 if prev else None, "prev_close": prev,
            "time": last_day, "currency": cur, "source": "Tiingo (end of day)"}


def yahoo_chart(sym: str, rng: str) -> dict:
    d = netlib.get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", ttl=300,
                        source="Yahoo (unofficial)", params={"range": rng, "interval": "1d"})
    result = ((d.get("chart") or {}).get("result") or [None])[0]
    if not result:
        err = ((d.get("chart") or {}).get("error") or {}).get("description", "no data")
        raise NoData(f"Yahoo: {err}")
    return result


def yahoo_quote(sym: str) -> dict:
    chart = yahoo_chart(sym, "5d")
    meta = chart["meta"]
    price = meta.get("regularMarketPrice")
    # chartPreviousClose is the close before the whole 5-day range, not the previous trading day: use the
    # second-to-last daily close (the last bar is the current or latest session).
    closes = [c for c in ((chart.get("indicators", {}).get("quote") or [{}])[0].get("close") or []) if c is not None]
    prev = closes[-2] if len(closes) >= 2 else meta.get("previousClose")
    return {"price": price, "change_pct": (price / prev - 1) * 100 if price and prev else None, "prev_close": prev,
            "time": meta.get("regularMarketTime"), "currency": meta.get("currency", ""),
            "source": f"Yahoo, unofficial ({meta.get('exchangeName', '')})"}


def yahoo_series(sym: str, days: int) -> tuple[list[tuple[str, float]], str]:
    rng = "1mo" if days <= 31 else "3mo" if days <= 92 else "6mo" if days <= 183 else "1y" if days <= 366 \
        else "2y" if days <= 731 else "5y"
    r = yahoo_chart(sym, rng)
    closes = (r.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose") or \
        r["indicators"]["quote"][0]["close"]
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    series = [(fmt_time(t)[:10], c) for t, c in zip(r.get("timestamp", []), closes) if c is not None]
    return [s for s in series if s[0] >= cutoff], r["meta"].get("currency", "")


QUOTES = {"finnhub": finnhub_quote, "tiingo": tiingo_quote, "yahoo": yahoo_quote}
SERIES = {"tiingo": tiingo_series, "yahoo": yahoo_series}


def quote(sym: str) -> dict:
    """First provider that knows the symbol. Raises SetupError when none is set up, NoData when none knows it."""
    order = providers()
    if not order:
        raise SetupError(SETUP_HELP)
    reasons = []
    for p in order:
        try:
            return QUOTES[p](sym)
        except (NoData, netlib.NetError, KeyError, TypeError, ValueError) as e:
            reasons.append(f"{p}: {e}")
    raise NoData("; ".join(reasons))


def series(sym: str, days: int) -> tuple[list[tuple[str, float]], str, str]:
    order = [p for p in providers() if p in SERIES]
    if not order:
        raise SetupError("price history needs Tiingo (TIINGO_API_KEY) or the opt-in Yahoo source. " + SETUP_HELP)
    reasons = []
    for p in order:
        try:
            data, cur = SERIES[p](sym, days)
            return data, cur, p
        except (NoData, netlib.NetError, KeyError, TypeError, ValueError) as e:
            reasons.append(f"{p}: {e}")
    raise NoData("; ".join(reasons))


def main() -> int:
    ap = argparse.ArgumentParser(description="Stock quotes and history (bring your own free API key).")
    ap.add_argument("symbols", nargs="*", help="tickers, e.g. AAPL or NOVO-B.CO (default: watchlist)")
    ap.add_argument("--history", metavar="SYMBOL", help="price history for one symbol")
    ap.add_argument("--days", type=int, default=90, help="days of history (default 90)")
    a = ap.parse_args()

    if a.history:
        try:
            data, cur, provider = series(a.history.upper(), a.days)
        except NoData as e:
            print(f"{a.history.upper()}: no data ({e})")
            return 1
        closes = [c for _, c in data]
        st = describe(closes)
        print(f"{a.history.upper()} {cur}, {data[0][0]} to {data[-1][0]} ({len(data)} trading days, adjusted closes)")
        print(f"  {sparkline(closes)}")
        print(f"  first {fmt_money(st['first'], cur)}  last {fmt_money(st['last'], cur)}  "
              f"change {fmt_pct(st.get('change_pct'))}  low {fmt_money(st['low'], cur)}  high {fmt_money(st['high'], cur)}")
        print(f"  largest fall from a high {fmt_pct(st['max_drawdown_pct'])}  "
              f"volatility (annualized) {fmt_pct(st.get('volatility_annual_pct'), signed=False)}")
        print(f"Source: {provider}. Past prices say nothing certain about future ones. {DISCLAIMER}")
        return 0

    symbols = [s.upper() for s in (a.symbols or settings().get("watchlist", {}).get("stocks", []))]
    if not symbols:
        raise SetupError('no symbols given and no watchlist; add "watchlist": {"stocks": ["AAPL"]} to '
                         + str(netlib.config_path()))
    missing = 0
    sources = set()
    for sym in symbols:
        try:
            q = quote(sym)
        except NoData as e:
            print(f"  {sym:<10} no data ({e})")
            missing += 1
            continue
        sources.add(q["source"])
        print(f"  {sym:<10} {fmt_money(q['price'], q['currency']):>16}   {fmt_pct(q.get('change_pct')):>8} "
              f"vs previous close   ({fmt_time(q.get('time'))})")
    if sources:
        print(f"Source: {', '.join(sorted(sources))}. Free data can be delayed 15 minutes or more. {DISCLAIMER}")
    return 1 if missing else 0


if __name__ == "__main__":
    run_main(main)
