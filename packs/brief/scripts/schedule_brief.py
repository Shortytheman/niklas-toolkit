#!/usr/bin/env python3
"""Run the brief every morning without opening Claude: shows (or, with --create, makes) a scheduled task.

    python schedule_brief.py                  show the command for a daily brief at 07:30
    python schedule_brief.py --time 06:45     another time
    python schedule_brief.py --create         Windows: create the task with schtasks (you can remove it with --remove)
    python schedule_brief.py --remove         Windows: delete the task

Each run executes `brief.py --save`, which writes <toolkit folder>/briefs/brief-YYYY-MM-DD.md. On Linux and macOS
this prints a crontab line to add with `crontab -e`; it never edits your crontab.

Creating a scheduled task changes your system, so nothing is created without --create. The task points at
this copy of brief.py: after updating the plugin (a new version lives in a new folder), run --create again.
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


def python_exe() -> str:
    """A real interpreter path: scheduled tasks do not have your shell's PATH shims (pyenv, Store aliases)."""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")  # Windows: no console window flashing up every morning
    return str(pythonw if platform.system() == "Windows" and pythonw.is_file() else exe)


def windows_create(time: str) -> list[str]:
    action = f'"{python_exe()}" "{BRIEF}" --save'
    return ["schtasks", "/Create", "/F", "/SC", "DAILY", "/TN", TASK, "/TR", action, "/ST", time]


def cron_line(time: str) -> str:
    hour, minute = time.split(":")
    return f'{int(minute)} {int(hour)} * * * "{sys.executable}" "{BRIEF}" --save >/dev/null 2>&1'


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
    r = subprocess.run(cmd, capture_output=True, text=True)
    print((r.stdout or r.stderr).strip())
    if r.returncode == 0:
        print(f"Daily at {a.time}: briefs go to {briefs}. Remove with: schedule_brief.py --remove")
    return 0 if r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
