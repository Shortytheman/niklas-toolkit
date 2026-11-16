#!/usr/bin/env python3
"""Danish official statistics from Statistics Denmark (Danmarks Statistik, api.statbank.dk). No API key.

    python dk_stats.py inflation                 consumer price inflation, last 13 months
    python dk_stats.py cpi | population          other shortcuts (see PRESETS)
    python dk_stats.py search unemployment       find tables (by id, title or variable)
    python dk_stats.py info AUP02                a table's variables and their codes
    python dk_stats.py get PRIS01 VAREGR=000000 ENHED=300 --last 24

In `get`, give a value for each variable that cannot be left out (info shows which); variables you leave out are
summed or eliminated by Statistics Denmark. Time is the last --last periods (default 12).

Data: Statistics Denmark, CC BY 4.0 - the output credits it. Exit codes: 0 ok, 2 bad table/variable or network.
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from common import SetupError, run_main, sparkline  # noqa: E402

API = "https://api.statbank.dk/v1"
ATTRIBUTION = "Source: Statistics Denmark (statbank.dk), CC BY 4.0"
PRESETS = {
    "inflation": ("PRIS01", {"VAREGR": "000000", "ENHED": "300"}, 13,
                  "Consumer price inflation, % change from the same month a year before"),
    "cpi": ("PRIS01", {"VAREGR": "000000", "ENHED": "100"}, 13, "Consumer price index"),
    "population": ("FOLK1AM", {}, 13, "Population on the first day of the month, whole country"),
}


def tables() -> list[dict]:
    return netlib.get_json(f"{API}/tables", params={"lang": "en", "format": "JSON"}, ttl=86400,
                           source="Statistics Denmark", timeout=60)


def info(table: str) -> dict:
    try:
        return netlib.get_json(f"{API}/tableinfo/{table}", params={"lang": "en", "format": "JSON"}, ttl=86400,
                               source="Statistics Denmark")
    except netlib.NetError as e:
        if e.status in (400, 404):
            raise SetupError(f"no table called {table}; find one with: dk_stats.py search <words>") from e
        raise


def fetch(table: str, selection: dict[str, str], last: int) -> tuple[dict, list[dict]]:
    """Table info and the rows (dicts with the variable texts, TID and INDHOLD) of the last `last` periods."""
    meta = info(table)
    variables = {v["id"].upper(): v for v in meta["variables"]}
    wanted = {k.upper(): v for k, v in selection.items()}
    for k in wanted:
        if k not in variables:
            raise SetupError(f"{table} has no variable {k}; it has {', '.join(variables)}")
    body_vars = []
    for vid, v in variables.items():
        if v.get("time"):
            body_vars.append({"code": v["id"], "values": ["*"]})
        elif vid in wanted:
            codes = [x["id"] for x in v["values"]]
            values = wanted[vid].split(",")
            bad = [x for x in values if x not in codes]
            if bad:
                sample = ", ".join(f"{x['id']}={x['text']}" for x in v["values"][:8])
                raise SetupError(f"{vid}: unknown code(s) {bad}; for example {sample}")
            body_vars.append({"code": v["id"], "values": values})
        elif not v.get("elimination"):
            options = ", ".join(f"{x['id']}={x['text']}" for x in v["values"][:8])
            raise SetupError(f"{table} needs a value for {vid} ({v['text']}), e.g. {vid}={v['values'][0]['id']}. "
                             f"Options: {options}")
    payload = {"table": table, "format": "CSV", "lang": "en", "variables": body_vars}
    text = netlib.request(f"{API}/data", data=__import__("json").dumps(payload).encode(), ttl=6 * 3600,
                          source="Statistics Denmark", timeout=60).decode("utf-8-sig", "replace")
    rows = list(csv.DictReader(io.StringIO(text), delimiter=";"))
    periods = sorted({r["TID"] for r in rows})[-last:]
    return meta, [r for r in rows if r["TID"] in periods]


def number(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except (ValueError, AttributeError):
        return None  # ".." means not available


def show(meta: dict, rows: list[dict], title: str = "") -> None:
    print(f"{title or meta['text']} ({meta['id']}, {meta['unit']}, updated {meta['updated'][:10]})")
    series_keys = [k for k in rows[0] if k not in ("TID", "INDHOLD")] if rows else []
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault(tuple(r[k] for k in series_keys), []).append(r)
    for key, rs in groups.items():
        if len(groups) > 1 or any(key):
            print(f"  {' / '.join(key)}")
        values = [number(r["INDHOLD"]) for r in rs]
        known = [v for v in values if v is not None]
        for r, v in zip(rs, values):
            print(f"    {r['TID']:<9} {r['INDHOLD'] if v is None else f'{v:,.2f}'.rstrip('0').rstrip('.')}")
        if len(known) >= 3:
            print(f"    {sparkline(known)}")
    print(ATTRIBUTION)


def main() -> int:
    ap = argparse.ArgumentParser(description="Danish statistics from Statistics Denmark (no key).")
    ap.add_argument("command", help="a shortcut (" + ", ".join(PRESETS) + "), or search, info, get")
    ap.add_argument("args", nargs="*", help="search words, a table id, or TABLE VAR=code ...")
    ap.add_argument("--last", type=int, default=None, help="number of latest periods (default 12)")
    a = ap.parse_args()

    if a.command in PRESETS:
        table, sel, last, title = PRESETS[a.command]
        meta, rows = fetch(table, sel, a.last or last)
        show(meta, rows, title)
        return 0
    if a.command == "search":
        words = [w.lower() for w in a.args]
        if not words:
            raise SetupError("give search words, e.g. dk_stats.py search unemployment")
        hits = [t for t in tables() if all(w in (t["id"] + " " + t["text"] + " " + " ".join(t.get("variables", []))).lower()
                                           for w in words)]
        hits.sort(key=lambda t: (not t.get("active", True), t["id"]))
        for t in hits[:25]:
            print(f"  {t['id']:<10} {t['text']}  ({t.get('firstPeriod', '?')}-{t.get('latestPeriod', '?')}"
                  f"{'' if t.get('active', True) else ', no longer updated'})")
        print(f"{len(hits)} table(s)" + (", first 25 shown" if len(hits) > 25 else "") + f". {ATTRIBUTION}")
        return 0
    if a.command == "info":
        if not a.args:
            raise SetupError("give a table id, e.g. dk_stats.py info PRIS01")
        meta = info(a.args[0].upper())
        print(f"{meta['id']}: {meta['text']} ({meta['unit']}, updated {meta['updated'][:10]}"
              f"{'' if meta.get('active', True) else ', no longer updated'})")
        for v in meta["variables"]:
            need = "time" if v.get("time") else ("optional" if v.get("elimination") else "required")
            sample = ", ".join(f"{x['id']}={x['text']}" for x in v["values"][:6])
            print(f"  {v['id']:<10} {v['text']} [{need}, {len(v['values'])} values]: {sample}"
                  + (" ..." if len(v["values"]) > 6 else ""))
        return 0
    if a.command == "get":
        if not a.args:
            raise SetupError("give a table id, e.g. dk_stats.py get PRIS01 VAREGR=000000 ENHED=300")
        sel = dict(arg.split("=", 1) for arg in a.args[1:] if "=" in arg)
        meta, rows = fetch(a.args[0].upper(), sel, a.last or 12)
        show(meta, rows)
        return 0
    raise SetupError(f"unknown command {a.command!r}; use {', '.join(PRESETS)}, search, info or get")


if __name__ == "__main__":
    run_main(main)
