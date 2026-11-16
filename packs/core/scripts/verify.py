#!/usr/bin/env python3
"""Run a project's checks (build, lint, tests) in one command and print a short pass/fail summary.

Runs without Claude. Standard library only.

    python verify.py [project_dir] [--list] [--fail-fast] [--only NAME ...] [--tail N]

The checks come from toolkit.json in the project root:

    {"verify": [
        {"name": "lint",  "run": "npm run lint"},
        {"name": "tests", "run": "python -m pytest -q", "timeout": 900}
    ]}

Without that, they are detected: npm scripts (lint, typecheck, build, test), pytest, cargo, go and make.
Each check runs through the shell from the project folder. Output is shown only for failed checks (the last
--tail lines).

Exit codes: 0 every check passed, 1 a check failed, 2 nothing to run or bad setup.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_TIMEOUT = 600


def find_root(start: Path) -> Path:
    markers = ("toolkit.json", ".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "project.godot")
    for d in [start, *start.parents]:
        if any((d / m).exists() for m in markers):
            return d
    return start


def detect(root: Path) -> list[dict]:
    checks: list[dict] = []
    pkg = root / "package.json"
    if pkg.is_file():
        try:
            scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts", {})
        except json.JSONDecodeError:
            scripts = {}
        runner = "pnpm" if (root / "pnpm-lock.yaml").exists() else "yarn" if (root / "yarn.lock").exists() else "npm"
        for name in ("lint", "typecheck", "build", "test"):
            if name in scripts:
                checks.append({"name": name, "run": f"{runner} run {name}" if runner != "yarn" else f"yarn {name}"})
    pyproject = root / "pyproject.toml"
    has_pytest = (root / "pytest.ini").exists() or (root / "conftest.py").exists() or (root / "tests").is_dir() or \
        (pyproject.is_file() and "pytest" in pyproject.read_text(encoding="utf-8", errors="replace"))
    if has_pytest and (pyproject.is_file() or (root / "tests").is_dir() or (root / "setup.py").exists()):
        if shutil.which("ruff") and (pyproject.is_file() and "ruff" in pyproject.read_text(encoding="utf-8")):
            checks.append({"name": "ruff", "run": "ruff check ."})
        checks.append({"name": "pytest", "run": f'"{sys.executable}" -m pytest -q'})
    if (root / "Cargo.toml").is_file():
        checks += [{"name": "cargo build", "run": "cargo build --quiet"},
                   {"name": "cargo test", "run": "cargo test --quiet"}]
    if (root / "go.mod").is_file():
        checks += [{"name": "go vet", "run": "go vet ./..."}, {"name": "go test", "run": "go test ./..."}]
    makefile = root / "Makefile"
    if not checks and makefile.is_file():
        text = makefile.read_text(encoding="utf-8", errors="replace")
        for target in ("lint", "build", "test", "check"):
            if f"\n{target}:" in "\n" + text:
                checks.append({"name": f"make {target}", "run": f"make {target}"})
    return checks


def load_checks(root: Path) -> tuple[list[dict], str]:
    cfg = root / "toolkit.json"
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise SystemExit(f"ERROR: {cfg} is not valid JSON: {e}")
        if "verify" in data:
            checks = data["verify"]
            if not isinstance(checks, list) or not all(isinstance(c, dict) and "run" in c for c in checks):
                raise SystemExit('ERROR: toolkit.json "verify" must be a list of {"name": ..., "run": ...}')
            return checks, "toolkit.json"
    return detect(root), "detected"


def run_check(check: dict, root: Path, tail: int) -> tuple[bool, float, str]:
    timeout = int(check.get("timeout", DEFAULT_TIMEOUT))
    start = time.monotonic()
    try:
        proc = subprocess.run(check["run"], shell=True, cwd=root / check.get("cwd", "."), capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout)
        ok, out = proc.returncode == 0, (proc.stdout + proc.stderr)
        if not ok:
            out += f"\n[exit code {proc.returncode}]"
    except subprocess.TimeoutExpired:
        ok, out = False, f"[timed out after {timeout}s]"
    lines = out.strip().splitlines()
    return ok, time.monotonic() - start, "\n".join(lines[-tail:])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run a project's checks with a short summary.")
    ap.add_argument("project", nargs="?", default=".", help="project folder (default: .)")
    ap.add_argument("--list", action="store_true", help="show the checks without running them")
    ap.add_argument("--fail-fast", action="store_true", help="stop at the first failing check")
    ap.add_argument("--only", action="append", help="run only checks with this name (repeatable)")
    ap.add_argument("--tail", type=int, default=40, help="output lines to show per failed check (default 40)")
    args = ap.parse_args(argv)

    root = find_root(Path(args.project).resolve())
    checks, source = load_checks(root)
    if args.only:
        checks = [c for c in checks if c.get("name") in args.only]
    if not checks:
        print(f"No checks found for {root}. Add them to toolkit.json: "
              '{"verify": [{"name": "tests", "run": "<command>"}]}', file=sys.stderr)
        return 2

    print(f"verify {root.name}: {len(checks)} check(s) from {source}")
    if args.list:
        for c in checks:
            print(f"  {c.get('name', c['run'])}: {c['run']}")
        return 0

    failed = []
    total = time.monotonic()
    for c in checks:
        name = c.get("name", c["run"])
        ok, seconds, out = run_check(c, root, args.tail)
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  ({seconds:.1f}s)", flush=True)
        if not ok:
            failed.append(name)
            print("\n".join("      " + line for line in out.splitlines()))
            if args.fail_fast:
                break
    print(f"{'OK' if not failed else 'FAILED: ' + ', '.join(failed)}  in {time.monotonic() - total:.1f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
