#!/usr/bin/env python3
"""What makes a Godot 4 build big: sizes by source folder, by kind and the largest files, read from the export.

Standard library only; does not need Godot. Reads the pack's file table without unpacking anything.

    python pck_size.py [target] [--compare OLD] [--top 15] [--depth 2] [--json]

target (and OLD) can be:
    a .pck file, a game executable with the pack embedded, a build .zip that contains either, or a project
    folder (default: .), which means the newest build in <project>/export/builds (where export.py puts them).

Imported files are listed under their source path (art/hero.png, not .godot/imported/hero.png-<hash>.ctex):
the pack's own .import and .remap entries say which source each exported file came from.
--compare shows which folders and files grew, shrank, appeared or went away since an older build.

Exit codes: 0 ok, 2 nothing readable (no build found, not a Godot 4 pack, encrypted file table).
"""
from __future__ import annotations

import argparse
import io
import json
import re
import struct
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

MAGIC = b"GDPC"
DIR_ENCRYPTED = 1        # pack flag: the file table itself is encrypted
REL_FILEBASE = 2         # pack flag: offsets are relative to the pack's start
FILE_ENCRYPTED = 1       # file flag
FILE_REMOVAL = 2         # file flag: a patch pack deletes this path
REMAP_PATH = re.compile(r'^path(?:\.[\w]+)?="res://([^"]+)"', re.MULTILINE)

KINDS = [
    ("texture", {"ctex", "ctexarray", "ctex3d", "png", "jpg", "jpeg", "webp", "svg", "image", "bmp", "tga", "exr",
                 "hdr", "dds", "ktx"}),
    ("audio", {"oggvorbisstr", "mp3str", "sample", "wav", "ogg", "mp3"}),
    ("video", {"ogv"}),
    ("scene", {"scn", "tscn"}),
    ("resource", {"res", "tres", "material", "mesh", "anim"}),
    ("script", {"gdc", "gd", "gde", "cs", "dll"}),
    ("shader", {"gdshader", "shader", "gdshaderinc"}),
    ("font", {"fontdata", "ttf", "otf", "woff", "woff2", "fnt"}),
    ("translation", {"translation", "po", "mo"}),
    ("pack metadata", {"import", "remap", "uid", "cfg", "bin", "godot"}),
]


class PackError(Exception):
    pass


@dataclass
class Entry:
    path: str           # path inside the pack
    offset: int         # absolute, in the stream the pack was read from
    size: int
    flags: int
    source: str = ""    # the project file it came from


@dataclass
class Pack:
    label: str
    version: str
    format: int
    size: int
    entries: list[Entry] = field(default_factory=list)


def kind_of(entry: Entry) -> str:
    ext = entry.path.rsplit(".", 1)[-1].lower()
    for name, exts in KINDS:
        if ext in exts:
            return name
    return "other"


def _u32(f: BinaryIO) -> int:
    return struct.unpack("<I", _read(f, 4))[0]


def _u64(f: BinaryIO) -> int:
    return struct.unpack("<Q", _read(f, 8))[0]


def _read(f: BinaryIO, n: int) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise PackError("the file ends early: not a complete Godot pack")
    return data


def pack_start(f: BinaryIO) -> int:
    """0 for a .pck; for an executable with an embedded pack, where the pack begins (Godot writes the pack's size
    and the magic at the very end of the file)."""
    f.seek(0)
    if f.read(4) == MAGIC:
        return 0
    end = f.seek(0, io.SEEK_END)
    if end >= 12:
        f.seek(end - 12)
        size, magic = struct.unpack("<Q4s", f.read(12))
        start = end - 12 - size
        if magic == MAGIC and 0 <= start:
            f.seek(start)
            if f.read(4) == MAGIC:
                return start
    raise PackError("not a Godot pack: no GDPC header, and no pack embedded in the file")


