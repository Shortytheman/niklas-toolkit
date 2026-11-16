#!/usr/bin/env python3
"""Run a Godot 4 project headless and report only its errors and warnings.

Runs without Claude. Standard library only.

    python run_report.py [project_dir] [--scene res://path.tscn] [--frames N] [--timeout S]
                         [--check] [--warnings-fail] [--godot PATH] [-- game args ...]

Modes:
  default   run the main scene (or --scene) for --frames frames, then quit
  --check   load the whole project in the headless editor (no game run): finds parse errors in every script
            and broken resources, even in scenes the run never reaches

Noise can be silenced per project in toolkit.json: {"run": {"ignore": ["ObjectDB instances were leaked"]}}
(regular expressions matched against the message).

The full log is saved to <project>/.godot/toolkit/last_run.log (or last_check.log).

Exit codes: 0 no errors, 1 errors found (or crash / timeout), 2 bad setup.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from godot_common import (SetupError, digest_log, find_godot, find_project, load_toolkit_config,  # noqa: E402
                          read_project, run_godot, sandbox_env)

CRASH = re.compile(r"CrashHandlerException|Program crashed with signal|Dumping the backtrace", re.IGNORECASE)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    game_args: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, game_args = argv[:i], argv[i + 1:]

    ap = argparse.ArgumentParser(description="Run a Godot project headless and report errors and warnings.")
    ap.add_argument("project", nargs="?", default=".", help="project folder or any folder inside it (default: .)")
    ap.add_argument("--scene", help="scene to run instead of the main scene, e.g. res://levels/test.tscn")
    ap.add_argument("--frames", type=int, default=300, help="frames to run before quitting (default 300)")
    ap.add_argument("--timeout", type=int, default=180, help="seconds before the run is killed (default 180)")
    ap.add_argument("--check", action="store_true", help="load the project in the headless editor instead of running")
    ap.add_argument("--warnings-fail", action="store_true", help="exit 1 on warnings too")
    ap.add_argument("--max", type=int, default=20, help="most problems to print (default 20)")
    ap.add_argument("--godot", help="Godot executable or its folder")
    ap.add_argument("--real-user-data", action="store_true",
                    help="use the real user:// folder (saves, settings) instead of the toolkit sandbox")
    args = ap.parse_args(argv)

    try:
        return run(args, game_args)
    except SetupError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


def run(args: argparse.Namespace, game_args: list[str]) -> int:
    project = find_project(args.project)
    godot = find_godot(args.godot, project)
    info = read_project(project)
    ignore = load_toolkit_config(project).get("run", {}).get("ignore", [])

    if args.check:
        what = "CHECK (headless editor load)"
        cmd = ["--headless", "--path", str(project), "--import"]
    else:
        scene = args.scene or info.main_scene
        if not scene:
            raise SetupError("no main scene in project.godot; pass --scene res://path.tscn")
        what = f"RUN {scene} for {args.frames} frames"
        cmd = ["--headless", "--path", str(project)]
        if args.scene:
            cmd.append(args.scene)
        cmd += ["--quit-after", str(args.frames)]
        if game_args:
            cmd += ["--", *game_args]

    env = None if args.real_user_data else sandbox_env(project)
    out = run_godot(godot, cmd, args.timeout, env=env)

    log_dir = project / ".godot" / "toolkit"
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / ("last_check.log" if args.check else "last_run.log")
    log.write_text(out.text, encoding="utf-8")

    problems = digest_log(out.text, ignore)
    errors = [p for p in problems if p.kind == "error"]
    warnings = [p for p in problems if p.kind == "warning"]
    crashed = bool(CRASH.search(out.text))

    status = "TIMED OUT" if out.timed_out else "CRASHED" if crashed else f"exit {out.code}"
    print(f"{info.name}: {what}  |  {status} in {out.seconds:.1f}s  |  "
          f"{sum(p.count for p in errors)} error(s), {sum(p.count for p in warnings)} warning(s)"
          f" ({len(errors)} + {len(warnings)} unique)")
    shown = (errors + warnings)[:args.max]
    for p in shown:
        print(p.render())
    if len(errors + warnings) > len(shown):
        print(f"... {len(errors + warnings) - len(shown)} more unique problem(s)")
    if out.timed_out:
        print(f"The run did not finish within {args.timeout}s; it may hang. Last log lines:")
        print("\n".join("    " + l for l in out.text.strip().splitlines()[-10:]))
    if crashed:
        print("Godot crashed; the backtrace is in the log.")
    print(f"Full log: {log}")

    failed = bool(errors) or crashed or out.timed_out or (args.warnings_fail and bool(warnings))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
