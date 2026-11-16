#!/usr/bin/env python3
"""Run the brief every morning without opening Claude: shows (or, with --create, makes) a scheduled task.

    python schedule_brief.py                  show the command for a daily brief at 07:30
    python schedule_brief.py --time 06:45     another time
    python schedule_brief.py --create         Windows: create the task with schtasks (you can remove it with --remove)
    python schedule_brief.py --remove         Windows: delete the task

Each run executes `brief.py --save`, which writes <toolkit folder>/briefs/brief-YYYY-MM-DD.md. On Linux and macOS
this prints a crontab line to add with `crontab -e`; it never edits your crontab.

Creating a scheduled task changes your system, so nothing is created without --create. The task runs a small
launcher, <toolkit folder>/run_brief.py, which picks the newest installed version of the brief plugin each
morning, so plugin updates do not break the task. Its output goes to briefs/last-run.log.
Exit codes: 0 ok, 1 schtasks failed, 2 bad arguments.
"""
from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402

TASK = "niklas-toolkit brief"
BRIEF = Path(__file__).resolve().parent / "brief.py"

# Written to <toolkit folder>/run_brief.py. Installed plugins live in .../plugins/cache/<marketplace>/brief/<version>/,
# and an update adds a new version folder, so the launcher looks for the newest one instead of a fixed path.
LAUNCHER = '''# Written by schedule_brief.py. Runs the newest installed brief plugin with --save; output goes to briefs/last-run.log.
import re, runpy, sys, traceback
from pathlib import Path

FALLBACK = Path({fallback!r})


def newest():
    if len(FALLBACK.parents) < 5 or FALLBACK.parents[4].name != "cache":   # a source checkout: use it as it is
        return FALLBACK
    found = []
    for p in FALLBACK.parents[2].glob("*/scripts/brief.py"):
        m = re.fullmatch(r"(\\d+)\\.(\\d+)\\.(\\d+)", p.parents[1].name)
        if m:   # Claude Code marks replaced versions with .orphaned_at before deleting them
            current = not (p.parents[1] / ".orphaned_at").exists()
            found.append((current, tuple(int(x) for x in m.groups()), str(p)))
    return Path(max(found)[2]) if found else FALLBACK


log_dir = Path(__file__).resolve().parent / "briefs"
log_dir.mkdir(parents=True, exist_ok=True)
with open(log_dir / "last-run.log", "w", encoding="utf-8") as log:
    sys.stdout = sys.stderr = log
    brief = newest()
    print(f"Running {{brief}}")
    sys.path.insert(0, str(brief.parent))
    sys.argv = [str(brief), "--save"]
    try:
        runpy.run_path(str(brief), run_name="__main__")
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception:
        traceback.print_exc()
        code = 1
    else:
        code = 0
sys.exit(code)
'''


def launcher_path() -> Path:
    return netlib.app_dir() / "run_brief.py"


def write_launcher() -> Path:
    path = launcher_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(LAUNCHER.format(fallback=str(BRIEF)), encoding="utf-8")
    return path


def python_exe() -> str:
    """A real interpreter path: scheduled tasks do not have your shell's PATH shims (pyenv, Store aliases)."""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")  # Windows: no console window flashing up every morning
    return str(pythonw if platform.system() == "Windows" and pythonw.is_file() else exe)


def windows_create(time: str) -> list[str]:
    action = f'"{python_exe()}" "{launcher_path()}"'
    return ["schtasks", "/Create", "/F", "/SC", "DAILY", "/TN", TASK, "/TR", action, "/ST", time]


def cron_line(time: str) -> str:
    hour, minute = time.split(":")
    return f'{int(minute)} {int(hour)} * * * "{sys.executable}" "{launcher_path()}" >/dev/null 2>&1'


def main(argv: list[str] | None = None) -> int:
    netlib.force_utf8_output()
    ap = argparse.ArgumentParser(description="Schedule a daily brief.")
    ap.add_argument("--time", default="07:30", help="local time HH:MM (default 07:30)")
    ap.add_argument("--create", action="store_true", help="Windows: create the scheduled task")
    ap.add_argument("--remove", action="store_true", help="Windows: delete the scheduled task")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", a.time):
        print("ERROR: --time must be HH:MM, e.g. 07:30", file=sys.stderr)
        return 2
    windows = platform.system() == "Windows"
    briefs = netlib.app_dir() / "briefs"

    if not windows:
        if a.create:
            print(f"Wrote {write_launcher()}")
        if a.create or a.remove:
            print("On Linux and macOS this script does not edit your crontab. Add or remove this line with "
                  "`crontab -e`:")
        print(cron_line(a.time))
        print(f"Briefs are written to {briefs}")
        return 0

    if a.remove:
        r = subprocess.run(["schtasks", "/Delete", "/F", "/TN", TASK], capture_output=True, text=True)
        print((r.stdout or r.stderr).strip())
        return 0 if r.returncode == 0 else 1
    cmd = windows_create(a.time)
    if not a.create:
        print("This would create a daily Windows task (run again with --create to make it):\n")
        print("  " + subprocess.list2cmdline(cmd))
        print(f"\nBriefs will be written to {briefs}. Remove the task later with --remove.")
        return 0
    if not shutil.which("schtasks"):
        print("ERROR: schtasks not found", file=sys.stderr)
        return 1
    write_launcher()
    r = subprocess.run(cmd, capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())
    if r.returncode == 0:
        print(f"Daily at {a.time}: briefs go to {briefs}. Remove with: schedule_brief.py --remove")
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