def read_pack(f: BinaryIO, label: str) -> Pack:
    start = pack_start(f)
    f.seek(start + 4)
    fmt, major, minor, patch, flags = struct.unpack("<5I", _read(f, 20))
    if major < 4 or fmt < 2:
        raise PackError(f"pack format {fmt} from Godot {major}.{minor}: only Godot 4 packs are supported")
    if flags & DIR_ENCRYPTED:
        raise PackError("the pack's file table is encrypted: sizes cannot be read without the key")
    file_base = _u64(f)
    if fmt >= 3 or flags & REL_FILEBASE:
        file_base += start
    if fmt >= 3:                              # Godot 4.4+: the file table sits at the end, after the data
        f.seek(_u64(f) + start)
    else:
        f.seek(16 * 4, io.SEEK_CUR)           # reserved
    count = _u32(f)
    if count > 10_000_000:
        raise PackError(f"implausible file count {count}: unsupported pack format {fmt}")
    entries = []
    for _ in range(count):
        path = _read(f, _u32(f)).rstrip(b"\0").decode("utf-8", "replace")
        offset, size = struct.unpack("<QQ", _read(f, 16))
        _read(f, 16)                          # md5
        flags_e = _u32(f)
        path = path[6:] if path.startswith("res://") else path
        if not flags_e & FILE_REMOVAL:
            entries.append(Entry(path, file_base + offset, size, flags_e))
    end = f.seek(0, io.SEEK_END)
    pack = Pack(label, f"{major}.{minor}.{patch}", fmt, end - start, entries)
    attribute(f, pack)
    return pack


def attribute(f: BinaryIO, pack: Pack) -> None:
    """Name each exported file after its source: read the small .import/.remap entries (in file order, so a
    compressed zip member is read in one forward pass)."""
    by_path = {e.path: e for e in pack.entries}
    maps = sorted((e for e in pack.entries if e.path.endswith((".import", ".remap"))
                   and not e.flags & FILE_ENCRYPTED and e.size < 64_000), key=lambda e: e.offset)
    for meta in maps:
        f.seek(meta.offset)
        text = f.read(meta.size).decode("utf-8", "replace")
        source = meta.path.rsplit(".", 1)[0]
        meta.source = source
        for target in REMAP_PATH.findall(text):
            hit = by_path.get(target)
            if hit is not None:
                hit.source = source
    for e in pack.entries:
        if not e.source:
            e.source = e.path[:-1] if e.path.endswith(".gdc") else e.path


# --- finding the build --------------------------------------------------------------------------------------------

def newest_build(project: Path) -> Path:
    builds = project / "export" / "builds"
    found = [p for pattern in ("*.zip", "*.pck") for p in builds.rglob(pattern)] if builds.is_dir() else []
    if not found:
        raise PackError(f"no .zip or .pck in {builds}: export first (export.py), or pass the build's path")
    return max(found, key=lambda p: p.stat().st_mtime)


def open_target(target: Path) -> Pack:
    if target.is_dir():
        target = newest_build(target)
    if not target.is_file():
        raise PackError(f"{target} does not exist")
    if zipfile.is_zipfile(target):
        with zipfile.ZipFile(target) as z:
            members = sorted((i for i in z.infolist() if not i.is_dir()), key=lambda i: i.file_size, reverse=True)
            pcks = [i for i in members if i.filename.lower().endswith(".pck")]
            for info in pcks or members[:5]:           # no .pck: the biggest files may embed one
                with z.open(info) as f:
                    try:
                        return read_pack(f, f"{target.name} > {info.filename}")
                    except PackError:
                        if pcks:
                            raise
        raise PackError(f"{target.name} contains no Godot pack")
    with target.open("rb") as f:
        return read_pack(f, target.name)


# --- reports ------------------------------------------------------------------------------------------------------

def folder_of(source: str, depth: int) -> str:
    parts = source.split("/")[:-1]
    return "/".join(parts[:depth]) or "(project root)"


def totals(pack: Pack, key) -> dict[str, list[int]]:
    out: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for e in pack.entries:
        t = out[key(e)]
        t[0] += e.size
        t[1] += 1
    return dict(out)


def by_source(pack: Pack) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for e in pack.entries:
        out[e.source] += e.size
    return dict(out)


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def signed(n: int) -> str:
    return ("+" if n > 0 else "-" if n < 0 else "±") + human(abs(n))


