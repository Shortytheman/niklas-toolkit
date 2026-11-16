#!/usr/bin/env python3
"""Claude Code PostToolUse hook: after an edit to a dependency file, report vulnerabilities the edit introduced.

Reads the hook event as JSON on stdin and does nothing for other files. It audits the file as it is now and as
it was in git HEAD, and reports only vulnerabilities that are new, so existing findings do not repeat on every
edit (dep_audit.py lists everything).

Exit codes follow the hook protocol: 0 nothing new (or the check could not run: an edit is never blocked by a
network problem), 2 new vulnerabilities (stderr goes back to Claude).

By hand:  python deps_hook.py --file path/to/requirements.txt
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
import osv  # noqa: E402
from lockfiles import is_dependency_file, scan  # noqa: E402


def target_from_stdin() -> Path | None:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return None
    file_path = (event.get("tool_input") or {}).get("file_path")
    if not file_path:
        return None
    p = Path(file_path)
    return p if p.is_absolute() else Path(event.get("cwd", ".")) / p


def head_version(path: Path) -> str | None:
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


def vuln_pairs(findings: list[osv.Finding]) -> dict[tuple[str, str], tuple]:
    """(package name, vulnerability id) -> (finding, vuln), so a version change that keeps a vuln is not 'new'."""
    return {(f.package.name, v.id): (f, v) for f in findings for v in f.vulns}


def main(argv: list[str]) -> int:
    path = Path(argv[argv.index("--file") + 1]) if "--file" in argv else target_from_stdin()
    if path is None or not is_dependency_file(path.name) or not path.is_file():
        return 0
    path = path.resolve()
    try:
        now = osv.audit(scan(path.parent, [path]).packages)
        before_text = head_version(path)
        before: list[osv.Finding] = []
        if before_text is not None:
            with tempfile.TemporaryDirectory() as tmp:
                old = Path(tmp) / path.name
                old.write_text(before_text, encoding="utf-8")
                before = osv.audit(scan(Path(tmp), [old]).packages)
    except (netlib.NetError, ValueError, OSError) as e:
        print(f"deps hook: could not check {path.name}: {e}", file=sys.stderr)
        return 0
    old_pairs = vuln_pairs(before)
    new = [(f, v) for key, (f, v) in vuln_pairs(now).items() if key not in old_pairs]
    if not new:
        return 0
    lines = [f"Known vulnerabilities introduced in {path.name}:"]
    ranked = sorted(new, key=lambda fv: (-osv.SEVERITY_ORDER.index(fv[1].severity), fv[0].package.name))
    for f, v in ranked[:8]:
        fix = f"fixed in {', '.join(v.fixed[-2:])}" if v.fixed else "no fix released"
        lines.append(f"  {f.package.name} {f.package.version}: {v.severity.upper()} {v.id} {v.summary[:70]} "
                     f"({fix})")
    if len(ranked) > 8:
        lines.append(f"  ... and {len(ranked) - 8} more; run dep_audit.py for the full list and upgrade targets")
    lines.append("Pick a version without these, or tell the user why this one is needed.")
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
