#!/usr/bin/env python3
"""Export a Godot 4 project headless: every preset (or the ones you name), then zip each build.

Runs without Claude. Standard library only.

    python export.py [project_dir] [--preset NAME ...] [--bump major|minor|patch | --set-version X.Y.Z]
                     [--debug] [--out DIR] [--godot PATH] [--no-zip] [--include FILE ...]

Per-project defaults go in <project>/toolkit.json:

    {"godot": "C:/Tools/Godot", "export": {"presets": ["windows"], "include": ["docs/HOW TO PLAY.txt"]}}

Exit codes: 0 all presets exported, 1 at least one preset failed, 2 bad setup (no Godot, no project, ...).
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from godot_common import (SetupError, digest_log, find_godot, find_project, godot_version,  # noqa: E402
                          load_toolkit_config, parse_cfg_sections, read_project, run_godot)

# Godot platform name -> (file extension of the exported program, release template file name)
PLATFORMS = {
    "Windows Desktop": (".exe", "windows_release_x86_64.exe"),
    "Linux": (".x86_64", "linux_release.x86_64"),
    "macOS": (".zip", "macos.zip"),
    "Web": (".html", "web_nothreads_release.zip"),
    "Android": (".apk", "android_release.apk"),
}


@dataclass
class Preset:
    name: str
    platform: str
    options: dict[str, str] = field(default_factory=dict)


@dataclass
class Result:
    preset: str
    ok: bool
    seconds: float
    output: Path | None = None
    archive: Path | None = None
    message: str = ""


def read_presets(project: Path) -> list[Preset]:
    cfg = project / "export_presets.cfg"
    if not cfg.is_file():
        return []
    sections = parse_cfg_sections(cfg.read_text(encoding="utf-8"))
    return [Preset(v["name"], v.get("platform", ""), sections.get(s + ".options", {}))
            for s, v in sections.items() if re.fullmatch(r"preset\.\d+", s) and "name" in v]


# ---------------------------------------------------------------- version

VERSION_LINE = re.compile(r'^config/version="([^"]*)"[ \t]*$', re.MULTILINE)


def bump(version: str, part: str) -> str:
    """bump('1.5.3', 'minor') -> '1.6.0'. Missing parts count as 0."""
    nums = [int(x) for x in re.findall(r"\d+", version)[:3]]
    nums += [0] * (3 - len(nums))
    i = {"major": 0, "minor": 1, "patch": 2}[part]
    nums[i] += 1
    for j in range(i + 1, 3):
        nums[j] = 0
    return ".".join(map(str, nums))


def write_project_version(project: Path, version: str) -> None:
    """Set application/config/version in project.godot, keeping the file's line endings."""
    path = project / "project.godot"
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    if VERSION_LINE.search(text):
        text = VERSION_LINE.sub(f'config/version="{version}"', text, count=1)
    elif re.search(r"^\[application\]$", text, re.MULTILINE):
        text = re.sub(r"^\[application\]\n", f'[application]\n\nconfig/version="{version}"\n', text, count=1,
                      flags=re.MULTILINE)
    else:
        text += f'\n[application]\n\nconfig/version="{version}"\n'
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


# ---------------------------------------------------------------- templates

def templates_dir(version: str) -> Path:
    """'4.7.2.stable.official.ed1daf0bf' -> the export_templates folder for 4.7.2.stable."""
    short = ".".join(version.split(".")[:4])
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", "")) / "Godot"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "Godot"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "godot"
    return base / "export_templates" / short


def missing_template(preset: Preset, tdir: Path, debug: bool) -> str | None:
    custom = preset.options.get("custom_template/debug" if debug else "custom_template/release", "")
    if custom:
        return None if Path(custom).is_file() else f"custom template not found: {custom}"
    info = PLATFORMS.get(preset.platform)
    if not info:
        return None  # unknown platform: let Godot decide
    name = info[1].replace("release", "debug") if debug else info[1]
    return None if (tdir / name).is_file() else (
        f"export template missing: {tdir / name}. Install it in the editor: Editor > Manage Export Templates.")


# ---------------------------------------------------------------- export

