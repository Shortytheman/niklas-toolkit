#!/usr/bin/env python3
"""Show or create the brief pack's settings file.

    python brief_config.py            where the file is and what it contains (API keys masked)
    python brief_config.py --init     write a starter file if there is none

The file is personal: it lives in your user folder, never in a project, so keys and holdings are not committed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402

TEMPLATE = {
    "contact": "",
    "currency": "DKK",
    "location": {"name": "Copenhagen", "lat": 55.6761, "lon": 12.5683},
    "watchlist": {"fx": ["EUR", "USD", "SEK"], "crypto": ["btc", "eth"], "stocks": []},
    "portfolio": "",
    "feeds": [{"name": "Godot news", "url": "https://godotengine.org/rss.xml"}],
    "github_releases": ["godotengine/godot"],
    "stocks": {"providers": ["finnhub", "tiingo", "yahoo"], "allow_unofficial_yahoo": False},
    "brief": {"sections": ["weather", "holidays", "fx", "crypto", "stocks", "portfolio", "news", "releases"],
              "hn": 5},
    "keys": {"FINNHUB_API_KEY": "", "TIINGO_API_KEY": "", "COINGECKO_DEMO_KEY": ""},
}


def masked(cfg: dict) -> dict:
    out = json.loads(json.dumps(cfg))
    for k, v in (out.get("keys") or {}).items():
        out["keys"][k] = (v[:3] + "..." + f"({len(v)} chars)") if v else ""
    return out


def main(argv: list[str] | None = None) -> int:
    netlib.force_utf8_output()
    ap = argparse.ArgumentParser(description="Show or create the toolkit's personal settings file.")
    ap.add_argument("--init", action="store_true", help="write a starter file if none exists")
    a = ap.parse_args(argv)
    path = netlib.config_path()
    if a.init:
        if path.exists():
            print(f"{path} already exists; not overwriting it.")
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(TEMPLATE, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {path}. Fill in contact (an e-mail; some free APIs ask for one), location, watchlists and "
              f"any API keys.")
        return 0
    if not path.exists():
        print(f"No settings yet. Create them with: brief_config.py --init   (would be {path})")
        return 0
    try:
        cfg = netlib.load_config()
    except netlib.NetError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"Settings: {path}\n")
    print(json.dumps(masked(cfg), indent=2))
    env_keys = [k for k in TEMPLATE["keys"] if netlib.os.environ.get(k)]
    if env_keys:
        print(f"\nAlso set in the environment: {', '.join(env_keys)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
