"""Helpers shared by the Godot pack's scripts. Standard library only."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Lines Godot prints for problems. "SCRIPT ERROR" is a GDScript runtime error, "USER ERROR" comes from push_error().
ERROR_LINE = re.compile(r"^\s*(ERROR|SCRIPT ERROR|USER ERROR|Parse Error|Invalid)\b.*", re.IGNORECASE)
WARNING_LINE = re.compile(r"^\s*(WARNING|SCRIPT WARNING|USER WARNING)\b.*", re.IGNORECASE)
# Context lines Godot prints right below an error: "   at: func (res://file.gd:12)" / "   GDScript backtrace ..."
CONTEXT_LINE = re.compile(r"^\s+(at:|\[\d+\]|GDScript backtrace)", re.IGNORECASE)


class SetupError(Exception):
    """Something is wrong before Godot runs: no project, no Godot, bad config. Scripts exit with code 2."""


# ---------------------------------------------------------------- project

def find_project(start: str | Path = ".") -> Path:
    """The folder holding project.godot: `start` itself or the nearest parent."""
    p = Path(start).resolve()
    for d in [p, *p.parents]:
        if (d / "project.godot").is_file():
            return d
    raise SetupError(f"no project.godot in {p} or any parent folder")


def parse_cfg_sections(text: str) -> dict[str, dict[str, str]]:
    """Minimal parser for Godot's .cfg / project.godot format. Values keep their raw text, outer quotes stripped."""
    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    key: str | None = None
    buf: list[str] = []

    def flush():
        nonlocal key, buf
        if current is not None and key is not None:
            value = "\n".join(buf).strip()
            if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                value = value[1:-1]
            current[key] = value
        key, buf = None, []

    for line in text.splitlines():
        if key is not None and _open_quote("\n".join(buf)):
            buf.append(line)  # a multi-line quoted value continues until its quotes balance
            continue
        flush()
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        m = re.match(r"^\[(.+)\]$", stripped)
        if m:
            current = sections.setdefault(m.group(1), {})
            continue
        if "=" in line and current is not None:
            k, _, rest = line.partition("=")
            key, buf = k.strip(), [rest]
    flush()
    return sections


def _open_quote(s: str) -> bool:
    return len(re.findall(r'(?<!\\)"', s)) % 2 == 1


@dataclass
class ProjectInfo:
    path: Path
    name: str
    version: str
    main_scene: str


def read_project(project: Path) -> ProjectInfo:
    sections = parse_cfg_sections((project / "project.godot").read_text(encoding="utf-8"))
    app = sections.get("application", {})
    return ProjectInfo(project, app.get("config/name", project.name), app.get("config/version", ""),
                       app.get("run/main_scene", ""))


