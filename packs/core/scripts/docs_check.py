#!/usr/bin/env python3
"""Check Markdown docs for broken links and for commands that point at files that no longer exist.

Runs without Claude. Standard library only.

    python docs_check.py [project_dir] [--external] [--file README.md ...] [--json]

Checks:
    missing-file    a relative link to a file or folder that does not exist (letter case must match exactly,
                    as it does on Linux and on GitHub, even though Windows does not care)
    missing-anchor  a #fragment that matches no heading in the target file (GitHub's heading slugs)
    missing-script  a script path in a code block (`python tools/x.py`, `./scripts/run.sh`) that does not exist
    dead-url        with --external: an http(s) link that answers 404/410 or does not resolve
                    (401/403/429 are reported as "could not verify", not as dead)

Code blocks and inline code are not scanned for links. Exit codes: 0 clean, 1 problems found, 2 setup problem.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".godot", "target",
             "vendor", ".tox", "site-packages", "research_notes"}
LINK = re.compile(r"(!?)\[(?:[^\[\]]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s+.*)?$")
AUTOLINK = re.compile(r"<(https?://[^>\s]+)>")
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
HTML_ID = re.compile(r"""<a\s+(?:name|id)=["']([^"']+)["']|\sid=["']([^"']+)["']""", re.IGNORECASE)
# A relative script path; not one that continues a variable or absolute path (${ROOT}/scripts/x.py, ~/x/y.py).
SCRIPT_PATH = re.compile(r"""(?<![\w$<{}/~%.-])((?:\.{1,2}/)?[\w.-]+(?:/[\w.-]+)+\.(?:py|sh|ps1|js|mjs|ts|rb|bat|cmd|gd))\b""")


@dataclass
class Problem:
    check: str
    file: str
    line: int
    target: str
    message: str


def github_slug(text: str) -> str:
    """GitHub's heading anchor: lowercase, drop punctuation except - and _, spaces become -."""
    text = re.sub(r"<[^>]+>", "", text)                    # inline HTML
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links keep their text
    text = text.replace("`", "").strip().lower()
    text = re.sub(r"[^\w\- ]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def strip_code(lines: list[str]) -> tuple[list[str], list[tuple[int, str]]]:
    """Lines with code removed (fenced blocks emptied, inline code blanked) and the fenced code lines kept apart."""
    out, code = [], []
    fence = None
    for n, line in enumerate(lines, 1):
        m = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if m:
            if fence is None:
                fence = m.group(1)[0] * len(m.group(1))
            elif line.strip().startswith(fence):
                fence = None
            out.append("")
            continue
        if fence is not None:
            code.append((n, line))
            out.append("")
            continue
        out.append(re.sub(r"`+[^`]*`+", lambda mm: " " * len(mm.group(0)), line))
    return out, code


def anchors_of(path: Path, cache: dict) -> set[str]:
    if path in cache:
        return cache[path]
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        cache[path] = set()
        return cache[path]
    prose, _ = strip_code(lines)
    seen: dict[str, int] = {}
    found = set()
    for line in prose:
        m = HEADING.match(line)
        if m:
            slug = github_slug(m.group(2))
            n = seen.get(slug, 0)
            found.add(slug if n == 0 else f"{slug}-{n}")
            seen[slug] = n + 1
        for a, b in HTML_ID.findall(line):
            found.add(a or b)
    cache[path] = found
    return found


def exists_exact(path: Path) -> bool:
    """True only if every path part exists with exactly this letter case."""
    if not path.exists():
        return False
    try:
        current = Path(path.anchor) if path.is_absolute() else Path(".")
        for part in path.parts[1:] if path.is_absolute() else path.parts:
            if part in (".", ".."):
                current = current / part
                continue
            names = os.listdir(current)
            if part not in names:
                return False
            current = current / part
    except OSError:
        return True
    return True


def find_docs(root: Path) -> list[Path]:
    """Markdown files git tracks or would track (ignored files skipped); a plain folder walk outside git."""
    import subprocess
    try:
        r = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "--", "*.md", "*.markdown"], cwd=root,
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            files = [root / line for line in r.stdout.splitlines() if line.strip()]
            return sorted(f for f in files if f.is_file() and not (set(f.relative_to(root).parts) & SKIP_DIRS))
    except OSError:
        pass
    docs = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        docs += [Path(dirpath) / f for f in files if f.lower().endswith((".md", ".markdown"))]
    return sorted(docs)


