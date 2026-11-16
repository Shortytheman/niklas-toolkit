#!/usr/bin/env python3
"""A morning brief in one command: weather, next holiday, currencies, crypto, stocks, portfolio, headlines and
new releases, from the user's config. Each section fails on its own: one dead source never sinks the brief.

    python brief.py                       all configured sections
    python brief.py --only weather news   just these

config.json "brief": {"sections": [...]} sets the default order. Sections:
    weather, holidays, fx, crypto, stocks, portfolio, news, releases,
    observed (measured now at the nearest DMI station), inflation (Danish CPI)
A section with nothing configured (no watchlist, no feeds) is skipped quietly.

Exit codes: 0 brief printed (even if some sections failed), 2 setup problem in the config file itself.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from common import DISCLAIMER, SetupError, base_currency, fmt_money, fmt_pct, fmt_time, run_main, settings  # noqa: E402

DEFAULT_SECTIONS = ["weather", "holidays", "fx", "crypto", "stocks", "portfolio", "news", "releases"]
MARKET_SECTIONS = {"fx", "crypto", "stocks", "portfolio", "inflation"}


def section_weather(cfg: dict) -> list[str]:
    import weather
    lines = weather.summary(None, 2)
    return lines + [f"  ({weather.ATTRIBUTION})"]


def section_holidays(cfg: dict) -> list[str]:
    from holidays_dk import upcoming
    d, name, official = upcoming(date.today(), 1)[0]
    days = (d - date.today()).days
    when = "today" if days == 0 else "tomorrow" if days == 1 else f"in {days} days"
    return [f"Next holiday: {name}, {d} ({when}){'' if official else ', customary'}"]


def section_fx(cfg: dict) -> list[str]:
    import fx
    base = base_currency()
    day, rates, source = fx.latest_rates()
    watch = [c.upper() for c in cfg.get("watchlist", {}).get("fx", ["EUR", "USD"]) if c.upper() != base]
    return [f"{base}: " + "   ".join(f"{c} {fx.cross(rates, c, base):.4f}" for c in watch) + f"   ({source}, {day})"]


def section_crypto(cfg: dict) -> list[str]:
    import crypto
    symbols = cfg.get("watchlist", {}).get("crypto", [])
    if not symbols:
        return []
    base = base_currency()
    ids = {s: crypto.coin_id(s) for s in symbols}
    data, source = crypto.prices(sorted(set(ids.values())), base)
    parts = [f"{s.upper()} {fmt_money(data.get(i, {}).get('price'), base)} ({fmt_pct(data.get(i, {}).get('change_24h'))} 24h)"
             for s, i in ids.items()]
    return ["Crypto: " + "   ".join(parts) + f"   ({source})"]


def section_stocks(cfg: dict) -> list[str]:
    import stocks
    symbols = cfg.get("watchlist", {}).get("stocks", [])
    if not symbols:
        return []
    if not stocks.providers():
        return ["Stocks: no data source set up (see stocks.py for free keys)"]
    lines = []
    for s in symbols:
        try:
            q = stocks.quote(s.upper())
            lines.append(f"  {s.upper():<10} {fmt_money(q['price'], q['currency']):>14} {fmt_pct(q.get('change_pct')):>8}"
                         f"  ({fmt_time(q.get('time'))})")
        except stocks.NoData as e:
            lines.append(f"  {s.upper():<10} no data")
    return ["Stocks (change vs previous close):"] + lines


def section_portfolio(cfg: dict) -> list[str]:
    if not cfg.get("portfolio"):
        return []
    import portfolio
    base = base_currency()
    valued = portfolio.value_rows(portfolio.read_csv(Path(cfg["portfolio"]).expanduser()), base)
    priced = [v for v in valued if v.value is not None]
    total = sum(v.value for v in priced)
    with_cost = [v for v in priced if v.cost is not None and v.row.kind != "cash"]
    gain = sum(v.value - v.cost for v in with_cost)
    missing = len(valued) - len(priced)
    return [f"Portfolio: {fmt_money(total, base)}" + (f", gain/loss {fmt_money(gain, base)}" if with_cost else "")
            + (f"  ({missing} position(s) without a price)" if missing else "")]


def section_news(cfg: dict) -> list[str]:
    import news
    n = int(cfg.get("brief", {}).get("hn", 5))
    lines = [f"Hacker News top {n}:"] + [f"  {s['points']:>4}  {s['title']}  {s['url']}" for s in news.hn_top(n)]
    for feed in cfg.get("feeds", []):
        try:
            entries = news.fetch_feed(feed["url"])[:3]
        except Exception as e:  # noqa: BLE001 - one broken feed must not hide the others
            lines.append(f"{feed.get('name', feed['url'])}: could not read ({e})")
            continue
        lines.append(f"{feed.get('name', feed['url'])}:")
        lines += [f"  {e['title']}  {news.ago(e['date'])}  {e['link']}" for e in entries]
    return lines


def section_releases(cfg: dict) -> list[str]:
    repos = cfg.get("github_releases", [])
    if not repos:
        return []
    import news
    found = [r for r in news.releases(repos, days=7) if not r.get("error")]
    if not found:
        return ["New releases (7 days): none"]
    return ["New releases (7 days):"] + [f"  {r['repo']} {r['title']}  {news.ago(r['date'])}" for r in found]


def section_observed(cfg: dict) -> list[str]:
    import dmi
    return dmi.summary() + [f"  ({dmi.ATTRIBUTION})"]


def section_inflation(cfg: dict) -> list[str]:
    import dk_stats
    table, sel, _, _ = dk_stats.PRESETS["inflation"]
    _, rows = dk_stats.fetch(table, sel, 2)
    values = [(r["TID"], dk_stats.number(r["INDHOLD"])) for r in rows if dk_stats.number(r["INDHOLD"]) is not None]
    if not values:
        return []
    (prev_t, prev), (last_t, last) = (values[-2] if len(values) > 1 else values[-1]), values[-1]
    return [f"Danish inflation: {last:.1f}% in {last_t} (year on year; {prev:.1f}% in {prev_t})  "
            f"({dk_stats.ATTRIBUTION.replace('Source: ', '')})"]


SECTIONS = {"weather": section_weather, "observed": section_observed, "inflation": section_inflation, "holidays": section_holidays, "fx": section_fx, "crypto": section_crypto,
            "stocks": section_stocks, "portfolio": section_portfolio, "news": section_news,
            "releases": section_releases}


def main() -> int:
    ap = argparse.ArgumentParser(description="Morning brief from the configured sources.")
    ap.add_argument("--only", nargs="+", choices=list(SECTIONS), help="just these sections")
    a = ap.parse_args()
    cfg = settings()
    sections = a.only or cfg.get("brief", {}).get("sections", DEFAULT_SECTIONS)
    unknown = [s for s in sections if s not in SECTIONS]
    if unknown:
        raise SetupError(f"unknown brief section(s) {unknown}; choose from {list(SECTIONS)}")

    print(f"Brief for {datetime.now().strftime('%A %d %B %Y, %H:%M')}\n")
    for name in sections:
        try:
            lines = SECTIONS[name](cfg)
        except (netlib.NetError, SetupError, Exception) as e:  # noqa: BLE001 - report and carry on
            lines = [f"{name}: unavailable ({e})"]
        if lines:
            print("\n".join(lines) + "\n")
    if MARKET_SECTIONS & set(sections):
        print(DISCLAIMER)
    return 0


if __name__ == "__main__":
    run_main(main)
