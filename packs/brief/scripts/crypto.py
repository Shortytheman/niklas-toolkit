#!/usr/bin/env python3
"""Crypto prices: CoinGecko (keyless, or a free Demo key), with Kraken public data as fallback.

    python crypto.py                     the watchlist (config watchlist.crypto) in the base currency
    python crypto.py btc eth sol         these coins
    python crypto.py --history btc --days 90

A free CoinGecko Demo key raises the limit from about 5 to 100 calls a minute: put it in config.json
keys.COINGECKO_DEMO_KEY or the environment. Prices are aggregated across exchanges and refreshed every minute or
so; they are not exchange quotes.

Exit codes: 0 ok, 2 unknown coin or no source reachable.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from common import (DISCLAIMER, SetupError, base_currency, describe, fmt_money, fmt_pct, fmt_time,  # noqa: E402
                    run_main, settings, sparkline)

COINGECKO = "https://api.coingecko.com/api/v3"
KRAKEN = "https://api.kraken.com/0/public"
# Common tickers -> CoinGecko ids; anything else is looked up with /search.
IDS = {"btc": "bitcoin", "eth": "ethereum", "sol": "solana", "ada": "cardano", "xrp": "ripple",
       "doge": "dogecoin", "ltc": "litecoin", "dot": "polkadot", "bnb": "binancecoin", "usdt": "tether",
       "usdc": "usd-coin", "avax": "avalanche-2", "link": "chainlink", "matic": "matic-network",
       "pol": "polygon-ecosystem-token", "trx": "tron", "xlm": "stellar", "atom": "cosmos", "xmr": "monero"}
KRAKEN_PAIRS = {"bitcoin": "XBT", "ethereum": "ETH", "solana": "SOL", "cardano": "ADA", "ripple": "XRP",
                "dogecoin": "XDG", "litecoin": "LTC", "polkadot": "DOT"}


def _headers() -> dict:
    key = netlib.get_key("COINGECKO_DEMO_KEY")
    return {"x-cg-demo-api-key": key} if key else {}


def coin_id(symbol: str) -> str:
    s = symbol.lower()
    if s in IDS:
        return IDS[s]
    data = netlib.get_json(f"{COINGECKO}/search", params={"query": s}, headers=_headers(), ttl=7 * 86400,
                           source="CoinGecko")
    coins = data.get("coins", [])
    exact = [c for c in coins if c.get("symbol", "").lower() == s or c.get("id") == s]
    if not (exact or coins):
        raise SetupError(f"no coin called {symbol} on CoinGecko")
    return (exact or coins)[0]["id"]


def prices(ids: list[str], vs: str) -> tuple[dict, str]:
    """{id: {price, change_24h, updated}} and the source name."""
    try:
        data = netlib.get_json(f"{COINGECKO}/simple/price", headers=_headers(), ttl=60, source="CoinGecko", params={
            "ids": ",".join(ids), "vs_currencies": vs.lower(), "include_24hr_change": "true",
            "include_last_updated_at": "true"})
        out = {i: {"price": d.get(vs.lower()), "change_24h": d.get(f"{vs.lower()}_24h_change"),
                   "updated": d.get("last_updated_at")} for i, d in data.items()}
        return out, "CoinGecko"
    except netlib.NetError as first:
        out = kraken_prices(ids, vs)
        if not out:
            raise first
        return out, "Kraken (fallback)"


def kraken_prices(ids: list[str], vs: str) -> dict:
    """Fallback for the major coins. Kraken quotes in USD and EUR; other currencies go through fx.py."""
    quote = vs.upper() if vs.upper() in ("USD", "EUR") else "EUR"
    out = {}
    for i in ids:
        base = KRAKEN_PAIRS.get(i)
        if not base:
            continue
        try:
            data = netlib.get_json(f"{KRAKEN}/Ticker", params={"pair": f"{base}{quote}"}, ttl=60, source="Kraken")
        except netlib.NetError:
            continue
        result = next(iter((data.get("result") or {}).values()), None)
        if not result:
            continue
        last, opening = float(result["c"][0]), float(result["o"])
        price = last
        if quote != vs.upper():
            from fx import convert
            price = convert(last, quote, vs)[0]
        out[i] = {"price": price, "change_24h": (last / opening - 1) * 100 if opening else None, "updated": None}
    return out


def history(cid: str, vs: str, days: int) -> list[tuple[float, float]]:
    data = netlib.get_json(f"{COINGECKO}/coins/{cid}/market_chart", headers=_headers(), ttl=1800,
                           source="CoinGecko", params={"vs_currency": vs.lower(), "days": days,
                                                       "interval": "daily" if days > 2 else None})
    return [(ts / 1000, price) for ts, price in data.get("prices", [])]


def main() -> int:
    ap = argparse.ArgumentParser(description="Crypto prices from CoinGecko (fallback: Kraken).")
    ap.add_argument("coins", nargs="*", help="tickers or CoinGecko ids (default: watchlist)")
    ap.add_argument("--vs", default=None, help="quote currency (default: config currency, DKK)")
    ap.add_argument("--history", metavar="COIN", help="price history for one coin")
    ap.add_argument("--days", type=int, default=30, help="days of history (default 30)")
    a = ap.parse_args()
    vs = (a.vs or base_currency()).upper()

    if a.history:
        cid = coin_id(a.history)
        series = history(cid, vs, a.days)
        if len(series) < 2:
            raise SetupError(f"no history for {a.history}")
        closes = [p for _, p in series]
        st = describe(closes, periods_per_year=365)
        print(f"{cid} in {vs}, last {a.days} days ({fmt_time(series[0][0])} to {fmt_time(series[-1][0])})")
        print(f"  {sparkline(closes)}")
        print(f"  first {fmt_money(st['first'], vs)}  last {fmt_money(st['last'], vs)}  "
              f"change {fmt_pct(st['change_pct'])}  low {fmt_money(st['low'], vs)}  high {fmt_money(st['high'], vs)}")
        print(f"  largest fall from a high {fmt_pct(st['max_drawdown_pct'])}  "
              f"volatility (annualized) {fmt_pct(st.get('volatility_annual_pct'), signed=False)}")
        print(f"Source: CoinGecko. {DISCLAIMER}")
        return 0

    symbols = a.coins or settings().get("watchlist", {}).get("crypto", ["btc", "eth"])
    ids = {s: coin_id(s) for s in symbols}
    data, source = prices(sorted(set(ids.values())), vs)
    print(f"Crypto in {vs}:")
    for sym, cid in ids.items():
        d = data.get(cid)
        if not d or d.get("price") is None:
            print(f"  {sym.upper():<6} no price from {source}")
            continue
        print(f"  {sym.upper():<6} {fmt_money(d['price'], vs):>18}   24h {fmt_pct(d.get('change_24h')):>8}   "
              f"({fmt_time(d.get('updated'))})")
    print(f"Source: {source}. {DISCLAIMER}")
    return 0


if __name__ == "__main__":
    run_main(main)
