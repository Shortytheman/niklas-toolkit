#!/usr/bin/env python3
"""How much of Claude's context your setup uses before you type anything, and where it goes.

Runs without Claude. Standard library only. Read-only.

    python context_cost.py [project_dir] [--all] [--json]

Counts, per plugin and in total:
    always   what loads into every session: each skill's, agent's and command's name and description, and the
             full text of every CLAUDE.md that applies to the project
    on use   what a skill or agent adds when it is used (its body)
MCP servers are listed too: their tool definitions also load at start, but their size is only known by running
them, so they are counted, not measured.

Token numbers are estimates (about 4 characters per token). Exit code 0, or 2 when nothing is installed.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_home import claude_dir, installed_plugins, loose_components  # noqa: E402
from mcp_cost import configured_servers, measure  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Estimate the context cost of installed Claude Code extensions.")
    ap.add_argument("project", nargs="?", default=".", help="project folder (default: .)")
    ap.add_argument("--all", action="store_true", help="list every component, not just the top 15")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--measure-mcp", action="store_true",
                    help="start each stdio MCP server and count its tool definitions (runs the servers' programs)")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    project = Path(a.project).resolve()
    plugins = installed_plugins(project)
    loose = loose_components(project)
    comps = [c for p in plugins if p.enabled for c in p.components] + loose
    servers = configured_servers(project, plugins)
    if not comps and not servers:
        print(f"Nothing installed that loads into context for {project} (looked in {claude_dir()}).")
        return 2
    measured = {}
    if a.measure_mcp and servers:
        with ThreadPoolExecutor(max_workers=4) as pool:
            measured = {id(m.server): m for m in pool.map(measure, servers)}

    by_origin: dict[str, list] = defaultdict(list)
    for c in comps:
        by_origin[c.origin].append(c)
    mcp_tokens = sum(m.tokens for m in measured.values())
    total_always = sum(c.always for c in comps) + mcp_tokens

    if a.json:
        print(json.dumps({"always_tokens": total_always,
                          "origins": {o: {"always": sum(c.always for c in cs), "on_use": sum(c.on_use for c in cs),
                                          "components": [{"kind": c.kind, "name": c.name, "always": c.always,
                                                          "on_use": c.on_use} for c in cs]}
                                      for o, cs in by_origin.items()},
                          "mcp_servers": [{"name": s.name, "origin": s.origin,
                                           **({"tools": measured[id(s)].tools, "tokens": measured[id(s)].tokens,
                                               "error": measured[id(s)].error} if id(s) in measured else {})}
                                          for s in servers],
                          "disabled_plugins": [p.key for p in plugins if not p.enabled]}, indent=2))
        return 0

    unmeasured = len(servers) - sum(1 for m in measured.values() if not m.error)
    print(f"{project.name}: about {total_always:,} tokens load into every session from {len(comps)} item(s)"
          + (f" and {len(servers)} MCP server(s)" if servers else "")
          + (f" ({unmeasured} not measured)" if unmeasured else "") + "\n")
    print(f"  {'source':<34} {'items':>5} {'always':>8} {'on use':>8}")
    for origin, cs in sorted(by_origin.items(), key=lambda kv: -sum(c.always for c in kv[1])):
        kinds = defaultdict(int)
        for c in cs:
            kinds[c.kind] += 1
        label = ", ".join(f"{n} {k}{'s' if n > 1 else ''}" for k, n in kinds.items())
        print(f"  {origin:<34} {len(cs):>5} {sum(c.always for c in cs):>8,} {sum(c.on_use for c in cs):>8,}   {label}")
    for s in servers:
        m = measured.get(id(s))
        if m and not m.error:
            print(f"  {s.origin:<34} {m.tools:>5} {m.tokens:>8,} {'':>8}   MCP server {s.name}: {m.tools} tool(s)")
        else:
            why = m.error if m else "measure with --measure-mcp"
            print(f"  {s.origin:<34} {'':>5} {'?':>8} {'':>8}   MCP server {s.name}: {why}")

    ranked = sorted(comps, key=lambda c: -c.always)
    shown = ranked if a.all else ranked[:15]
    print(f"\nLargest always-loaded items:")
    for c in shown:
        name = Path(c.name).name if c.kind == "claude-md" else c.name
        print(f"  {c.always:>6,}  {c.kind:<9} {name:<32} ({c.origin})")
    if len(ranked) > len(shown):
        print(f"  ... {len(ranked) - len(shown)} more (--all)")
    disabled = [p.key for p in plugins if not p.enabled]
    if disabled:
        print(f"\nInstalled but disabled (cost nothing): {', '.join(disabled)}")
    print("\nEstimates at ~4 characters per token. Long descriptions cost tokens in every session: keep them to "
          "what decides when the item is used. skill_usage.py shows which skills never fire.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
