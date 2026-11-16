#!/usr/bin/env python3
"""Value your own holdings from a CSV: current value, gain or loss, and weight per position, in one currency.

    python portfolio.py [holdings.csv]       (default: config "portfolio")
    python portfolio.py --example out.csv    write an example file to start from

CSV columns (header row required; extra columns are ignored):
    symbol     ticker (AAPL, NOVO-B.CO), coin (btc) or currency for cash (EUR)
    type       stock | crypto | cash
    quantity   number of shares / coins / units of cash
    avg_price  what you paid per unit, in `currency` (leave empty for cash)
    currency   currency of avg_price and of the stock's quote (USD, DKK, ...)

Prices come from stocks.py (your own key or the opt-in Yahoo source), crypto.py (CoinGecko) and fx.py (ECB);
everything is converted to the base currency (config "currency", default DKK). The file never leaves your
machine; only the symbols are sent to the price sources.

This describes what you hold; it does not judge it. Exit codes: 0 ok, 1 some positions had no price, 2 setup.
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crypto  # noqa: E402
import netlib  # noqa: E402
import fx  # noqa: E402
import stocks  # noqa: E402
from common import DISCLAIMER, SetupError, base_currency, fmt_money, fmt_pct, run_main, settings  # noqa: E402

EXAMPLE = """symbol,type,quantity,avg_price,currency
AAPL,stock,10,150.00,USD
NOVO-B.CO,stock,20,400.00,DKK
btc,crypto,0.05,250000,DKK
EUR,cash,1000,,EUR
"""


@dataclass
class Row:
    symbol: str
    kind: str
    quantity: float
    avg_price: float | None
    currency: str


@dataclass
class Valued:
    row: Row
    price: float | None = None        # per unit, in price_currency
    price_currency: str = ""
    value: float | None = None        # in base currency
    cost: float | None = None         # in base currency
    source: str = ""
    error: str = ""


def read_csv(path: Path) -> list[Row]:
    if not path.is_file():
        raise SetupError(f"portfolio file not found: {path}. Create one with: portfolio.py --example {path}")
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        need = {"symbol", "type", "quantity", "currency"}
        if not reader.fieldnames or not need <= {h.strip().lower() for h in reader.fieldnames}:
            raise SetupError(f"{path} needs the columns symbol,type,quantity,avg_price,currency")
        for n, raw in enumerate(reader, start=2):
            r = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            if not r.get("symbol"):
                continue
            try:
                qty = float(r["quantity"].replace(",", "."))
                avg = float(r["avg_price"].replace(",", ".")) if r.get("avg_price") else None
            except ValueError:
                raise SetupError(f"{path}:{n}: quantity and avg_price must be numbers")
            kind = r["type"].lower()
            if kind not in ("stock", "crypto", "cash"):
                raise SetupError(f"{path}:{n}: type must be stock, crypto or cash, not {r['type']!r}")
            rows.append(Row(r["symbol"], kind, qty, avg, r["currency"].upper() or base_currency()))
    return rows


def value_rows(rows: list[Row], base: str) -> list[Valued]:
    _, rates, fx_source = fx.latest_rates()

    def to_base(amount: float, cur: str) -> float:
        return amount * fx.cross(rates, cur, base)

    out = []
    coins = [r for r in rows if r.kind == "crypto"]
    coin_prices: dict = {}
    if coins:
        ids = {r.symbol: crypto.coin_id(r.symbol) for r in coins}
        coin_prices, _ = crypto.prices(sorted(set(ids.values())), base)
    for r in rows:
        v = Valued(r)
        try:
            if r.kind == "cash":
                v.price, v.price_currency, v.source = 1.0, r.currency, "cash"
                v.value = to_base(r.quantity, r.currency)
                v.cost = v.value
            elif r.kind == "crypto":
                p = coin_prices.get(crypto.coin_id(r.symbol), {}).get("price")
                if p is None:
                    raise stocks.NoData("no price from CoinGecko")
                v.price, v.price_currency, v.source = p, base, "CoinGecko"
                v.value = p * r.quantity
            else:
                q = stocks.quote(r.symbol.upper())
                cur = (q.get("currency") or r.currency).upper()
                v.price, v.price_currency, v.source = q["price"], cur, q["source"]
                v.value = to_base(q["price"] * r.quantity, cur)
            if v.cost is None and r.avg_price is not None:
                v.cost = to_base(r.avg_price * r.quantity, r.currency)
        except (stocks.NoData, netlib.NetError) as e:  # this position has no price; the others still count
            v.error = str(e)
        out.append(v)  # a SetupError (no stock source, unknown currency) stops the whole run with its message
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Value a portfolio CSV in one currency (information only).")
    ap.add_argument("file", nargs="?", help="holdings CSV (default: config portfolio)")
    ap.add_argument("--example", metavar="PATH", help="write an example CSV and exit")
    a = ap.parse_args()

    if a.example:
        path = Path(a.example)
        if path.exists():
            raise SetupError(f"{path} exists; not overwriting it")
        path.write_text(EXAMPLE, encoding="utf-8")
        print(f"Wrote {path}. Edit it, then: portfolio.py {path}")
        return 0
    file = a.file or settings().get("portfolio")
    if not file:
        raise SetupError('give a CSV file, or set "portfolio": "<path>" in config.json (portfolio.py --example x.csv)')
    base = base_currency()
    rows = read_csv(Path(file).expanduser())
    valued = value_rows(rows, base)

    priced = [v for v in valued if v.value is not None]
    total = sum(v.value for v in priced)
    cost_known = [v for v in priced if v.cost is not None]
    print(f"Portfolio in {base} ({len(priced)} of {len(valued)} positions priced)\n")
    print(f"  {'position':<12} {'quantity':>12} {'price':>18} {'value ' + base:>16} {'gain/loss':>16} {'':>8} {'weight':>7}")
    for v in sorted(priced, key=lambda v: -v.value):
        gain = v.value - v.cost if v.cost is not None and v.row.kind != "cash" else None
        gain_pct = (gain / v.cost * 100) if gain is not None and v.cost else None
        print(f"  {v.row.symbol:<12} {v.row.quantity:>12,.6g} {fmt_money(v.price, v.price_currency):>18} "
              f"{fmt_money(v.value):>16} {fmt_money(gain):>16} {fmt_pct(gain_pct):>8} "
              f"{fmt_pct(v.value / total * 100 if total else None, signed=False):>7}")
    for v in valued:
        if v.value is None:
            print(f"  {v.row.symbol:<12} no price: {v.error}")
    cost = sum(v.cost for v in cost_known)
    value_known = sum(v.value for v in cost_known)
    print(f"\n  total value {fmt_money(total, base)}")
    if cost_known:
        print(f"  gain/loss on positions with a purchase price: {fmt_money(value_known - cost, base)} "
              f"({fmt_pct((value_known / cost - 1) * 100 if cost else None)})")
    sources = sorted({v.source for v in priced if v.source != "cash"})
    print(f"\nPrices: {', '.join(sources) or 'none'}; currency: ECB reference rates. Not tax figures. {DISCLAIMER}")
    return 1 if len(priced) < len(valued) else 0


if __name__ == "__main__":
    run_main(main)
