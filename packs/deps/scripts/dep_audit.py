#!/usr/bin/env python3
"""Check a project's dependencies for known vulnerabilities (OSV.dev, no API key).

Runs without Claude. Standard library only.

    python dep_audit.py [project_dir] [--file PATH ...] [--min-severity low|moderate|high|critical]
                        [--direct-only] [--json]

Reads lockfiles and pinned requirements for PyPI, npm, crates.io, Go, Packagist and RubyGems (see lockfiles.py).
Dependencies without an exact version (ranges in pyproject.toml or package.json with no lockfile) cannot be
checked and are listed as "not checked".

Known findings can be accepted in <project>/toolkit.json:  {"deps": {"ignore": ["GHSA-xxxx-xxxx-xxxx"]}}

Exit codes: 0 nothing at or above --min-severity, 1 vulnerabilities found, 2 setup or network problem.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
import osv  # noqa: E402
from lockfiles import scan  # noqa: E402
from registry import smallest_fix, version_key  # noqa: E402


def upgrade_target(finding: osv.Finding) -> tuple[str, list[str]]:
    """The lowest version that fixes every vulnerability with a released fix, and the ids that have none."""
    current = finding.package.version
    fixes, unfixed = [], []
    for v in finding.vulns:
        fix = smallest_fix(current, v.fixed)
        (fixes.append(fix) if fix else unfixed.append(v.id))
    return (max(fixes, key=version_key) if fixes else ""), unfixed


def load_ignore(root: Path) -> set[str]:
    cfg = root / "toolkit.json"
    if not cfg.is_file():
        return set()
    try:
        return set(json.loads(cfg.read_text(encoding="utf-8")).get("deps", {}).get("ignore", []))
    except json.JSONDecodeError as e:
        raise SystemExit(f"ERROR: {cfg} is not valid JSON: {e}")


def main(argv: list[str] | None = None) -> int:
    netlib.force_utf8_output()
    ap = argparse.ArgumentParser(description="Check dependencies for known vulnerabilities (OSV.dev).")
    ap.add_argument("project", nargs="?", default=".", help="project folder (default: .)")
    ap.add_argument("--file", action="append", help="check only this dependency file (repeatable)")
    ap.add_argument("--min-severity", default="low", choices=osv.SEVERITY_ORDER[1:],
                    help="exit 1 only for findings at or above this (default low: any)")
    ap.add_argument("--direct-only", action="store_true", help="only dependencies the project lists itself")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    root = Path(args.project).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a folder", file=sys.stderr)
        return 2
    files = [Path(f).resolve() for f in args.file] if args.file else None
    if files:
        missing = [str(f) for f in files if not f.is_file()]
        if missing:
            print(f"ERROR: not found: {', '.join(missing)}", file=sys.stderr)
            return 2
    result = scan(root, files)
    packages = [p for p in result.packages if p.direct or not args.direct_only]
    if not result.files:
        print(f"No dependency files found in {root}.", file=sys.stderr)
        return 2

    start = time.monotonic()
    try:
        findings = osv.audit(packages, load_ignore(root))
    except netlib.NetError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    threshold = osv.SEVERITY_ORDER.index(args.min_severity)
    failing = [f for f in findings if osv.SEVERITY_ORDER.index(f.worst) >= threshold or f.worst == "unknown"]

    if args.json:
        print(json.dumps({
            "files": result.files, "checked": len(packages), "not_checked": [p.name for p in result.unpinned],
            "findings": [{"ecosystem": f.package.ecosystem, "name": f.package.name, "version": f.package.version,
                          "direct": f.package.direct, "source": f.package.source,
                          "vulns": [v.__dict__ for v in f.vulns]} for f in findings],
            "problems": result.problems}, indent=2))
        return 1 if failing else 0

    vuln_count = sum(len(f.vulns) for f in findings)
    print(f"{root.name}: {len(packages)} package(s) from {len(result.files)} file(s) checked in "
          f"{time.monotonic() - start:.1f}s  |  {vuln_count} known vulnerabilit{'y' if vuln_count == 1 else 'ies'} "
          f"in {len(findings)} package(s)")
    for f in sorted(findings, key=lambda f: (-osv.SEVERITY_ORDER.index(f.worst), f.package.name)):
        p = f.package
        print(f"\n{p.name} {p.version}  ({p.ecosystem}, {'direct' if p.direct else 'transitive'}, {p.source})")
        for v in f.vulns:
            score = f" {v.score:.1f}" if v.score is not None else ""
            fix = f"fixed in {', '.join(v.fixed[-3:])}" if v.fixed else "no fixed version yet"
            alias = f" ({', '.join(v.aliases[:2])})" if v.aliases else ""
            print(f"  {v.severity.upper()}{score}  {v.id}{alias}  {fix}")
            if v.summary:
                print(f"      {v.summary[:110]}")
        target, unfixed = upgrade_target(f)
        if target:
            print(f"  -> upgrading to {target} fixes " + ("all of these" if not unfixed else
                                                          f"all but {', '.join(unfixed)} (no fix released yet)"))
    if result.unpinned:
        names = ", ".join(sorted({p.name for p in result.unpinned})[:15])
        more = f" and {len(result.unpinned) - 15} more" if len(result.unpinned) > 15 else ""
        print(f"\nNot checked, no exact version (add a lockfile): {names}{more}")
    for problem in result.problems:
        print(f"WARNING: {problem}")
    print("\nSource: OSV.dev (https://osv.dev). Details: https://osv.dev/vulnerability/<id>")
    return 1 if failing else 0


if __name__ == "__main__":
    sys.exit(main())
