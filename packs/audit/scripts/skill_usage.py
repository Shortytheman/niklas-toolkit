#!/usr/bin/env python3
"""Which skills and agents actually get used, from your Claude Code session logs, and which never fire.

Runs without Claude. Standard library only. Read-only and local: it reads the session transcripts in
~/.claude/projects, counts Skill tool calls, subagent launches and slash commands by name, and reads nothing
else from them. Nothing is sent anywhere.

    python skill_usage.py [project_dir] [--days 30] [--json]

Exit codes: 0 report printed, 2 no transcripts found.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_home import installed_plugins, loose_components, transcripts  # noqa: E402

COMMAND_TAG = re.compile(r"<command-name>/?([^<\s]+)</command-name>")


def count_uses(files: list[Path]) -> tuple[Counter, Counter, int]:
    """(skill uses, agent uses, sessions read). Skill names are stored as written, e.g. 'deps' or 'brief:markets'."""
    skills, agents = Counter(), Counter()
    sessions = 0
    for f in files:
        sessions += 1
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if '"Skill"' not in line and '"Agent"' not in line and '"Task"' not in line and "command-name" not in line:
                continue  # cheap filter: most lines are irrelevant
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (event.get("message") or {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use" and block.get("name") == "Skill":
                        skills[str((block.get("input") or {}).get("skill", "?"))] += 1
                    elif block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                        agents[str((block.get("input") or {}).get("subagent_type", "general-purpose"))] += 1
                    elif block.get("type") == "text":
                        for m in COMMAND_TAG.finditer(block.get("text", "")):
                            skills[m.group(1)] += 1
            elif isinstance(content, str):
                for m in COMMAND_TAG.finditer(content):
                    skills[m.group(1)] += 1
    return skills, agents, sessions


def short(name: str) -> str:
    """'plugin:skill' and 'skill' both match a skill called 'skill'."""
    return name.split(":")[-1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Skill and agent usage from local session logs.")
    ap.add_argument("project", nargs="?", default=".", help="project folder for the installed list (default: .)")
    ap.add_argument("--days", type=int, default=30, help="look back this many days (default 30)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    files = transcripts(a.days)
    if not files:
        print(f"No session logs from the last {a.days} days.", file=sys.stderr)
        return 2
    skills, agents, sessions = count_uses(files)
    project = Path(a.project).resolve()
    installed = [c for p in installed_plugins(project) if p.enabled for c in p.components] + \
        [c for c in loose_components(project) if c.kind != "claude-md"]
    used_names = {short(n) for n in skills} | {short(n) for n in agents}
    unused = [c for c in installed if c.kind in ("skill", "agent", "command") and c.name not in used_names]

    if a.json:
        print(json.dumps({"days": a.days, "sessions": sessions, "skills": dict(skills), "agents": dict(agents),
                          "never_used": [{"kind": c.kind, "name": c.name, "origin": c.origin, "always_tokens": c.always}
                                         for c in unused]}, indent=2))
        return 0

    print(f"Last {a.days} days: {sessions} session log(s), {sum(skills.values())} skill/command use(s), "
          f"{sum(agents.values())} subagent launch(es)\n")
    if skills:
        print("Skills and slash commands used:")
        for name, n in skills.most_common(25):
            print(f"  {n:>4}  {name}")
    if agents:
        print("\nSubagents launched:")
        for name, n in agents.most_common(10):
            print(f"  {n:>4}  {name}")
    if unused:
        cost = sum(c.always for c in unused)
        print(f"\nInstalled for this project but not used in {a.days} days (about {cost:,} tokens every session):")
        for c in sorted(unused, key=lambda c: -c.always):
            print(f"  {c.kind:<8} {c.name:<28} {c.always:>5} tokens  ({c.origin})")
        print("\nNot used is not useless: a rarely needed skill can still be worth its cost. Disable whole plugins "
              "you do not need with /plugin, per project if they only matter in some.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
