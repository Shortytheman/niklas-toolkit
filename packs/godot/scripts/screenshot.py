#!/usr/bin/env python3
"""Run a Godot 4 scene with rendering, save chosen frames as PNG, and report errors from the run.

Runs without Claude. Standard library only. A game window opens briefly; headless mode cannot render.

    python screenshot.py [project_dir] [--scene res://x.tscn] [--frames 60,180] [--out DIR]
                         [--max-width 1280] [--real-user-data] [--godot PATH] [-- game args ...]

Frames are counted from the first frame the scene is running. The game's own code is not changed: the capture
logic is capture.gd, loaded as the main loop with --script.

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

    out_dir = Path(args.out).resolve() if args.out else project / ".godot" / "toolkit" / "shots"
    if out_dir.exists():
        for old in out_dir.glob("shot_*.png"):
            old.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = ["--path", str(project), "--script", str(CAPTURE), "--",
           "--scene", scene, "--frames", ",".join(map(str, frames)), "--out", str(out_dir),
           "--max-width", str(args.max_width), *game_args]
    env = None if args.real_user_data else sandbox_env(project)
    out = run_godot(godot, cmd, args.timeout, env=env)
    (out_dir / "capture.log").write_text(out.text, encoding="utf-8")

    saved = [out_dir / f"shot_{f:05d}.png" for f in frames]
    missing = [p for p in saved if not p.is_file()]
    problems = digest_log(out.text, ignore)
    errors = [p for p in problems if p.kind == "error" and "capture.gd" not in p.message]

    status = "TIMED OUT" if out.timed_out else f"exit {out.code}"
    print(f"{info.name}: {scene} frames {frames}  |  {status} in {out.seconds:.1f}s  |  "
          f"{len(saved) - len(missing)}/{len(saved)} saved, {sum(p.count for p in errors)} error(s)")
    for p in saved:
        if p.is_file():
            print(f"  {p}")
    for p in missing:
        print(f"  MISSING {p.name}")
    for p in errors[:10]:
        print(p.render())
    if missing:
        fails = [l for l in out.text.splitlines() if "capture.gd" in l]
        if fails:
            print("\n".join(fails[-5:]))
    print(f"Log: {out_dir / 'capture.log'}")
    return 1 if missing or errors or out.timed_out else 0


if __name__ == "__main__":
    sys.exit(main())
