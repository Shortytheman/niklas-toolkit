#!/usr/bin/env python3
"""Check the machine and project for setup problems that break Claude Code tools, hooks and MCP servers.

Standard library only. Read-only: it reads PATH, git settings, the registry (Windows) and config files, and runs
only `git config`, `git ls-files` and, on Windows, `Get-ExecutionPolicy`. It changes nothing.

    python env_doctor.py [project_dir] [--json]

Checks:
    git-bash            Windows: Git Bash, which Claude Code runs shell commands and hooks with, is missing, or
                        CLAUDE_CODE_GIT_BASH_PATH points at a file that does not exist
    store-python        `python`/`python3` is the Microsoft Store placeholder, which opens the Store
    pyenv-shim          (info) `python` is a pyenv-win .bat shim: multi-line `python -c "..."` arguments break
                        there; scripts in files work
    no-python           neither `python` nor `py` runs
    crlf-shell-script   a tracked .sh file has CRLF line endings in the working tree: bash fails with "\\r"
    eol-risk            core.autocrlf=true and .sh files without an `eol=lf` rule in .gitattributes: the next
                        checkout can give them CRLF
    npx-without-cmd     Windows: an MCP server starts `npx` (or npm, pnpm, yarn, bunx) directly; native Windows
                        needs `cmd /c npx ...` because these are .cmd files
    execution-policy    Windows: PowerShell's policy is Restricted or AllSigned, so .ps1 scripts do not run
    long-paths          (info) Windows: paths over 260 characters are not enabled
    path-missing        (info) a PATH entry that does not exist
    path-duplicate      (info) the same folder twice on PATH

Exit codes: 0 nothing to fix, 1 errors or warnings found.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from claude_home import installed_plugins  # noqa: E402
from hook_doctor import is_store_stub  # noqa: E402
from mcp_cost import configured_servers  # noqa: E402

CMD_LAUNCHERS = {"npx", "npm", "pnpm", "yarn", "bunx"}
RESTRICTIVE_POLICIES = {"Restricted", "AllSigned"}


@dataclass
class Finding:
    severity: str   # error | warning | info
    check: str
    message: str
    fix: str = ""


def run(cmd: list[str], cwd: Path | None = None, timeout: float = 20) -> str | None:
    """stdout of a command, or None when it is missing, fails or hangs."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


# --- PATH ---------------------------------------------------------------------------------------------------------

def check_path(value: str, windows: bool, is_dir: Callable[[str], bool] = os.path.isdir) -> list[Finding]:
    missing, dupes, seen = [], [], set()
    for entry in filter(None, (e.strip() for e in value.split(os.pathsep))):
        expanded = os.path.expandvars(entry)
        key = os.path.normpath(expanded).rstrip("\\/")
        key = key.lower() if windows else key
        if key in seen:
            if entry not in dupes:
                dupes.append(entry)
            continue
        seen.add(key)
        if not is_dir(expanded):
            missing.append(entry)
    out = [Finding("info", "path-missing", f"on PATH but does not exist: {entry}") for entry in missing]
    if dupes:
        out.append(Finding("info", "path-duplicate", f"{len(dupes)} folder(s) on PATH more than once: "
                           + "; ".join(dupes)))
    return out


def registry_path() -> str | None:
    """The PATH Windows builds new processes from (machine, then user), before shells such as Git Bash add their
    own folders. That is the PATH the user can edit, so it is the one worth checking."""
    try:
        import winreg
    except ImportError:
        return None
    parts = []
    for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(hive, sub) as key:
                parts.append(str(winreg.QueryValueEx(key, "Path")[0]))
        except OSError:
            pass
    return os.pathsep.join(parts) if parts else None


# --- Git Bash -----------------------------------------------------------------------------------------------------

