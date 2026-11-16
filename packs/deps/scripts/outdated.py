#!/usr/bin/env python3
"""List dependencies with newer releases, sorted by how big the jump is (major, minor, patch).

Runs without Claude. Standard library only, no API keys.

    python outdated.py [project_dir] [--all] [--json]

By default only direct dependencies (the ones the project lists itself); --all includes transitive ones from
lockfiles. Registry answers are cached for 6 hours.

Exit codes: 0 always when the check ran (outdated is information, not failure), 2 setup problem.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from lockfiles import scan  # noqa: E402
from registry import bump_kind, lookup_all  # noqa: E402

ORDER = {"major": 0, "minor": 1, "patch": 2}


def main(argv: list[str] | None = None) -> int:
    netlib.force_utf8_output()
    ap = argparse.ArgumentParser(description="List dependencies with newer releases.")
    ap.add_argument("project", nargs="?", default=".", help="project folder (default: .)")
    ap.add_argument("--all", action="store_true", help="include transitive dependencies")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    root = Path(args.project).resolve()
    result = scan(root)
    if not result.files:
        print(f"No dependency files found in {root}.", file=sys.stderr)
        return 2
    packages = [p for p in result.packages if args.all or p.direct] + result.unpinned
    infos = lookup_all(packages)

    rows, unpinned, errors = [], [], []
    for p, info in infos.items():
        if info.error:
            errors.append(f"{p.name}: {info.error}")
        elif not p.version:
            unpinned.append((p, info.latest))
        else:
            kind = bump_kind(p.version, info.latest)
            if kind:
                rows.append((p, info.latest, kind))
    rows.sort(key=lambda r: (ORDER[r[2]], r[0].ecosystem, r[0].name))

    if args.json:
        print(json.dumps({"outdated": [{"ecosystem": p.ecosystem, "name": p.name, "current": p.version,
                                        "latest": latest, "kind": kind, "direct": p.direct, "source": p.source}
                                       for p, latest, kind in rows],
                          "unpinned": [{"name": p.name, "latest": latest} for p, latest in unpinned],
                          "errors": errors}, indent=2))
        return 0

    scope = "all" if args.all else "direct"
    print(f"{root.name}: {len(packages)} {scope} package(s) checked  |  {len(rows)} outdated "
          f"({sum(r[2] == 'major' for r in rows)} major, {sum(r[2] == 'minor' for r in rows)} minor, "
          f"{sum(r[2] == 'patch' for r in rows)} patch)")
    width = max((len(p.name) for p, _, _ in rows), default=10)
    for p, latest, kind in rows:
        print(f"  {kind:<5}  {p.name:<{width}}  {p.version} -> {latest}   ({p.ecosystem}, {p.source})")
    if unpinned:
        print("\nNo exact version in the project (latest shown): " +
              ", ".join(f"{p.name} {latest}" for p, latest in unpinned[:20]))
    for e in errors[:10]:
        print(f"WARNING: {e}")
    print("\nMajor jumps (and 0.x minor jumps) can break the API: read the changelog before upgrading.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
