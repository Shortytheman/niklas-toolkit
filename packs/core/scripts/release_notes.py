#!/usr/bin/env python3
"""Draft release notes from the git history since the last tag, and suggest the next version.

Runs without Claude. Standard library only (calls git).

    python release_notes.py [project_dir] [--since TAG] [--version X.Y.Z] [--write]

- Commits since the last tag (or --since) are grouped: Breaking, Added, Fixed, Changed, Docs, Other. Conventional
  commit prefixes (feat:, fix:, docs:, refactor:, perf:, chore:, ...) are used when present; otherwise the first
  word decides (Add/New -> Added, Fix -> Fixed, ...). Merge commits and version-bump commits are left out.
- The suggested version follows semver from the last tag: a breaking change bumps major (minor while 0.x), an
  addition bumps minor, anything else patch. Without a version tag there is no suggestion: pass --version.
- --write puts the section at the top of CHANGELOG.md (created if missing). Without it, nothing is written.

The draft is a starting point: commit subjects are written for developers, release notes for users.
Exit codes: 0 ok, 1 no commits since the tag, 2 not a git repository.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

GROUPS = ["Breaking", "Added", "Fixed", "Changed", "Docs", "Other"]
CONVENTIONAL = {"feat": "Added", "fix": "Fixed", "perf": "Changed", "refactor": "Changed", "docs": "Docs",
                "style": "Other", "test": "Other", "build": "Other", "ci": "Other", "chore": "Other",
                "revert": "Changed"}
# The first word decides the group; (?![\w-]) so that "docs-check, ..." is not read as "docs".
WORDS = [(r"^(add|adds|added|new|introduce|support)(?![\w-])", "Added"),
         (r"^(fix|fixes|fixed|repair|correct)(?![\w-])", "Fixed"),
         (r"^(docs?|readme|document)(?![\w-])", "Docs"),
         (r"^(update|change|improve|refactor|rename|move|remove|drop|speed|make|use)(?![\w-])", "Changed")]
SKIP = re.compile(r"^(Merge (branch|pull request|remote)|v?\d+\.\d+\.\d+$|(Bump|Release|Version) v?\d+\.\d+)",
                  re.IGNORECASE)


def git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"git {' '.join(args)} failed")
    return r.stdout


def last_tag(root: Path) -> str | None:
    try:
        return git(root, "describe", "--tags", "--abbrev=0").strip() or None
    except RuntimeError:
        return None


def commits(root: Path, since: str | None) -> list[tuple[str, str, str]]:
    """(short hash, subject, body) oldest first."""
    rng = f"{since}..HEAD" if since else "HEAD"
    out = git(root, "log", rng, "--no-merges", "--reverse", "--format=%h%x1f%s%x1f%b%x1e")
    result = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if rec:
            h, subject, body = (rec.split("\x1f") + ["", ""])[:3]
            result.append((h, subject.strip(), body.strip()))
    return result


def classify(subject: str, body: str) -> tuple[str, str]:
    """(group, cleaned subject)."""
    m = re.match(r"^(\w+)(\([^)]*\))?(!)?:\s*(.+)$", subject)
    breaking = "BREAKING CHANGE" in body or "BREAKING-CHANGE" in body
    if m and m.group(1).lower() in CONVENTIONAL:
        text = m.group(4)
        scope = m.group(2)[1:-1] if m.group(2) else ""
        text = f"{scope}: {text}" if scope else text
        if m.group(3) or breaking:
            return "Breaking", text
        return CONVENTIONAL[m.group(1).lower()], text
    if breaking:
        return "Breaking", subject
    for pattern, group in WORDS:
        if re.match(pattern, subject, re.IGNORECASE):
            return group, subject
    return "Other", subject


def next_version(tag: str | None, groups: dict[str, list]) -> str:
    """The next semver after `tag`, or "" when there is no version to start from."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", tag or "")
    if not m:
        return ""
    major, minor, patch = (int(x) for x in m.groups())
    if groups["Breaking"]:
        return f"{major + 1}.0.0" if major > 0 else f"0.{minor + 1}.0"   # 0.x: breaking changes bump the minor
    if groups["Added"]:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def render(version: str, groups: dict[str, list]) -> str:
    lines = [f"## {version} ({date.today().isoformat()})", ""]
    for g in GROUPS:
        if groups[g]:
            lines.append(f"### {g}")
            lines.append("")
            lines += [f"- {text[0].upper() + text[1:]} ({h})" for h, text in groups[g]]
            lines.append("")
    return "\n".join(lines)


def write_changelog(path: Path, section: str) -> None:
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        m = re.search(r"^## ", text, re.MULTILINE)
        text = text[:m.start()] + section + "\n" + text[m.start():] if m else text.rstrip() + "\n\n" + section
    else:
        text = "# Changelog\n\n" + section
    path.write_text(text, encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Draft release notes from git history since the last tag.")
    ap.add_argument("project", nargs="?", default=".", help="project folder (default: .)")
    ap.add_argument("--since", help="tag or commit to start after (default: the last tag)")
    ap.add_argument("--version", help="version for the heading (default: suggested from the commits)")
    ap.add_argument("--write", action="store_true", help="add the section to the top of CHANGELOG.md")
    a = ap.parse_args(argv)

    root = Path(a.project).resolve()
    try:
        git(root, "rev-parse", "--is-inside-work-tree")
        since = a.since or last_tag(root)
        found = commits(root, since)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    groups: dict[str, list] = {g: [] for g in GROUPS}
    for h, subject, body in found:
        if SKIP.match(subject):
            continue
        group, text = classify(subject, body)
        groups[group].append((h, text))
    if not any(groups.values()):
        print(f"No commits since {since or 'the beginning'}.")
        return 1

    base = since if since and re.search(r"\d+\.\d+\.\d+", since) else last_tag(root)
    suggested = next_version(base, groups)
    version = a.version or suggested or "Unreleased"
    section = render(version, groups)
    advice = f"Suggested version: {suggested}" if suggested else "No version tag to start from: pass --version"
    print(f"Since {since or 'the first commit'}: {sum(len(v) for v in groups.values())} change(s). {advice}"
          + (f" (using {version})" if a.version else "") + "\n")
    print(section)
    if a.write:
        write_changelog(root / "CHANGELOG.md", section)
        print(f"Added to {root / 'CHANGELOG.md'}. Edit the wording for users before releasing.")
    else:
        print("(dry run: add --write to put this at the top of CHANGELOG.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
