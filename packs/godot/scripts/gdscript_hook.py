#!/usr/bin/env python3
"""Claude Code PostToolUse hook: lint (and optionally format) a GDScript file right after Claude edits it.

Reads the hook event as JSON on stdin. Does nothing for files that are not .gd.

Lint reports only problems the edit introduced: it lints the file as it is now and as it was in git HEAD, and
shows the problems that are new (compared by rule and message, not line number, so moved code is not "new").
A new or untracked file has every problem counted as new. Syntax errors are always reported.

Exit codes follow the hook protocol: 0 nothing to say, 2 problems found (stderr goes back to Claude),
1 hook could not run (stderr shown to the user only).

Per-project settings in toolkit.json:
    {"gdscript": {"format": false, "lint": true, "disable": ["max-line-length"]}}
"format": true runs gdformat on the file after each edit; use it only in codebases that are already
gdformat-clean, or the first edit to each file reformats all of it.

Also works by hand:  python gdscript_hook.py --file path/to/script.gd
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from godot_common import SetupError, find_project, load_toolkit_config  # noqa: E402

LINT_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+): (?P<level>\w+): (?P<msg>.*?)(?: \((?P<rule>[a-z-]+)\))?$")


def gdtoolkit_available() -> bool:
    r = subprocess.run([sys.executable, "-m", "gdtoolkit.linter", "--version"], capture_output=True, text=True)
    return r.returncode == 0


def lint(path: Path, cwd: Path) -> list[dict]:
    """gdlint problems for one file. A syntax error comes back as a problem with rule 'syntax'."""
    r = subprocess.run([sys.executable, "-m", "gdtoolkit.linter", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=cwd)
    problems = []
    for line in (r.stdout + r.stderr).splitlines():
        m = LINT_LINE.match(line.strip())
        if m:
            problems.append({"line": int(m["line"]), "msg": m["msg"], "rule": m["rule"] or "other"})
    if r.returncode != 0 and not problems:
        # A parse failure prints the source line, a caret, then "Unexpected token ... at line N, column M."
        text = (r.stdout + r.stderr).strip()
        m = re.search(r"^(Unexpected .*?|.*[Ee]rror.*?) at line (\d+), column (\d+)\.?$", text, re.MULTILINE)
        if m:
            problems.append({"line": int(m.group(2)), "msg": f"syntax error: {m.group(1)}", "rule": "syntax"})
        else:
            tail = [l for l in text.splitlines() if l.strip() and not l.startswith("Failure")][-3:]
            problems.append({"line": 0, "msg": "syntax error: " + " | ".join(tail), "rule": "syntax"})
    return problems


def head_version(path: Path) -> str | None:
    """The file's content in git HEAD, or None when it is new, untracked, or not in a git repo."""
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                              cwd=path.parent).stdout.strip()
        if not root:
            return None
        rel = path.resolve().relative_to(Path(root).resolve()).as_posix()
        r = subprocess.run(["git", "show", f"HEAD:{rel}"], capture_output=True, cwd=root)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None
    except (OSError, ValueError):
        return None


def new_problems(path: Path, cwd: Path) -> list[dict]:
    after = lint(path, cwd)
    if not after:
        return []
    before_text = head_version(path)
    if before_text is None:
        return after
    with tempfile.TemporaryDirectory() as tmp:
        old = Path(tmp) / path.name
        old.write_text(before_text, encoding="utf-8")
        before = lint(old, cwd)
    budget = Counter((p["rule"], p["msg"]) for p in before)
    fresh = []
    for p in after:
        key = (p["rule"], p["msg"])
        if p["rule"] == "syntax":
            fresh.append(p)
        elif budget[key] > 0:
            budget[key] -= 1
        else:
            fresh.append(p)
    return fresh


def format_file(path: Path, cwd: Path) -> str | None:
    r = subprocess.run([sys.executable, "-m", "gdtoolkit.formatter", str(path)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=cwd)
    return None if r.returncode == 0 else (r.stderr or r.stdout).strip()


def target_from_stdin() -> Path | None:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return None
    tool_input = event.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return None
    p = Path(file_path)
    if not p.is_absolute():
        p = Path(event.get("cwd", ".")) / p
    return p


def main(argv: list[str]) -> int:
    path = Path(argv[argv.index("--file") + 1]) if "--file" in argv else target_from_stdin()
    if path is None or path.suffix != ".gd" or not path.is_file():
        return 0
    path = path.resolve()
    try:
        project = find_project(path.parent)
        settings = load_toolkit_config(project).get("gdscript", {})
    except SetupError:
        project, settings = path.parent, {}

    if not gdtoolkit_available():
        print('GDScript hook: gdtoolkit is not installed. Run: python -m pip install "gdtoolkit==4.*"',
              file=sys.stderr)
        return 1

    if settings.get("format"):
        err = format_file(path, project)
        if err:  # gdformat refuses files with syntax errors; lint below reports those
            pass

    if not settings.get("lint", True):
        return 0
    disabled = set(settings.get("disable", []))
    problems = [p for p in new_problems(path, project) if p["rule"] not in disabled]
    if not problems:
        return 0

    rel = path.relative_to(project) if path.is_relative_to(project) else path
    syntax = [p for p in problems if p["rule"] == "syntax"]
    lines = [f"GDScript problems introduced in {rel}:"]
    for p in sorted(problems, key=lambda p: p["line"])[:15]:
        lines.append(f"  line {p['line']}: {p['msg']} ({p['rule']})")
    if len(problems) > 15:
        lines.append(f"  ... and {len(problems) - 15} more")
    lines.append("Fix the syntax error now." if syntax else
                 "Fix these unless they are intended; existing problems from before the edit are not listed.")
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
