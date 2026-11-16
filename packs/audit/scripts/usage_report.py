#!/usr/bin/env python3
"""Where your Claude Code tokens go: by day, project, model, session and tool, from the local session logs.

Standard library only. Read-only and local: it reads the session transcripts in ~/.claude/projects (including
subagent transcripts) and uses only their token counts, model names, timestamps, folders, session titles and
tool names. It reads no message text and sends nothing anywhere.

    python usage_report.py [--days 30] [--project NAME] [--top 10] [--json]

Token columns follow the API's usage fields:
    input        fresh input tokens (not from the cache)
    cache write  input written to the prompt cache (costs a little more than fresh input)
    cache read   input served from the prompt cache (costs about a tenth of fresh input)
    output       generated tokens, thinking included
"Peak context" is the largest single request of a session (input + cache write + cache read): close to the
model's context window means the session was about to be compacted.

Exit codes: 0 report printed, 2 no usage found in the period.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_home import claude_dir  # noqa: E402

FIELDS = ("input", "cache_write", "cache_read", "output")


@dataclass
class Tally:
    responses: int = 0
    input: int = 0
    cache_write: int = 0
    cache_read: int = 0
    output: int = 0

    def add(self, u: dict) -> None:
        self.responses += 1
        self.input += u.get("input_tokens") or 0
        self.cache_write += u.get("cache_creation_input_tokens") or 0
        self.cache_read += u.get("cache_read_input_tokens") or 0
        self.output += u.get("output_tokens") or 0

    @property
    def total(self) -> int:
        return self.input + self.cache_write + self.cache_read + self.output

    def as_dict(self) -> dict:
        return {"responses": self.responses, **{f: getattr(self, f) for f in FIELDS}, "total": self.total}


@dataclass
class Session:
    id: str
    project: str = ""
    title: str = ""
    start: str = ""
    tally: Tally = field(default_factory=Tally)
    subagents: Tally = field(default_factory=Tally)
    peak_context: int = 0
    compactions: int = 0


def session_files(root: Path, cutoff: float) -> list[tuple[Path, str]]:
    """(file, session id) for main transcripts and their subagent transcripts changed since the cutoff."""
    out = []
    for f in root.glob("*/*.jsonl"):
        if f.stat().st_mtime >= cutoff:
            out.append((f, f.stem))
    for f in root.glob("*/*/subagents/*.jsonl"):
        if f.stat().st_mtime >= cutoff:
            out.append((f, f.parent.parent.name))
    return sorted(out)


def read_usage(files: list[tuple[Path, str]], since: float) -> tuple[dict[str, Session], dict, Counter]:
    sessions: dict[str, Session] = {}
    days: dict[str, Tally] = defaultdict(Tally)
    models: dict[str, Tally] = defaultdict(Tally)
    tools: Counter = Counter()
    seen: set[str] = set()
    for path, sid in files:
        s = sessions.setdefault(sid, Session(sid))
        sub = path.parent.name == "subagents"
        try:
            handle = path.open(encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for line in handle:
                if '"usage"' not in line and '"custom-title"' not in line and "compact_boundary" not in line:
                    continue                                       # cheap filter: most lines are irrelevant
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = d.get("type")
                if kind == "custom-title":
                    s.title = d.get("customTitle") or s.title
                    continue
                if kind == "system" and d.get("subtype") == "compact_boundary":
                    s.compactions += 1
                    continue
                if kind != "assistant":
                    continue
                msg = d.get("message") or {}
                for block in msg.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") not in seen:
                        seen.add(block.get("id"))
                        tools[block.get("name", "?")] += 1
                usage, mid = msg.get("usage"), msg.get("id") or d.get("requestId")
                if not usage or not mid or mid in seen:            # one response is logged once per content block
                    continue
                seen.add(mid)
                stamp = d.get("timestamp", "")
                try:
                    when = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone()
                except ValueError:
                    continue
                if when.timestamp() < since:
                    continue
                if msg.get("model", "").startswith("<"):             # synthetic messages, no real request
                    continue
                if not s.project and d.get("cwd"):
                    s.project = Path(d["cwd"]).name
                s.start = min(s.start or stamp, stamp)
                (s.subagents if sub else s.tally).add(usage)
                days[when.date().isoformat()].add(usage)
                models[msg.get("model", "unknown")].add(usage)
                if not sub:
                    ctx = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                           "cache_read_input_tokens"))
                    s.peak_context = max(s.peak_context, ctx)
    used = {k: v for k, v in sessions.items() if v.tally.responses or v.subagents.responses}
    return used, {"days": dict(days), "models": dict(models)}, tools


def combined(s: Session) -> Tally:
    t = Tally()
    for part in (s.tally, s.subagents):
        t.responses += part.responses
        for f in FIELDS:
            setattr(t, f, getattr(t, f) + getattr(part, f))
    return t


def report(sessions: dict[str, Session], groups: dict, tools: Counter, days: int, top: int) -> dict:
    total, subs = Tally(), Tally()
    projects: dict[str, Tally] = defaultdict(Tally)
    for s in sessions.values():
        c = combined(s)
        for t in (total, projects[s.project or "(unknown)"]):
            t.responses += c.responses
            for f in FIELDS:
                setattr(t, f, getattr(t, f) + getattr(c, f))
        subs.responses += s.subagents.responses
        for f in FIELDS:
            setattr(subs, f, getattr(subs, f) + getattr(s.subagents, f))
    fed = total.input + total.cache_write + total.cache_read
    ranked = sorted(sessions.values(), key=lambda s: -combined(s).total)[:top]
    return {
        "days": days,
        "total": total.as_dict(),
        "cache_read_share": round(total.cache_read / fed, 4) if fed else 0,
        "subagents": subs.as_dict(),
        "by_day": {k: v.as_dict() for k, v in sorted(groups["days"].items())},
        "by_project": {k: v.as_dict() for k, v in sorted(projects.items(), key=lambda kv: -kv[1].total)},
        "by_model": {k: v.as_dict() for k, v in sorted(groups["models"].items(), key=lambda kv: -kv[1].total)},
        "sessions": [{"id": s.id, "title": s.title, "project": s.project, "start": s.start[:16].replace("T", " "),
                      **combined(s).as_dict(), "subagent_tokens": s.subagents.total,
                      "peak_context": s.peak_context, "compactions": s.compactions} for s in ranked],
        "session_count": len(sessions),
        "tools": dict(tools.most_common(top)),
    }


def short(n: float) -> str:
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(n) >= size:
            return f"{n / size:.1f}{unit}"
    return f"{n:.0f}"


def row(label: str, t: dict, width: int = 26) -> str:
    return (f"  {label[:width]:<{width}} {t['responses']:>7,} {short(t['input']):>8} {short(t['cache_write']):>8} "
            f"{short(t['cache_read']):>8} {short(t['output']):>8}")


def print_report(r: dict) -> None:
    t = r["total"]
    print(f"Claude Code usage, last {r['days']} days: {r['session_count']} session(s), {t['responses']:,} responses, "
          f"{short(t['total'])} tokens\n")
    print(f"  output {short(t['output'])}, fresh input {short(t['input'])}, cache write {short(t['cache_write'])}, "
          f"cache read {short(t['cache_read'])}")
    print(f"  {r['cache_read_share']:.0%} of all input came from the prompt cache")
    if r["subagents"]["responses"]:
        share = r["subagents"]["total"] / t["total"] if t["total"] else 0
        print(f"  subagents: {r['subagents']['responses']:,} responses, {short(r['subagents']['total'])} tokens "
              f"({share:.0%})")
    head = f"  {'':<26} {'replies':>7} {'input':>8} {'c.write':>8} {'c.read':>8} {'output':>8}"
    for title, key in (("By day", "by_day"), ("By project", "by_project"), ("By model", "by_model")):
        print(f"\n{title}:\n{head}")
        for k, v in r[key].items():
            print(row(k, v))
    print(f"\nLargest sessions:\n  {'tokens':>8} {'peak ctx':>8} {'compact':>7}  session")
    for s in r["sessions"]:
        name = s["title"] or s["id"][:8]
        print(f"  {short(s['total']):>8} {short(s['peak_context']):>8} {s['compactions']:>7}  {name}  "
              f"({s['project']}, {s['start']})")
    if r["tools"]:
        print("\nMost-used tools: " + ", ".join(f"{k} {v:,}" for k, v in r["tools"].items()))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Token usage from local Claude Code session logs.")
    ap.add_argument("--days", type=int, default=30, help="period in days (default 30)")
    ap.add_argument("--project", help="only sessions whose folder name contains this text")
    ap.add_argument("--top", type=int, default=10, help="sessions and tools to list (default 10)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)
    since = time.time() - a.days * 86400
    sessions, groups, tools = read_usage(session_files(claude_dir() / "projects", since), since)
    if a.project:
        sessions = {k: s for k, s in sessions.items() if a.project.lower() in s.project.lower()}
        if sessions:      # recount the day and model groups for just these sessions
            keep = {f for f in session_files(claude_dir() / "projects", since) if f[1] in sessions}
            _, groups, tools = read_usage(sorted(keep), since)
    if not sessions:
        print(f"No Claude Code usage found in the last {a.days} days.", file=sys.stderr)
        return 2
    r = report(sessions, groups, tools, a.days, a.top)
    print(json.dumps(r, indent=2) if a.json else "", end="\n" if a.json else "")
    if not a.json:
        print_report(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