def export_preset(godot: Path, project: Path, preset: Preset, game_name: str, out_dir: Path,
                  debug: bool, timeout: int) -> Result:
    ext = PLATFORMS.get(preset.platform, ("", ""))[0]
    target_dir = out_dir / preset.name / game_name
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)
    target = target_dir / f"{game_name}{ext}"

    flag = "--export-debug" if debug else "--export-release"
    run = run_godot(godot, ["--headless", "--path", str(project), flag, preset.name, str(target)], timeout)
    log = out_dir / preset.name / "export.log"
    log.write_text(run.text + (f"\n[export.py] timed out after {timeout}s\n" if run.timed_out else ""), encoding="utf-8")

    errors = [p for p in digest_log(run.text) if p.kind == "error"]
    if run.timed_out or run.code != 0 or not target.exists():
        why = "timed out" if run.timed_out else f"exit code {run.code}" if run.code else "no output file"
        detail = "\n".join(p.render() for p in errors[-10:]) or run.text.strip()[-1500:] or "(no output)"
        return Result(preset.name, False, run.seconds, message=f"{why}; full log: {log}\n{detail}")
    msg = f"{len(errors)} error line(s) in the log, the build was still written: {log}" if errors else ""
    return Result(preset.name, True, run.seconds, output=target_dir, message=msg)


def zip_build(build_dir: Path, archive: Path, includes: list[Path]) -> Path:
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(build_dir.rglob("*")):
            if f.is_file():
                zf.write(f, Path(build_dir.name) / f.relative_to(build_dir))
        for inc in includes:
            zf.write(inc, Path(build_dir.name) / inc.name)
    return archive


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export a Godot 4 project headless and zip the builds.")
    ap.add_argument("project", nargs="?", default=".", help="project folder or any folder inside it (default: .)")
    ap.add_argument("--preset", action="append", help="preset to export; repeat for several "
                                                      "(default: toolkit.json export.presets, else all)")
    ver = ap.add_mutually_exclusive_group()
    ver.add_argument("--bump", choices=["major", "minor", "patch"],
                     help="raise config/version in project.godot before exporting")
    ver.add_argument("--set-version", metavar="X.Y.Z", help="write this config/version to project.godot first")
    ap.add_argument("--out", help="output folder (default: <project>/export/builds)")
    ap.add_argument("--godot", help="Godot executable or its folder")
    ap.add_argument("--debug", action="store_true", help="debug export instead of release")
    ap.add_argument("--no-zip", action="store_true", help="skip zipping")
    ap.add_argument("--include", action="append", help="extra file for every zip (default: toolkit.json export.include)")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per preset before giving up (default 1800)")
    args = ap.parse_args(argv)

    try:
        return run(args)
    except SetupError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


def run(args: argparse.Namespace) -> int:
    project = find_project(args.project)
    godot = find_godot(args.godot, project)
    defaults = load_toolkit_config(project).get("export", {})

    include_paths = args.include or [str(project / p) for p in defaults.get("include", [])]
    includes = [Path(p).resolve() for p in include_paths]
    for inc in includes:
        if not inc.is_file():
            raise SetupError(f"include file not found: {inc}")

    all_presets = read_presets(project)
    if not all_presets:
        raise SetupError(f"no presets in {project / 'export_presets.cfg'}. Create one in the editor: Project > Export.")
    wanted = args.preset or defaults.get("presets")
    if wanted:
        by_name = {p.name: p for p in all_presets}
        unknown = [n for n in wanted if n not in by_name]
        if unknown:
            raise SetupError(f"unknown preset(s) {unknown}. Available: {list(by_name)}")
        presets = [by_name[n] for n in wanted]
    else:
        presets = all_presets

    info = read_project(project)
    version = info.version
    if args.bump or args.set_version:
        new = args.set_version or bump(version, args.bump)
        write_project_version(project, new)
        print(f"Version {version or '(none)'} -> {new} in project.godot")
        version = new

    out_dir = Path(args.out).resolve() if args.out else project / "export" / "builds"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ".gdignore").touch()  # keep Godot from importing the builds

    gv = godot_version(godot)
    tdir = templates_dir(gv)
    print(f"Godot {gv}  |  {info.name} {version}  |  output {out_dir}")

    results: list[Result] = []
    total_start = time.monotonic()
    for preset in presets:
        problem = missing_template(preset, tdir, args.debug)
        if problem:
            results.append(Result(preset.name, False, 0.0, message=problem))
            print(f"[{preset.name}] SKIPPED: {problem}")
            continue
        print(f"[{preset.name}] exporting ({preset.platform}) ...", flush=True)
        r = export_preset(godot, project, preset, info.name, out_dir, args.debug, args.timeout)
        if r.ok and not args.no_zip:
            suffix = f" {version}" if version else ""
            r.archive = zip_build(r.output, out_dir / f"{info.name}{suffix} {preset.name}.zip", includes)
        results.append(r)
        status = "OK" if r.ok else "FAILED"
        print(f"[{preset.name}] {status} in {r.seconds:.1f}s" + (f"  ->  {r.archive or r.output}" if r.ok else ""))
        if r.message:
            print("    " + r.message.replace("\n", "\n    "))

    failed = [r for r in results if not r.ok]
    print(f"\nDone in {time.monotonic() - total_start:.1f}s: {len(results) - len(failed)} ok, {len(failed)} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