def report(pack: Pack, top: int, depth: int) -> dict:
    total = sum(e.size for e in pack.entries) or 1
    folders = sorted(totals(pack, lambda e: folder_of(e.source, depth)).items(), key=lambda kv: -kv[1][0])
    kinds = sorted(totals(pack, kind_of).items(), key=lambda kv: -kv[1][0])
    files = sorted(by_source(pack).items(), key=lambda kv: -kv[1])[:top]
    return {
        "build": pack.label, "godot": pack.version, "pack_format": pack.format, "pack_bytes": pack.size,
        "files": len(pack.entries), "content_bytes": total,
        "folders": [{"folder": k, "bytes": v[0], "files": v[1], "share": round(v[0] / total, 4)} for k, v in folders],
        "kinds": [{"kind": k, "bytes": v[0], "files": v[1], "share": round(v[0] / total, 4)} for k, v in kinds],
        "largest": [{"source": s, "bytes": b} for s, b in files],
    }


def compare(new: Pack, old: Pack, top: int, depth: int) -> dict:
    a, b = by_source(old), by_source(new)
    changes = {s: b.get(s, 0) - a.get(s, 0) for s in set(a) | set(b)}
    fa = totals(old, lambda e: folder_of(e.source, depth))
    fb = totals(new, lambda e: folder_of(e.source, depth))
    folders = {k: fb.get(k, [0, 0])[0] - fa.get(k, [0, 0])[0] for k in set(fa) | set(fb)}
    moved = sorted(((s, d) for s, d in changes.items() if d), key=lambda kv: -abs(kv[1]))
    return {
        "old": old.label, "new": new.label, "old_bytes": old.size, "new_bytes": new.size,
        "change_bytes": new.size - old.size,
        "folders": [{"folder": k, "change_bytes": v} for k, v in
                    sorted(((k, v) for k, v in folders.items() if v), key=lambda kv: -abs(kv[1]))[:top]],
        "files": [{"source": s, "change_bytes": d, "status": "new" if s not in a else "removed" if s not in b
                   else "changed"} for s, d in moved[:top]],
        "added": sum(1 for s in b if s not in a), "removed": sum(1 for s in a if s not in b),
    }


def print_report(r: dict) -> None:
    print(f"{r['build']}: {human(r['pack_bytes'])}, {r['files']:,} files (Godot {r['godot']}, "
          f"pack format {r['pack_format']})\n")
    print("By folder:")
    for f in r["folders"][:15]:
        print(f"  {human(f['bytes']):>10}  {f['share']:>4.0%}  {f['files']:>6,} files  {f['folder']}")
    if len(r["folders"]) > 15:
        rest = r["folders"][15:]
        print(f"  {human(sum(f['bytes'] for f in rest)):>10}        {len(rest)} more folders")
    print("\nBy kind:")
    for k in r["kinds"]:
        print(f"  {human(k['bytes']):>10}  {k['share']:>4.0%}  {k['files']:>6,} files  {k['kind']}")
    print("\nLargest files:")
    for f in r["largest"]:
        print(f"  {human(f['bytes']):>10}  {f['source']}")


def print_compare(c: dict) -> None:
    print(f"{c['old']}  ->  {c['new']}")
    print(f"{human(c['old_bytes'])} -> {human(c['new_bytes'])} ({signed(c['change_bytes'])}); "
          f"{c['added']} file(s) added, {c['removed']} removed\n")
    if not c["files"]:
        print("No content changed size.")
        return
    print("Folders that changed most:")
    for f in c["folders"]:
        print(f"  {signed(f['change_bytes']):>11}  {f['folder']}")
    print("\nFiles that changed most:")
    for f in c["files"]:
        print(f"  {signed(f['change_bytes']):>11}  {f['source']}" + ("" if f["status"] == "changed"
                                                                    else f"  ({f['status']})"))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Show what makes a Godot 4 build big.")
    ap.add_argument("target", nargs="?", default=".", help=".pck, executable, build .zip or project folder")
    ap.add_argument("--compare", metavar="OLD", help="an older build to compare against")
    ap.add_argument("--top", type=int, default=15, help="how many files to list (default 15)")
    ap.add_argument("--depth", type=int, default=2, help="folder depth for grouping (default 2)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)
    try:
        new = open_target(Path(a.target).resolve())
        old = open_target(Path(a.compare).resolve()) if a.compare else None
    except (PackError, OSError, zipfile.BadZipFile) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    result = compare(new, old, a.top, a.depth) if old else report(new, a.top, a.depth)
    if a.json:
        print(json.dumps(result, indent=2))
    elif old:
        print_compare(result)
    else:
        print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
