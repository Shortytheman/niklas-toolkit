#!/usr/bin/env python3
"""Run a Godot 4 scene with rendering, save chosen frames as PNG, and report errors from the run.

Runs without Claude. Standard library only. A game window opens briefly; headless mode cannot render.

    python screenshot.py [project_dir] [--scene res://x.tscn] [--frames 60,180] [--out DIR]
                         [--max-width 1280] [--real-user-data] [--godot PATH] [-- game args ...]

Frames are counted from the first frame the scene is running. The game's own code is not changed: the capture
logic is capture.gd, loaded as the main loop with --script.

--steps drives the UI with real mouse and key events to reach screens behind menus, saving named shots:

    python screenshot.py <project> --steps "click:Settings; wait:20; shot:settings; key:Escape; shot:back"

Actions: wait:<frames>, click:<control>, hover:<control>, key:<key>, waitfor:<control>, shot:<name>.
A control is found by its button or label text, its node name, or its node path from the root. When a step
fails, the run stops, saves shot_failed_stepNN.png and lists the visible buttons.

Saves and settings go to a sandbox (<project>/.godot/toolkit/userdata) unless --real-user-data is given, so the
run never touches the developer's real save files.

Exit codes: 0 every frame saved, 1 a frame is missing or the run had errors, 2 bad setup.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from godot_common import (SetupError, digest_log, find_godot, find_project, load_toolkit_config,  # noqa: E402
                          read_project, run_godot, sandbox_env)

CAPTURE = Path(__file__).resolve().parent / "capture.gd"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    game_args: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, game_args = argv[:i], argv[i + 1:]

    ap = argparse.ArgumentParser(description="Capture frames of a Godot scene as PNG.")
    ap.add_argument("project", nargs="?", default=".", help="project folder or any folder inside it (default: .)")
    ap.add_argument("--scene", help="scene to run (default: main scene)")
    ap.add_argument("--frames", default="60", help="comma-separated frames to save (default 60)")
    ap.add_argument("--steps", help='drive the UI, e.g. "click:Settings; wait:20; shot:settings" '
                                    "(actions: wait, click, hover, key, waitfor, shot); replaces --frames")
    ap.add_argument("--out", help="output folder (default: <project>/.godot/toolkit/shots)")
    ap.add_argument("--max-width", type=int, default=1280, help="downscale wider frames (default 1280, 0 = full)")
    ap.add_argument("--timeout", type=int, default=180, help="seconds before the run is killed (default 180)")
    ap.add_argument("--real-user-data", action="store_true", help="use the real saves instead of the sandbox")
    ap.add_argument("--godot", help="Godot executable or its folder")
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
    try:
        frames = sorted({int(f) for f in args.frames.split(",") if f.strip()})
    except ValueError:
        raise SetupError(f"--frames must be numbers separated by commas, got {args.frames!r}")
    if not frames or frames[0] < 0:
        raise SetupError("--frames needs at least one frame number >= 0")
    scene = args.scene or info.main_scene
    if not scene:
        raise SetupError("no main scene in project.godot; pass --scene res://path.tscn")

    steps = parse_steps(args.steps) if args.steps else []

    out_dir = Path(args.out).resolve() if args.out else project / ".godot" / "toolkit" / "shots"
    if out_dir.exists():
        for old in out_dir.glob("shot_*.png"):
            old.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    mode = ["--steps", "; ".join(steps)] if steps else ["--frames", ",".join(map(str, frames))]
    cmd = ["--path", str(project), "--script", str(CAPTURE), "--",
           "--scene", scene, *mode, "--out", str(out_dir), "--max-width", str(args.max_width), *game_args]
    env = None if args.real_user_data else sandbox_env(project)
    out = run_godot(godot, cmd, args.timeout, env=env)
    (out_dir / "capture.log").write_text(out.text, encoding="utf-8")

    if steps:
        expected = [s.split(":", 1)[1].strip() or f"step{i + 1:02d}" for i, s in enumerate(steps)
                    if s.split(":", 1)[0].strip().lower() == "shot"]
        saved = [out_dir / f"shot_{name}.png" for name in expected]
        what = f"{len(steps)} step(s)"
    else:
        saved = [out_dir / f"shot_{f:05d}.png" for f in frames]
        what = f"frames {frames}"
    missing = [p for p in saved if not p.is_file()]
    failed_shots = sorted(out_dir.glob("shot_failed_step*.png"))
    problems = digest_log(out.text, ignore)
    errors = [p for p in problems if p.kind == "error" and "capture.gd" not in p.message]
    step_failed = bool(steps) and (out.code != 0 or bool(failed_shots))

    status = "TIMED OUT" if out.timed_out else f"exit {out.code}"
    print(f"{info.name}: {scene} {what}  |  {status} in {out.seconds:.1f}s  |  "
          f"{len(saved) - len(missing)}/{len(saved)} saved, {sum(p.count for p in errors)} error(s)")
    for p in saved:
        if p.is_file():
            print(f"  {p}")
    for p in missing:
        print(f"  MISSING {p.name}")
    for p in errors[:10]:
        print(p.render())
    if step_failed or missing:
        lines = out.text.splitlines()
        start = next((i for i, l in enumerate(lines) if "failed:" in l and "capture.gd" in l), None)
        if start is not None:  # why it failed, the failing step, and the list of visible buttons after it
            why = [l for l in lines[max(0, start - 2):start] if l.startswith("capture.gd:") and "step" not in l]
            block = why + [lines[start]] + [l for l in lines[start + 1:start + 45]
                                     if (l.startswith("  ") and not l.strip().startswith("at:"))
                                     or "visible buttons" in l]
            print("\n".join(block))
        else:
            print("\n".join([l for l in lines if "capture.gd" in l][-5:]))
        for p in failed_shots:
            print(f"  screen at the failure: {p}")
    print(f"Log: {out_dir / 'capture.log'}")
    return 1 if missing or errors or out.timed_out or step_failed else 0


STEP_ACTIONS = {"wait", "click", "hover", "key", "waitfor", "shot"}


def parse_steps(text: str) -> list[str]:
    """'click:Start; wait:30; shot:menu' -> checked list of steps."""
    steps = [s.strip() for s in text.split(";") if s.strip()]
    for s in steps:
        action, _, arg = s.partition(":")
        action, arg = action.strip().lower(), arg.strip()
        if action not in STEP_ACTIONS:
            raise SetupError(f"unknown step '{s}'; use {', '.join(sorted(STEP_ACTIONS))}")
        if action == "wait" and not arg.isdigit():
            raise SetupError(f"'{s}': wait needs a number of frames, e.g. wait:30")
        if action in ("click", "hover", "key", "waitfor") and not arg:
            raise SetupError(f"'{s}': {action} needs a target, e.g. {action}:Start")
        if action == "shot" and arg and not all(c.isalnum() or c in "-_" for c in arg):
            raise SetupError(f"'{s}': shot names use letters, digits, - and _ only")
    return steps


if __name__ == "__main__":
    sys.exit(main())
