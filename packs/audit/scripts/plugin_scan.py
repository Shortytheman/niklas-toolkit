#!/usr/bin/env python3
"""Static risk scan of Claude Code plugins: patterns that do not belong in a plugin you trust with your machine.

Runs without Claude. Standard library only. Read-only: files are read as text, nothing is executed.

    python plugin_scan.py [project_dir]        plugins installed for this project
    python plugin_scan.py --all                every installed plugin
    python plugin_scan.py --path DIR           a plugin folder you are about to install

Findings (severity):
    remote-exec     (high)    download-and-run: curl/wget piped into a shell, iwr | iex, Invoke-Expression on a download
    obfuscated      (high)    decoding and running hidden code (base64 -d | sh, exec(b64decode(...)), eval(atob(...)))
    secrets-access  (high)    reads SSH keys, cloud credentials, .netrc, browser login/cookie stores, OS keychains
    destructive     (high)    deletes from the root, home or a whole drive
    prompt-steering (high)    instructions in skills/agents that tell Claude to hide things from the user, ignore
                              earlier instructions, or skip permission prompts
    hook-network    (medium)  a hook command that talks to the network (runs automatically on every matching event)
    env-dump        (medium)  dumps all environment variables (may contain tokens)
    long-blob       (info)    a long base64-like string in a script

A finding is a reason to read that file, not proof of bad intent: many legitimate tools download things. The scan
cannot see code that is fetched at run time. Exit codes: 0 nothing high, 1 high findings, 2 nothing to scan.

A file that contains the marker "plugin-scan: pattern-definitions" (like this one, which must spell out the
patterns it looks for) still has its findings listed, but as info, labelled as such: a marker can lower the
severity, never hide a finding, so a malicious plugin gains nothing by copying it.
"""
# plugin-scan: pattern-definitions
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_home import claude_dir, installed_plugins, read_json  # noqa: E402

TEXT_EXTS = {".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".ps1", ".psm1", ".bat", ".cmd", ".rb",
             ".md", ".json", ".toml", ".yaml", ".yml"}
CODE_EXTS = TEXT_EXTS - {".md", ".json", ".toml", ".yaml", ".yml"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "tests", "test", "fixtures", ".venv"}

RULES = [
    ("remote-exec", "high", CODE_EXTS | {".json", ".md"},
     r"(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z)?sh\b|(iwr|Invoke-WebRequest|irm|Invoke-RestMethod)\b[^\n|]*\|\s*(iex|Invoke-Expression)"
     r"|Invoke-Expression\s*\(?\s*\(?\s*(New-Object\s+Net\.WebClient|iwr|irm|Invoke-WebRequest)"),
    ("obfuscated", "high", CODE_EXTS | {".json"},
     r"base64\s+(-d|--decode)[^\n]*\|\s*(ba)?sh|exec\s*\(\s*(base64\.)?b64decode|eval\s*\(\s*(atob|Buffer\.from)\s*\("
     r"|FromBase64String[^\n]*(Invoke-Expression|iex)|powershell(\.exe)?\s+[^\n]*-e(nc|ncodedcommand)?\s+[A-Za-z0-9+/=]{40,}"),
    ("secrets-access", "high", CODE_EXTS | {".json"},
     r"\.ssh[/\\](id_|authorized_keys|known_hosts)|\.aws[/\\]credentials|\.netrc\b|\.docker[/\\]config\.json"
     r"|Login Data|Cookies\.sqlite|[/\\]Cookies\b|Local State|security\s+find-(generic|internet)-password"
     r"|\.config[/\\]gcloud|\.azure[/\\]|\.kube[/\\]config|\.git-credentials"),
    ("destructive", "high", CODE_EXTS | {".json"},
     r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+(/|~|\$HOME|/\*)(\s|$|;)|rm\s+-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+(/|~|\$HOME)(\s|$|;)"
     r"|Remove-Item\s+[^\n]*-Recurse[^\n]*\s(C:\\?|\$env:USERPROFILE|~)\s*($|-)|del\s+/[sq]\s+/[sq]\s+[A-Z]:\\\s*$|format\s+[A-Z]:"),
    ("prompt-steering", "high", {".md"},
     r"ignore (all |any )?(previous|prior|earlier) instructions|do not (tell|inform|show) the user|without (telling|asking) the user"
     r"|hide (this|it) from the user|--dangerously-skip-permissions|bypass (the )?permission|disable (all )?(safety|permission)"),
    ("env-dump", "medium", CODE_EXTS,
     r"(^|[;|&(]\s*)(printenv|env)\s*(\||>)|^\s*printenv\s*$|Get-ChildItem\s+env:\s*(\||>)"
     r"|json\.dumps\(\s*(dict\()?os\.environ|JSON\.stringify\(\s*process\.env\s*\)"),
]
NETWORK = re.compile(r"\b(curl|wget|Invoke-WebRequest|iwr|irm|Invoke-RestMethod|nc|ncat|netcat)\b|https?://")
BLOB = re.compile(r"[A-Za-z0-9+/]{240,}={0,2}")
COMPILED = [(name, sev, exts, re.compile(rx, re.IGNORECASE | re.MULTILINE)) for name, sev, exts, rx in RULES]