def check_file(doc: Path, root: Path, cache: dict, external: list) -> list[Problem]:
    rel = doc.relative_to(root).as_posix()
    lines = doc.read_text(encoding="utf-8", errors="replace").splitlines()
    prose, code = strip_code(lines)
    problems = []
    for n, line in enumerate(prose, 1):
        targets = [m.group(2) for m in LINK.finditer(line)] + [m.group(1) for m in AUTOLINK.finditer(line)]
        ref = REF_DEF.match(line)
        if ref:
            targets.append(ref.group(1))
        for t in targets:
            problems += check_target(t, doc, rel, n, root, cache, external)
    for n, line in code:
        if re.match(r"^\s*(#|//|REM\b)", line):
            continue
        for m in SCRIPT_PATH.finditer(line):
            p = m.group(1)
            if any(ch in line[max(0, m.start() - 1):m.end() + 1] for ch in "<>*{}") or p.startswith(("http", "/")):
                continue
            if not (exists_exact(root / p) or exists_exact(doc.parent / p)):
                problems.append(Problem("missing-script", rel, n, p, f"{p} does not exist (relative to the "
                                                                     f"project root or this file)"))
    return problems


def check_target(t: str, doc: Path, rel: str, n: int, root: Path, cache: dict, external: list) -> list[Problem]:
    if t.startswith(("http://", "https://")):
        external.append((rel, n, t))
        return []
    if re.match(r"^[a-z][a-z0-9+.-]*:", t, re.IGNORECASE):  # mailto:, tel:, vscode:, ...
        return []
    path_part, _, fragment = t.partition("#")
    path_part = urllib.parse.unquote(path_part.split("?")[0])
    if path_part:
        target = (root / path_part.lstrip("/")) if path_part.startswith("/") else (doc.parent / path_part)
        if not exists_exact(target):
            hint = " (exists with different letter case)" if target.exists() else ""
            return [Problem("missing-file", rel, n, t, f"{path_part} does not exist{hint}")]
    else:
        target = doc
    if fragment and target.suffix.lower() in (".md", ".markdown") and target.is_file():
        if urllib.parse.unquote(fragment).lower() not in anchors_of(target, cache) and \
                not re.match(r"^L\d+(-L\d+)?$", fragment):  # GitHub line anchors
            return [Problem("missing-anchor", rel, n, t, f"#{fragment} matches no heading in {target.name}")]
    return []


def check_url(url: str, timeout: float = 10) -> tuple[str, str]:
    """('ok'|'dead'|'unknown', detail)."""
    headers = {"User-Agent": "niklas-toolkit-docs-check/0.5 (+https://github.com/Shortytheman/niklas-toolkit)"}
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return "ok", str(resp.status)
        except urllib.error.HTTPError as e:
            if e.code in (405, 501) and method == "HEAD":
                continue  # server does not allow HEAD: try GET
            if e.code in (404, 410):
                return "dead", f"HTTP {e.code}"
            if e.code in (401, 403, 429) or e.code >= 500:
                return "unknown", f"HTTP {e.code}"
            return "ok", f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            reason = str(getattr(e, "reason", e))
            if "Name or service not known" in reason or "getaddrinfo failed" in reason or "nodename" in reason:
                return "dead", "host does not resolve"
            return "unknown", reason[:80]
    return "unknown", "no answer"


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Check Markdown docs for broken links and stale script paths.")
    ap.add_argument("project", nargs="?", default=".", help="project folder (default: .)")
    ap.add_argument("--file", action="append", help="check only this Markdown file (repeatable)")
    ap.add_argument("--external", action="store_true", help="also check http(s) links (network)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    root = Path(a.project).resolve()
    if not root.is_dir():
        print(f"ERROR: {root} is not a folder", file=sys.stderr)
        return 2
    docs = [Path(f).resolve() for f in a.file] if a.file else find_docs(root)
    if not docs:
        print(f"No Markdown files in {root}.", file=sys.stderr)
        return 2
    cache: dict = {}
    external: list = []
    problems: list[Problem] = []
    for doc in docs:
        problems += check_file(doc, root, cache, external)

    unverified = []
    if a.external and external:
        urls = sorted({u for _, _, u in external})
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = dict(zip(urls, pool.map(check_url, urls)))
        for rel, n, url in external:
            state, detail = results[url]
            if state == "dead":
                problems.append(Problem("dead-url", rel, n, url, detail))
            elif state == "unknown":
                unverified.append((rel, n, url, detail))

    if a.json:
        print(json.dumps({"files": len(docs), "problems": [p.__dict__ for p in problems],
                          "unverified": [{"file": f, "line": n, "url": u, "detail": d} for f, n, u, d in unverified]},
                         indent=2))
        return 1 if problems else 0

    ext = f", {len(external)} external link(s) " + ("checked" if a.external else "not checked (--external)")
    print(f"{root.name}: {len(docs)} Markdown file(s){ext}  |  {len(problems)} problem(s)")
    for p in sorted(problems, key=lambda p: (p.file, p.line)):
        print(f"  {p.file}:{p.line}  {p.check:<14} {p.message}")
    if unverified:
        print(f"\nCould not verify {len(unverified)} link(s) (blocked, rate limited or server error):")
        for f, n, u, d in unverified[:15]:
            print(f"  {f}:{n}  {u}  ({d})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