def load_toolkit_config(project: Path) -> dict:
    """<project>/toolkit.json: per-project settings for the toolkit scripts. Missing file means no settings."""
    cfg = project / "toolkit.json"
    if not cfg.is_file():
        return {}
    try:
        return json.loads(cfg.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SetupError(f"{cfg} is not valid JSON: {e}") from e


# ---------------------------------------------------------------- godot

def find_godot(explicit: str | None = None, project: Path | None = None) -> Path:
    """Godot from --godot, then $GODOT_BIN, then "godot" in toolkit.json, then godot/godot4 on PATH.

    A folder is accepted too (the Windows download is a folder holding Godot*.exe and Godot*_console.exe);
    the console executable is preferred because it prints to the terminal.
    """
    candidates = [explicit, os.environ.get("GODOT_BIN")]
    if project is not None:
        candidates.append(load_toolkit_config(project).get("godot"))
    for c in candidates:
        if not c:
            continue
        p = Path(os.path.expandvars(os.path.expanduser(c)))
        if p.is_dir():
            found = sorted(p.glob("Godot*_console.exe")) or sorted(p.glob("Godot*.exe")) or sorted(p.glob("Godot*"))
            p = found[0] if found else p
        if p.is_file():
            return p
        raise SetupError(f"Godot not found at {c}")
    for name in ("godot", "godot4"):
        hit = shutil.which(name)
        if hit:
            return Path(hit)
    raise SetupError('Godot not found. Pass --godot, set GODOT_BIN, or add "godot": "<path>" to toolkit.json.')


def godot_version(godot: Path) -> str:
    out = subprocess.run([str(godot), "--headless", "--version"], capture_output=True, text=True, timeout=120)
    lines = out.stdout.strip().splitlines()
    return lines[-1].strip() if lines else ""


@dataclass
class RunOutput:
    code: int
    text: str
    timed_out: bool
    seconds: float


def sandbox_env(project: Path) -> dict[str, str]:
    """Environment that points Godot's user data (user://, saves, settings) at <project>/.godot/toolkit/userdata.

    Tool runs then never read or overwrite the developer's real save files. Godot derives the user data folder
    from APPDATA on Windows, XDG_DATA_HOME / XDG_CONFIG_HOME on Linux, and HOME on macOS.
    """
    root = project / ".godot" / "toolkit" / "userdata"
    root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["APPDATA"] = str(root)
    env["XDG_DATA_HOME"] = str(root / "data")
    env["XDG_CONFIG_HOME"] = str(root / "config")
    env["XDG_CACHE_HOME"] = str(root / "cache")
    if platform.system() == "Darwin":
        env["HOME"] = str(root)
    return env


def run_godot(godot: Path, args: list[str], timeout: int, cwd: Path | None = None,
              env: dict[str, str] | None = None) -> RunOutput:
    """Run Godot, capture stdout+stderr together, never raise on timeout."""
    import time

    start = time.monotonic()
    try:
        proc = subprocess.run([str(godot), *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout, cwd=cwd, env=env)
        return RunOutput(proc.returncode, proc.stdout, False, time.monotonic() - start)
    except subprocess.TimeoutExpired as e:
        out = e.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return RunOutput(-1, out, True, time.monotonic() - start)


# ---------------------------------------------------------------- log digest

@dataclass
class Problem:
    kind: str  # "error" or "warning"
    message: str
    context: list[str]
    count: int = 1

    def render(self) -> str:
        head = f"{self.kind.upper()}: {self.message}" + (f"  (x{self.count})" if self.count > 1 else "")
        return "\n".join([head, *("    " + c for c in self.context)])


ANSI = re.compile(r"\x1b\[[0-9;]*m")
RES_LOCATION = re.compile(r"(\w+) \((res://[^)]+)\)")


def _location(context: list[str]) -> list[str]:
    """Keep the project locations ('res://main.gd:12 in _ready'); fall back to the engine's 'at:' line."""
    found = []
    for line in context:
        m = RES_LOCATION.search(line)
        if m:
            # Parse errors are reported "at: GDScript::reload (res://x.gd:5)": the function name means nothing there.
            loc = m.group(2) if m.group(1) == "reload" else f"{m.group(2)} in {m.group(1)}"
            if loc not in found:
                found.append(loc)
    if found:
        return found[:3]
    return [line for line in context if line.startswith("at:")][:1]


def digest_log(text: str, ignore: list[str] | None = None) -> list[Problem]:
    """Errors and warnings from a Godot log with their project locations; repeats are merged and counted.

    `ignore` holds regular expressions; a problem whose message matches one is dropped.
    """
    ignore_re = [re.compile(p) for p in (ignore or [])]
    problems: list[Problem] = []
    by_key: dict[tuple[str, str, str], Problem] = {}
    current: Problem | None = None
    raw_context: dict[int, list[str]] = {}
    for line in ANSI.sub("", text).splitlines():
        if ERROR_LINE.match(line) or WARNING_LINE.match(line):
            kind = "error" if ERROR_LINE.match(line) else "warning"
            msg = re.sub(r"^\s*(SCRIPT |USER )?(ERROR|WARNING):\s*", "", line.strip(), flags=re.IGNORECASE)
            current = Problem(kind, msg, [])
            problems.append(current)
            raw_context[id(current)] = []
        elif current is not None and (CONTEXT_LINE.match(line) or line.startswith((" ", "\t"))) and line.strip():
            raw_context[id(current)].append(line.strip())
        elif line.strip():
            current = None
    for p in problems:
        p.context = _location(raw_context[id(p)])
    problems = [p for p in problems if not any(r.search(p.message) for r in ignore_re)]
    merged: list[Problem] = []
    for p in problems:
        key = (p.kind, p.message, "|".join(p.context))
        if key in by_key:
            by_key[key].count += 1
        else:
            by_key[key] = p
            merged.append(p)
    return merged