def git_bash(which: Callable[[str], str | None] = shutil.which, env: dict | None = None,
             exists: Callable[[Path], bool] = Path.is_file) -> tuple[Path | None, list[Finding]]:
    env = os.environ if env is None else env
    configured = env.get("CLAUDE_CODE_GIT_BASH_PATH")
    if configured:
        if exists(Path(configured)):
            return Path(configured), []
        return None, [Finding("error", "git-bash", f"CLAUDE_CODE_GIT_BASH_PATH is {configured}, which does not exist",
                              "point it at bash.exe in your Git for Windows folder, or remove it")]
    git = which("git")
    if git:
        # <Git>/cmd/git.exe or <Git>/bin/git.exe or <Git>/mingw64/bin/git.exe -> <Git>/bin/bash.exe
        for parent in Path(git).resolve().parents:
            candidate = parent / "bin" / "bash.exe"
            if exists(candidate):
                return candidate, []
    return None, [Finding("error", "git-bash", "Git Bash not found: Claude Code on Windows runs shell commands "
                          "and hooks with it", "install Git for Windows (git-scm.com), or set "
                          "CLAUDE_CODE_GIT_BASH_PATH to bash.exe")]


# --- Python -------------------------------------------------------------------------------------------------------

def check_python(windows: bool, which: Callable[[str], str | None] = shutil.which) -> tuple[list[str], list[Finding]]:
    lines, out = [], []
    working = False
    for name in ("python", "python3", "py") if windows else ("python3", "python"):
        found = which(name)
        if not found:
            continue
        if is_store_stub(found):
            out.append(Finding("error", "store-python", f"'{name}' is the Microsoft Store placeholder ({found})",
                               "install Python from python.org, or turn the alias off: Settings > Apps > Advanced "
                               "app settings > App execution aliases"))
            continue
        lines.append(f"{name}: {found}")
        working = True
        if windows and name == "python" and "pyenv" in found.lower() and "shims" in found.lower():
            out.append(Finding("info", "pyenv-shim", f"'python' is a pyenv-win shim ({found}): multi-line "
                               "`python -c` arguments break in .bat shims", "run scripts from files, or call the "
                               "real interpreter (`pyenv which python`)"))
    if not working:
        out.append(Finding("error", "no-python", "no working python on PATH: the toolkit's scripts need Python 3.10+",
                           "install Python from python.org (tick 'Add to PATH')"))
    return lines, out


# --- line endings -------------------------------------------------------------------------------------------------

def check_line_endings(project: Path) -> tuple[list[str], list[Finding]]:
    if run(["git", "rev-parse", "--is-inside-work-tree"], project) is None:
        return [], []
    autocrlf = (run(["git", "config", "--get", "core.autocrlf"], project) or "").strip() or "unset"
    lines = [f"git core.autocrlf: {autocrlf}"]
    scripts = [s for s in (run(["git", "ls-files", "-z", "--", "*.sh", "*.bash"], project) or "").split("\0") if s]
    out = []
    for rel in scripts:
        try:
            if b"\r\n" in (project / rel).read_bytes():
                out.append(Finding("error", "crlf-shell-script", f"{rel} has Windows line endings: bash fails with "
                                   "'$'\\r': command not found'", "add `*.sh text eol=lf` to .gitattributes, then "
                                   "`git add --renormalize .` and check out the file again"))
        except OSError:
            pass
    if scripts and autocrlf == "true":
        attrs = run(["git", "check-attr", "eol", "--", *scripts], project) or ""
        unguarded = [line.split(":")[0] for line in attrs.splitlines() if not line.rstrip().endswith(": lf")]
        if unguarded:
            out.append(Finding("warning", "eol-risk", f"{len(unguarded)} shell script(s) can get CRLF on checkout "
                               f"(core.autocrlf=true, no eol=lf rule), e.g. {unguarded[0]}",
                               "add `*.sh text eol=lf` to .gitattributes"))
    return lines, out


# --- MCP servers --------------------------------------------------------------------------------------------------

