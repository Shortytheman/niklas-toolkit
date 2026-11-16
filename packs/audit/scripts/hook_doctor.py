#!/usr/bin/env python3
"""Find Claude Code hooks that will fail, with a focus on Windows, plus the environment problems behind them.

Runs without Claude. Standard library only. Read-only: it reads settings and plugin files and runs no hook.

    python hook_doctor.py [project_dir] [--json]

Checks every command hook from user/project/local settings and from enabled plugins:
    missing-program     the command's program is not on PATH (common: jq, python3, bash on a clean Windows)
    store-python        `python3`/`python` resolves to the Microsoft Store placeholder, which opens the Store
                        instead of running anything
    missing-file        a script the command names does not exist (often ${CLAUDE_PLUGIN_ROOT} paths)
    crlf-script         a .sh script with Windows line endings: bash fails with "\\r: command not found"
    bad-matcher         the matcher is not a valid regular expression
    no-timeout          (info) no timeout set: the default is 60 seconds
And the environment: Git Bash present (Claude Code on Windows runs hooks with it), Python version.

Exit codes: 0 no problems, 1 problems found, 2 nothing to check.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_home import installed_plugins, settings_hooks  # noqa: E402

SHELL_WORDS = {"if", "then", "else", "fi", "for", "do", "done", "while", "case", "esac", "exit", "echo", "test",
               "[", "true", "false", "cd", "export", "set", "source", "."}


@dataclass
class Problem:
    severity: str   # error | warning | info
    check: str
    where: str
    message: str


def is_store_stub(path: str) -> bool:
    """The Microsoft Store 'App execution alias' placeholders live in WindowsApps and are 0-byte reparse points."""
    p = Path(path)
    return "WindowsApps" in p.parts and (not p.exists() or p.stat().st_size == 0)


def resolve_program(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if platform.system() == "Windows" and not name.lower().endswith((".exe", ".cmd", ".bat")):
        for ext in (".exe", ".cmd", ".bat"):
            found = shutil.which(name + ext)
            if found:
                return found
    return None


def programs_in(command: str) -> list[str]:
    """The programs a shell command runs: the first word of each pipeline stage and && / || / ; part."""
    out = []
    for part in re.split(r"\|\||&&|[|;]|\$\(|`", command):
        part = part.strip()
        if not part:
            continue
        try:
            words = shlex.split(part, posix=True)
        except ValueError:
            words = part.split()
        # leading keywords ("then node x.js") and VAR=value prefixes are not the program
        while words and (words[0] in ("if", "then", "else", "elif", "do", "while", "until", "!", "time")
                         or re.match(r"^\w+=", words[0])):
            words = words[1:]
        if words and words[0] not in SHELL_WORDS and not words[0].startswith(("$", "-", "<", ">", "2>")):
            out.append(words[0])
    return out


def paths_in(command: str, plugin_root: Path | None) -> list[Path]:
    text = command
    if plugin_root is not None:
        text = text.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_root)).replace("$CLAUDE_PLUGIN_ROOT", str(plugin_root))
    found = []
    for token in re.findall(r'"([^"]+)"|(\S+)', text):
        t = token[0] or token[1]
        if re.search(r"\.(py|sh|ps1|js|mjs|cjs|ts|rb|bat|cmd)$", t, re.IGNORECASE) and "$" not in t:
            found.append(Path(t))
    return found


def check_hooks(hooks: dict, where: str, plugin_root: Path | None, project: Path) -> list[Problem]:
    problems = []
    for event, groups in (hooks or {}).items():
        for group in groups or []:
            matcher = group.get("matcher", "")
            if matcher:
                try:
                    re.compile(matcher)
                except re.error as e:
                    problems.append(Problem("error", "bad-matcher", f"{where} {event}", f"matcher {matcher!r}: {e}"))
            for hook in group.get("hooks", []) or []:
                if hook.get("type") != "command":
                    continue
                cmd = hook.get("command", "")
                label = f"{where} {event}" + (f" [{matcher}]" if matcher else "")
                for prog in programs_in(cmd):
                    if "${CLAUDE_PLUGIN_ROOT}" in prog or "/" in prog or "\\" in prog:
                        continue  # a path: checked below
                    found = resolve_program(prog)
                    if not found:
                        problems.append(Problem("error", "missing-program", label,
                                                f"'{prog}' is not on PATH, so `{cmd[:80]}` fails"))
                    elif is_store_stub(found):
                        problems.append(Problem("error", "store-python", label,
                                                f"'{prog}' is the Microsoft Store placeholder ({found}); install "
                                                f"Python or turn off the alias in Settings > Apps > App execution aliases"))
                for path in paths_in(cmd, plugin_root):
                    full = path if path.is_absolute() else project / path
                    if not full.exists():
                        problems.append(Problem("error", "missing-file", label, f"{full} does not exist"))
                    elif full.suffix == ".sh" and b"\r\n" in full.read_bytes()[:4096]:
                        problems.append(Problem("error", "crlf-script", label,
                                                f"{full.name} has Windows line endings; bash will fail. Add "
                                                f"'*.sh text eol=lf' to .gitattributes and re-checkout"))
                if "timeout" not in hook:
                    problems.append(Problem("info", "no-timeout", label, "no timeout set (default 60 s)"))
    return problems


def environment() -> list[str]:
    lines = [f"Python {platform.python_version()} at {sys.executable}"]
    if platform.system() == "Windows":
        bash = shutil.which("bash")
        git = shutil.which("git")
        lines.append(f"Git Bash: {bash or 'not found'}" + ("" if bash else
                     " (Claude Code on Windows needs Git for Windows to run shell hooks)"))
        if git:
            r = subprocess.run(["git", "config", "--get", "core.autocrlf"], capture_output=True, text=True)
            lines.append(f"git core.autocrlf: {r.stdout.strip() or 'unset'}")
        for name in ("python3", "python"):
            found = shutil.which(name)
            if found and is_store_stub(found):
                lines.append(f"WARNING: '{name}' on PATH is the Microsoft Store placeholder ({found})")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check Claude Code hooks for problems (Windows-aware).")
    ap.add_argument("project", nargs="?", default=".", help="project folder (default: .)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    project = Path(a.project).resolve()
    problems: list[Problem] = []
    sources = 0
    for label, hooks in settings_hooks(project):
        if hooks:
            sources += 1
            problems += check_hooks(hooks, label, None, project)
    for p in installed_plugins(project):
        if p.enabled and p.hooks:
            sources += 1
            problems += check_hooks(p.hooks, p.key, p.path, project)

    if a.json:
        print(json.dumps({"hook_sources": sources, "problems": [pr.__dict__ for pr in problems],
                          "environment": environment()}, indent=2))
        return 1 if any(pr.severity == "error" for pr in problems) else 0

    errors = [pr for pr in problems if pr.severity == "error"]
    infos = [pr for pr in problems if pr.severity == "info"]
    print(f"{project.name}: {sources} hook source(s) checked  |  {len(errors)} problem(s)\n")
    for pr in errors:
        print(f"  {pr.check:<16} {pr.where}\n                   {pr.message}")
    if infos:
        print(f"\n  {len(infos)} hook(s) without a timeout (default 60 s): " +
              ", ".join(sorted({pr.where for pr in infos})))
    print("\nEnvironment:")
    for line in environment():
        print(f"  {line}")
    if not sources:
        print("\nNo hooks configured.")
        return 2
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
