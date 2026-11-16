#!/usr/bin/env python3
"""Headlines: Hacker News top stories, your RSS/Atom feeds, and new GitHub releases. No API keys.

    python news.py                 everything configured
    python news.py --hn 10         Hacker News top 10 only
    python news.py --feeds         configured feeds only
    python news.py --releases      new releases of configured GitHub repos (last 14 days)

config.json:
    "feeds": [{"name": "Godot news", "url": "https://godotengine.org/rss.xml"}, ...],
    "github_releases": ["godotengine/godot", "anthropics/claude-code"]

GitHub releases come from each repo's releases.atom feed, which does not use the 60-requests-an-hour limit of
GitHub's unauthenticated API. Feeds are fetched with ETag / Last-Modified, so unchanged feeds cost almost nothing.
Exit codes: 0 ok (a failing feed is reported but does not fail the run), 2 setup problem.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from common import run_main, settings  # noqa: E402

HN = "https://hacker-news.firebaseio.com/v0"
ATOM = "{http://www.w3.org/2005/Atom}"


def hn_top(n: int = 10) -> list[dict]:
    ids = netlib.get_json(f"{HN}/topstories.json", ttl=300, source="Hacker News")[:n]
    with ThreadPoolExecutor(max_workers=8) as pool:
        items = list(pool.map(lambda i: netlib.get_json(f"{HN}/item/{i}.json", ttl=3600, source="Hacker News"), ids))
    return [{"title": it.get("title", ""), "url": it.get("url") or f"https://news.ycombinator.com/item?id={it['id']}",
             "points": it.get("score", 0), "comments": it.get("descendants", 0),
             "discussion": f"https://news.ycombinator.com/item?id={it['id']}"} for it in items if it]


def _date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0 and Atom entries as {title, link, date}, newest first."""
    root = ET.fromstring(xml_text)
    entries = []
    for item in root.iter("item"):  # RSS
        entries.append({"title": (item.findtext("title") or "").strip(), "link": (item.findtext("link") or "").strip(),
                        "date": _date(item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date"))})
    for entry in root.iter(f"{ATOM}entry"):  # Atom
        link = entry.find(f"{ATOM}link[@rel='alternate']")
        if link is None:  # an Element with no children is falsy, so `a or b` would be wrong here
            link = entry.find(f"{ATOM}link")
        entries.append({"title": (entry.findtext(f"{ATOM}title") or "").strip(),
                        "link": link.get("href", "") if link is not None else "",
                        "date": _date(entry.findtext(f"{ATOM}updated") or entry.findtext(f"{ATOM}published"))})
    for e in entries:
        e["title"] = html.unescape(re.sub(r"<[^>]+>", "", e["title"]))
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(entries, key=lambda e: e["date"] or epoch, reverse=True)


def fetch_feed(url: str) -> list[dict]:
    return parse_feed(netlib.get_text(url, ttl=900, source=url.split("/")[2]))


def releases(repos: list[str], days: int = 14) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    def one(repo: str) -> list[dict]:
        try:
            entries = fetch_feed(f"https://github.com/{repo}/releases.atom")
        except (netlib.NetError, ET.ParseError) as e:
            return [{"repo": repo, "error": str(e)}]
        return [dict(e, repo=repo) for e in entries if e["date"] and e["date"] >= cutoff][:3]

    with ThreadPoolExecutor(max_workers=6) as pool:
        return [r for group in pool.map(one, repos) for r in group]


def ago(dt: datetime | None) -> str:
    if not dt:
        return ""
    hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    return f"{int(hours)}h ago" if hours < 48 else f"{int(hours // 24)}d ago"


def main() -> int:
    ap = argparse.ArgumentParser(description="Hacker News, RSS/Atom feeds and GitHub releases.")
    ap.add_argument("--hn", type=int, nargs="?", const=10, help="Hacker News top N (default 10)")
    ap.add_argument("--feeds", action="store_true", help="configured feeds")
    ap.add_argument("--releases", action="store_true", help="GitHub releases of configured repos")
    ap.add_argument("--per-feed", type=int, default=5, help="entries per feed (default 5)")
    a = ap.parse_args()
    cfg = settings()
    everything = a.hn is None and not a.feeds and not a.releases

    if a.hn or everything:
        print(f"Hacker News top {a.hn or 10}:")
        for s in hn_top(a.hn or 10):
            print(f"  {s['points']:>4} pts  {s['title']}\n            {s['url']}")
    if a.feeds or everything:
        for feed in cfg.get("feeds", []):
            name, url = feed.get("name", feed.get("url")), feed.get("url")
            try:
                entries = fetch_feed(url)[:a.per_feed]
            except (netlib.NetError, ET.ParseError) as e:
                print(f"\n{name}: could not read the feed ({e})")
                continue
            print(f"\n{name}:")
            for e in entries:
                print(f"  {e['title']}  {ago(e['date'])}\n      {e['link']}")
        if a.feeds and not cfg.get("feeds"):
            print('No feeds configured: add "feeds": [{"name": "...", "url": "..."}] to ' + str(netlib.config_path()))
    if a.releases or everything:
        repos = cfg.get("github_releases", [])
        if repos:
            print("\nNew releases (14 days):")
            found = releases(repos)
            for r in found:
                if r.get("error"):
                    print(f"  {r['repo']}: {r['error']}")
                else:
                    print(f"  {r['repo']}: {r['title']}  {ago(r['date'])}  {r['link']}")
            if not any(not r.get("error") for r in found):
                print("  none")
        elif a.releases:
            print('No repos configured: add "github_releases": ["owner/repo"] to ' + str(netlib.config_path()))
    return 0


if __name__ == "__main__":
    run_main(main)
