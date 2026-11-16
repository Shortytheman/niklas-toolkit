#!/usr/bin/env python3
"""Find broken resource references in a Godot 4 project without running Godot.

Runs without Claude. Standard library only. Read-only: it never changes the project.

    python doctor.py [project_dir] [--unused] [--only CHECK ...] [--max N]

Checks (see godot_index.doctor):
  broken-path  res:// paths that point at nothing                                   error
  wrong-case   paths whose letter case differs from the file: fine on Windows,     error
               broken in exports and on Linux/macOS
  stale-uid    ext_resources whose uid names a different file than their path      warning
  unknown-uid  uid:// references no file owns                                      error/warning
  unused       files nothing references (only with --unused)                       info

Paths built at runtime ("res://icons/" + name) cannot be checked and are skipped.

Known findings can be silenced in toolkit.json with regular expressions matched against "<file> <message>":
    {"doctor": {"ignore": ["res://assets/sfx/"]}}

Exit codes: 0 no errors, 1 errors found, 2 bad setup.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from godot_common import SetupError, find_project, load_toolkit_config  # noqa: E402
from godot_index import Index, doctor  # noqa: E402

CHECKS = ["broken-path", "wrong-case", "stale-uid", "unknown-uid", "unused"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Find broken resource references in a Godot project.")
    ap.add_argument("project", nargs="?", default=".", help="project folder or any folder inside it (default: .)")
    ap.add_argument("--unused", action="store_true", help="also list files nothing references")
    ap.add_argument("--only", action="append", choices=CHECKS, help="run only these checks (repeatable)")
    ap.add_argument("--max", type=int, default=50, help="most findings to print per check (default 50)")
    args = ap.parse_args(argv)

    try:
        project = find_project(args.project)
        patterns = load_toolkit_config(project).get("doctor", {}).get("ignore", [])
        ignore = [re.compile(p) for p in patterns]
    except SetupError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except re.error as e:
        print(f"ERROR: bad pattern in toolkit.json doctor.ignore: {e}", file=sys.stderr)
        return 2

    start = time.monotonic()
    idx = Index.build(project)
    findings = doctor(idx, include_unused=args.unused or (args.only is not None and "unused" in args.only))
    if args.only:
        findings = [f for f in findings if f.check in args.only]
    ignored =[f for f in findings if any(r.search(f"{f.file} {f.message}") for r in ignore)]
    findings = [f for f in findings if f not in ignored]

    counts = Counter(f.severity for f in findings)
    print(f"{project.name}: {len(idx.files)} files checked in {time.monotonic() - start:.1f}s  |  "
          f"{counts['error']} error(s), {counts['warning']} warning(s)" +
          (f", {counts['info']} unused" if counts["info"] else "") +
          (f"  ({len(ignored)} ignored by toolkit.json)" if ignored else ""))
    for check in CHECKS:
        group = [f for f in findings if f.check == check]
        if not group:
            continue
        print(f"\n{check} ({len(group)}):")
        for f in group[:args.max]:
            where = f"{f.file}:{f.line}" if f.line else f.file
            print(f"  {where}  {f.message}" if f.check != "unused" else f"  {f.file}")
        if len(group) > args.max:
            print(f"  ... {len(group) - args.max} more")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