def check_mcp(servers: list) -> list[Finding]:
    out = []
    for s in servers:
        command = str(s.config.get("command", ""))
        if s.config.get("type", "stdio") != "stdio" or not command:
            continue
        program = re.split(r"[\\/]", command)[-1].lower()
        if program in CMD_LAUNCHERS:
            out.append(Finding("warning", "npx-without-cmd", f"MCP server '{s.name}' ({s.origin}) starts "
                               f"'{command}' directly: on native Windows it does not start",
                               f'use "command": "cmd", "args": ["/c", "{command}", ...]'))
    return out


# --- Windows system settings --------------------------------------------------------------------------------------

def long_paths_enabled() -> bool | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return bool(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
    except (ImportError, OSError):
        return None


def execution_policy() -> str | None:
    shell = shutil.which("powershell") or shutil.which("pwsh")
    out = run([shell, "-NoProfile", "-NonInteractive", "-Command", "Get-ExecutionPolicy"], timeout=30) if shell else None
    return out.strip() if out else None


def check_windows_settings(policy: str | None, long_paths: bool | None) -> tuple[list[str], list[Finding]]:
    lines, out = [], []
    if policy:
        lines.append(f"PowerShell execution policy: {policy}")
        if policy in RESTRICTIVE_POLICIES:
            out.append(Finding("warning", "execution-policy", f"PowerShell's execution policy is {policy}: .ps1 "
                               "scripts and hooks will not run", "Set-ExecutionPolicy -Scope CurrentUser "
                               "RemoteSigned (your decision: it is a security setting)"))
    if long_paths is not None:
        lines.append(f"Long paths: {'enabled' if long_paths else 'disabled'}")
        if not long_paths:
            out.append(Finding("info", "long-paths", "paths longer than 260 characters are not enabled; deep "
                               "node_modules or build folders can fail", "enable 'Win32 long paths' (needs admin)"))
    return lines, out


# --- report -------------------------------------------------------------------------------------------------------

def collect(project: Path, windows: bool) -> tuple[list[str], list[Finding]]:
    lines = [f"System: {platform.system()} {platform.version()}, Python {platform.python_version()}"]
    findings: list[Finding] = []
    if windows:
        bash, found = git_bash()
        findings += found
        if bash:
            lines.append(f"Git Bash: {bash}")
    py_lines, found = check_python(windows)
    lines += py_lines
    findings += found
    le_lines, found = check_line_endings(project)
    lines += le_lines
    findings += found
    if windows:
        findings += check_mcp(configured_servers(project, installed_plugins(project)))
        sys_lines, found = check_windows_settings(execution_policy(), long_paths_enabled())
        lines += sys_lines
        findings += found
    findings += check_path((registry_path() if windows else None) or os.environ.get("PATH", ""), windows)
    return lines, findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Check the machine and project for Claude Code setup problems.")
    ap.add_argument("project", nargs="?", default=".", help="project folder (default: .)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    project = Path(a.project).resolve()
    lines, findings = collect(project, platform.system() == "Windows")
    serious = [f for f in findings if f.severity in ("error", "warning")]
    if a.json:
        print(json.dumps({"environment": lines, "findings": [f.__dict__ for f in findings]}, indent=2))
        return 1 if serious else 0

    print("Environment:")
    for line in lines:
        print(f"  {line}")
    print(f"\n{len(serious)} problem(s)" + (":" if serious else ""))
    for f in serious:
        print(f"  {f.severity:<8} {f.check:<18} {f.message}")
        if f.fix:
            print(f"  {'':<8} {'':<18} fix: {f.fix}")
    infos = [f for f in findings if f.severity == "info"]
    if infos:
        print(f"\nNotes ({len(infos)}):")
        for f in infos:
            print(f"  {f.check:<18} {f.message}" + (f"  ({f.fix})" if f.fix else ""))
    return 1 if serious else 0


if __name__ == "__main__":
    sys.exit(main())