@dataclass
class Finding:
    severity: str
    rule: str
    plugin: str
    file: str
    line: int
    snippet: str


def scan_dir(root: Path, label: str) -> list[Finding]:
    findings = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in TEXT_EXTS or set(f.relative_to(root).parts) & SKIP_DIRS:
            continue
        if f.stat().st_size > 1_000_000:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = f.relative_to(root).as_posix()
        lines = text.splitlines()
        declared = "plugin-scan: pattern-definitions" in text
        for name, sev, exts, rx in COMPILED:
            if f.suffix.lower() not in exts:
                continue
            for m in rx.finditer(text):
                n = text.count("\n", 0, m.start()) + 1
                snippet = lines[n - 1].strip()[:140] if n <= len(lines) else ""
                if declared:
                    findings.append(Finding("info", f"{name} (declared pattern file)", label, rel, n, snippet))
                else:
                    findings.append(Finding(sev, name, label, rel, n, snippet))
        if f.suffix.lower() in CODE_EXTS:
            for m in BLOB.finditer(text):
                n = text.count("\n", 0, m.start()) + 1
                findings.append(Finding("info", "long-blob", label, rel, n, m.group(0)[:40] + "..."))
    hooks = read_json(root / "hooks" / "hooks.json").get("hooks", {}) or {}
    for event, groups in hooks.items():
        for group in groups or []:
            for hook in group.get("hooks", []) or []:
                cmd = hook.get("command", "")
                if hook.get("type") == "command" and NETWORK.search(cmd):
                    findings.append(Finding("medium", "hook-network", label, "hooks/hooks.json", 0,
                                            f"{event}: {cmd[:120]}"))
    return findings


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Static risk scan of Claude Code plugins.")
    ap.add_argument("project", nargs="?", default=".", help="project whose plugins to scan (default: .)")
    ap.add_argument("--all", action="store_true", help="every installed plugin, any project")
    ap.add_argument("--path", action="append", help="scan this plugin folder (repeatable)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    targets: list[tuple[Path, str]] = []
    if a.path:
        targets = [(Path(p).resolve(), Path(p).resolve().name) for p in a.path]
    else:
        plugins = installed_plugins(None if a.all else Path(a.project).resolve())
        if a.all:  # installed_plugins(None) returns only user-scope ones; add the rest
            data = read_json(claude_dir() / "plugins" / "installed_plugins.json")
            seen = {p.path for p in plugins}
            for key, entries in (data.get("plugins") or {}).items():
                for e in entries if isinstance(entries, list) else [entries]:
                    path = Path(e.get("installPath", ""))
                    if path.is_dir() and path not in seen:
                        targets.append((path, key))
                        seen.add(path)
        targets += [(p.path, p.key) for p in plugins]
    targets = [(p, l) for p, l in targets if p.is_dir()]
    if not targets:
        print("Nothing to scan: no installed plugins found (or the --path folder does not exist).", file=sys.stderr)
        return 2

    findings = [f for path, label in targets for f in scan_dir(path, label)]
    order = {"high": 0, "medium": 1, "info": 2}
    findings.sort(key=lambda f: (order[f.severity], f.plugin, f.file, f.line))
    if a.json:
        print(json.dumps({"scanned": [l for _, l in targets], "findings": [f.__dict__ for f in findings]}, indent=2))
        return 1 if any(f.severity == "high" for f in findings) else 0

    counts = {s: sum(f.severity == s for f in findings) for s in order}
    print(f"{len(targets)} plugin(s) scanned  |  {counts['high']} high, {counts['medium']} medium, {counts['info']} info\n")
    for f in findings:
        where = f"{f.file}:{f.line}" if f.line else f.file
        print(f"  {f.severity.upper():<6} {f.rule:<16} {f.plugin}  {where}\n         {f.snippet}")
    if not findings:
        print("  No risky patterns found.")
    print("\nA finding is a reason to read that file, not proof of bad intent. Code fetched at run time is not "
          "visible to this scan.")
    return 1 if counts["high"] else 0


if __name__ == "__main__":
    sys.exit(main())
