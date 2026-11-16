#!/usr/bin/env python3
"""Look up the exact Godot API of the Godot version the project uses: classes, method signatures, properties,
signals, constants and enums, read from that Godot executable itself.

Standard library only.

    python godot_api.py Tween                    class overview: parents, method names, properties, signals
    python godot_api.py Tween.tween_method       exact signature (inherited members are found too)
    python godot_api.py tween_method             every class that has a member of that name
    python godot_api.py --search tween           names containing the text
    python godot_api.py Tween --full             every signature of the class
    python godot_api.py Tween.tween_method --describe   also the official description (fetched once from GitHub)

The first lookup for a Godot version runs `godot --doctool` (a few seconds) and saves an index in the toolkit
folder (<toolkit folder>/godot-api/<version>/); later lookups read the index. Godot is found like the other
scripts: --godot, $GODOT_BIN, "godot" in the project's toolkit.json, or godot on PATH.

The release executable's dump has signatures but no description text. --describe downloads that class's file
from the godotengine/godot repository at the matching version tag (cached), and also shows deprecation notes.

Exit codes: 0 found, 1 not found (suggestions are printed), 2 setup problem (no Godot, dump failed, offline).
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import sys
import tempfile
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from godot_common import SetupError, find_godot, godot_version, run_godot  # noqa: E402

INDEX_VERSION = 1
GITHUB_RAW = "https://raw.githubusercontent.com/godotengine/godot/{tag}/{path}"

# Godot 3 names that Claude (and old tutorials) still reach for; checked against the index before being shown.
GODOT3_NAMES = {
    "KinematicBody2D": "CharacterBody2D", "KinematicBody": "CharacterBody3D", "Spatial": "Node3D",
    "Position2D": "Marker2D", "Position3D": "Marker3D", "Particles2D": "GPUParticles2D",
    "Particles": "GPUParticles3D", "Light2D": "PointLight2D", "VisibilityNotifier2D": "VisibleOnScreenNotifier2D",
    "VisibilityNotifier": "VisibleOnScreenNotifier3D", "File": "FileAccess", "Directory": "DirAccess",
    "PoolStringArray": "PackedStringArray", "PoolIntArray": "PackedInt32Array",
    "PoolRealArray": "PackedFloat32Array", "PoolVector2Array": "PackedVector2Array", "ToolButton": "Button",
    "instance": "instantiate", "change_scene": "change_scene_to_file", "rect_position": "position",
    "rect_size": "size", "rect_min_size": "custom_minimum_size", "get_ticks_msec": "Time.get_ticks_msec",
}


class NotFound(Exception):
    pass


# --- building the index -------------------------------------------------------------------------------------------

def _type(el: ET.Element | None) -> str:
    if el is None:
        return ""
    t = el.get("enum") or el.get("type") or ""
    if t.endswith("[]"):                          # typed arrays are written as Node[] in the docs
        t = f"Array[{t[:-2]}]"
    return t


def _params(el: ET.Element) -> list[list[str]]:
    params = sorted(el.findall("param"), key=lambda p: int(p.get("index", 0)))
    return [[p.get("name", ""), _type(p), p.get("default", "")] for p in params]


def parse_class(path: Path, rel: str) -> dict:
    root = ET.parse(path).getroot()
    c: dict = {"inherits": root.get("inherits", ""), "file": rel, "methods": {}, "members": {}, "signals": {},
               "constants": {}, "constructors": [], "annotations": {}, "theme": {}}
    for m in root.iterfind("methods/method"):
        c["methods"][m.get("name")] = {"ret": _type(m.find("return")), "params": _params(m),
                                       "q": m.get("qualifiers", "")}
    for m in root.iterfind("constructors/constructor"):
        c["constructors"].append(_params(m))
    for m in root.iterfind("members/member"):
        c["members"][m.get("name")] = {"type": _type(m), "default": m.get("default", "")}
    for s in root.iterfind("signals/signal"):
        c["signals"][s.get("name")] = _params(s)
    for k in root.iterfind("constants/constant"):
        c["constants"][k.get("name")] = {"value": k.get("value", ""), "enum": k.get("enum", ""),
                                         "bitfield": k.get("is_bitfield") == "true"}
    for a in root.iterfind("annotations/annotation"):
        c["annotations"][a.get("name")] = _params(a)
    for t in root.iterfind("theme_items/theme_item"):
        c["theme"][t.get("name")] = {"kind": t.get("data_type", ""), "type": t.get("type", ""),
                                     "default": t.get("default", "")}
    return c


def build_index(dump: Path, version: str) -> dict:
    classes = {}
    for xml in sorted(dump.rglob("*.xml")):
        rel = xml.relative_to(dump).as_posix()
        if "/doc/classes/" not in f"/{rel}" and "/doc_classes/" not in rel:
            continue
        name = ET.parse(xml).getroot().get("name")
        if name:
            classes[name] = parse_class(xml, rel)
    if not classes:
        raise SetupError("godot --doctool wrote no class files")
    return {"index_version": INDEX_VERSION, "godot": version, "classes": classes}


def cache_dir(version: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", version) or "unknown"
    return netlib.app_dir() / "godot-api" / safe


def load_index(godot: Path, refresh: bool = False) -> dict:
    version = godot_version(godot)
    if not version:
        raise SetupError(f"{godot} did not print a version")
    path = cache_dir(version) / "index.json"
    if path.is_file() and not refresh:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("index_version") == INDEX_VERSION:
                return data
        except (OSError, json.JSONDecodeError):
            pass
    with tempfile.TemporaryDirectory(prefix="godot-api-") as tmp:
        dump, home = Path(tmp) / "dump", Path(tmp) / "home"
        dump.mkdir()
        home.mkdir()
        # Godot's own settings and caches go to a throwaway folder, never the user's editor settings.
        env = dict(__import__("os").environ, APPDATA=str(home), XDG_DATA_HOME=str(home),
                   XDG_CONFIG_HOME=str(home), XDG_CACHE_HOME=str(home))
        out = run_godot(godot, ["--headless", "--doctool", str(dump)], timeout=300, env=env)
        if out.timed_out:
            raise SetupError("godot --doctool did not finish within 5 minutes")
        try:
            data = build_index(dump, version)
        except (SetupError, ET.ParseError) as e:
            raise SetupError(f"could not read Godot's API dump ({e}); Godot said:\n{out.text[-600:]}") from e
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    return data


# --- rendering ----------------------------------------------------------------------------------------------------

def _args(params: list[list[str]]) -> str:
    return ", ".join(f"{n}: {t or 'Variant'}" + (f" = {d}" if d else "") for n, t, d in params)


def method_sig(name: str, m: dict) -> str:
    q = m["q"].split()
    args = _args(m["params"]) + ((", " if m["params"] else "") + "..." if "vararg" in q else "")
    prefix = "static func" if "static" in q else "func"
    suffix = " const" if "const" in q else ""
    return f"{prefix} {name}({args}) -> {m['ret'] or 'void'}{suffix}"


def member_sig(cls: str, kind: str, name: str, data) -> str:
    if kind == "methods":
        return method_sig(name, data)
    if kind == "members":
        return f"var {name}: {data['type']}" + (f" = {data['default']}" if data["default"] else "")
    if kind == "signals":
        return f"signal {name}({_args(data)})"
    if kind == "constants":
        where = f"  (enum {cls}.{data['enum']}{', bitfield' if data['bitfield'] else ''})" if data["enum"] else ""
        return f"const {name} = {data['value']}{where}"
    if kind == "annotations":
        return f"{name}({_args(data)})"
    if kind == "theme":
        return f"theme {data['kind']} {name}: {data['type']}" + (f" = {data['default']}" if data["default"] else "")
    return name


KINDS = ["methods", "members", "signals", "constants", "annotations", "theme"]


def ancestors(idx: dict, cls: str) -> list[str]:
    chain, seen = [], set()
    while cls in idx["classes"] and cls not in seen:
        seen.add(cls)
        chain.append(cls)
        cls = idx["classes"][cls]["inherits"]
    return chain


def find_member(idx: dict, cls: str, name: str) -> list[tuple[str, str, str, object]]:
    """(owner class, kind, name, data) for `name` on `cls` or its parents, nearest first."""
    for owner in ancestors(idx, cls):
        c = idx["classes"][owner]
        hits = [(owner, kind, name, c[kind][name]) for kind in KINDS if name in c[kind]]
        if hits:
            return hits
    return []


def class_overview(idx: dict, cls: str, full: bool) -> str:
    c = idx["classes"][cls]
    chain = ancestors(idx, cls)
    lines = [f"class {cls}" + (f" extends {c['inherits']}" if c["inherits"] else "")
             + f"   (Godot {idx['godot'].split('.official')[0]})"]
    if len(chain) > 2:
        lines.append("Inherits: " + " < ".join(chain[1:]))
    for params in c["constructors"]:
        lines.append(f"  {cls}({_args(params)})")
    enums: dict[str, list[str]] = {}
    for k, v in c["constants"].items():
        if v["enum"]:
            enums.setdefault(v["enum"], []).append(k)
    sections = [("Methods", "methods"), ("Properties", "members"), ("Signals", "signals"),
                ("Annotations", "annotations"), ("Theme items", "theme")]
    for title, kind in sections:
        items = c[kind]
        if not items:
            continue
        if full:
            lines.append(f"\n{title}:")
            lines += [f"  {member_sig(cls, kind, n, d)}" for n, d in items.items()]
        else:
            lines.append(f"{title} ({len(items)}): " + ", ".join(items))
    plain = [k for k, v in c["constants"].items() if not v["enum"]]
    if plain:
        lines.append(f"Constants ({len(plain)}): " + ", ".join(plain))
    for e, names in enums.items():
        lines.append(f"enum {e}: " + ", ".join(names))
    if not full:
        lines.append(f"\n{cls}.<name> gives a signature; inherited members are on: {', '.join(chain[1:]) or '-'}")
    return "\n".join(lines)


def suggest(idx: dict, name: str, cls: str | None = None) -> list[str]:
    out = []
    old = GODOT3_NAMES.get(name)
    if old:
        target_cls, _, target = old.rpartition(".")
        if (old in idx["classes"]) or any(target in c[k] for c in idx["classes"].values() for k in KINDS):
            out.append(f"{name} is the Godot 3 name: use {old}")
    if cls:
        pool = {n for owner in ancestors(idx, cls) for k in KINDS for n in idx["classes"][owner][k]}
    else:
        pool = set(idx["classes"])
    close = difflib.get_close_matches(name, sorted(pool), n=5, cutoff=0.6)
    if close:
        out.append("Did you mean: " + ", ".join(f"{cls}.{c}" if cls else c for c in close))
    if cls:
        elsewhere = [c for c, data in idx["classes"].items() if any(name in data[k] for k in KINDS)]
        if elsewhere:
            out.append(f"{name} exists on: " + ", ".join(elsewhere[:12]) + (" ..." if len(elsewhere) > 12 else ""))
    return out


def lookup(idx: dict, query: str, full: bool = False) -> str:
    query = query.strip().removesuffix("()")
    cls, dot, name = query.partition(".")
    if dot:
        if cls not in idx["classes"]:
            raise NotFound("\n".join([f"No class {cls} in Godot {idx['godot']}."] + suggest(idx, cls)))
        hits = find_member(idx, cls, name)
        if not hits:
            raise NotFound("\n".join([f"{cls} has no member {name} (searched {' < '.join(ancestors(idx, cls))})."]
                                     + suggest(idx, name, cls)))
        lines = []
        for owner, kind, n, data in hits:
            where = f"   (inherited from {owner})" if owner != cls else ""
            lines.append(f"{owner}.{n}: {member_sig(owner, kind, n, data)}{where}")
        return "\n".join(lines)
    if query in idx["classes"]:
        return class_overview(idx, query, full)
    hits = [(c, k, data[k][query]) for c, data in idx["classes"].items() for k in KINDS if query in data[k]]
    if hits:
        lines = [f"{query} is defined on {len(hits)} class(es):"]
        lines += [f"  {c}.{query}: {member_sig(c, k, query, d)}" for c, k, d in hits[:40]]
        if len(hits) > 40:
            lines.append(f"  ... and {len(hits) - 40} more")
        return "\n".join(lines)
    raise NotFound("\n".join([f"Nothing named {query} in Godot {idx['godot']}."] + suggest(idx, query)))


def search(idx: dict, text: str, limit: int = 60) -> str:
    t = text.lower()
    hits = [c for c in idx["classes"] if t in c.lower()]
    hits += [f"{c}.{n}" for c, data in idx["classes"].items() for k in KINDS for n in data[k] if t in n.lower()]
    if not hits:
        raise NotFound(f"No class or member name contains '{text}'.")
    more = f"\n... {len(hits) - limit} more: narrow the search" if len(hits) > limit else ""
    return f"{len(hits)} match(es):\n" + "\n".join(f"  {h}" for h in hits[:limit]) + more


# --- descriptions from the official docs --------------------------------------------------------------------------

def version_tag(version: str) -> str:
    """'4.7.2.stable.official.ed1daf0bf' -> '4.7.2-stable'; Godot tags leave out a .0 patch ('4.3-stable')."""
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?\.([a-z]+\d*)", version)
    if not m:
        raise SetupError(f"cannot tell the release tag from version {version!r}")
    major, minor, patch, status = m.groups()
    return f"{major}.{minor}" + (f".{patch}" if patch and patch != "0" else "") + f"-{status}"


def bbcode_to_text(text: str) -> str:
    text = re.sub(r"\[codeblocks\](.*?)\[/codeblocks\]",
                  lambda m: (re.search(r"\[gdscript\](.*?)\[/gdscript\]", m.group(1), re.S) or m).group(1),
                  text, flags=re.S)
    text = re.sub(r"\[/?codeblock[^\]]*\]", "\n", text)
    text = re.sub(r"\[/?code\]", "`", text)
    text = re.sub(r"\[(?:method|member|signal|constant|enum|param|annotation|theme_item|constructor|operator) "
                  r"([^\]]+)\]", r"`\1`", text)
    text = re.sub(r"\[url=([^\]]+)\]([^\[]*)\[/url\]", r"\2 (\1)", text)
    text = re.sub(r"\[/?(?:b|i|u|kbd|br|lb|rb|center)\]", "", text)
    text = re.sub(r"\[([A-Z@][\w.]*)\]", r"\1", text)                    # [Node] -> Node
    # The XML indents every line with tabs for its nesting depth; code examples add their own indentation on top.
    text = textwrap.dedent(text.strip("\n").expandtabs(4)) if text.strip() else ""
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def describe(idx: dict, query: str) -> str:
    cls, _, name = query.strip().removesuffix("()").partition(".")
    if cls not in idx["classes"]:
        raise NotFound(f"No class {cls}.")
    owner = cls
    if name:
        hits = find_member(idx, cls, name)
        if not hits:
            raise NotFound(f"{cls} has no member {name}.")
        owner = hits[0][0]
    url = GITHUB_RAW.format(tag=version_tag(idx["godot"]), path=idx["classes"][owner]["file"])
    root = ET.fromstring(netlib.request(url, ttl=30 * 86400, source="GitHub (Godot docs)"))
    if not name:
        el = root
        parts = [bbcode_to_text(root.findtext(tag) or "") for tag in ("brief_description", "description")]
        text = "\n\n".join(p for p in parts if p)
    else:
        el = next((e for e in root.iter() if e.get("name") == name and e.tag in
                   ("method", "member", "signal", "constant", "annotation", "theme_item")), None)
        if el is None:
            raise NotFound(f"{owner}.{name} is not in the official docs file ({url})")
        text = bbcode_to_text(el.findtext("description") or el.text or "")
    notes = [f"DEPRECATED: {bbcode_to_text(el.get('deprecated'))}" for _ in [0] if el.get("deprecated") is not None]
    notes += [f"EXPERIMENTAL: {bbcode_to_text(el.get('experimental'))}" for _ in [0]
              if el.get("experimental") is not None]
    body = text or "(no description in the official docs)"
    return "\n".join(notes + [body, f"\nSource: {url}"])


# --- entry points -------------------------------------------------------------------------------------------------

def answer(project: Path | None, query: str, *, full: bool = False, find: bool = False, desc: bool = False,
           godot: str | None = None) -> str:
    """One lookup, for the CLI and the MCP server. Raises NotFound, SetupError or netlib.NetError."""
    idx = load_index(find_godot(godot, project))
    if find:
        return search(idx, query)
    text = lookup(idx, query, full)
    if desc:
        try:
            text += "\n\n" + describe(idx, query)
        except netlib.NetError as e:
            text += f"\n\n(description unavailable: {e})"
    return text


def main(argv: list[str] | None = None) -> int:
    netlib.force_utf8_output()
    ap = argparse.ArgumentParser(description="Exact Godot API of the project's Godot version.")
    ap.add_argument("query", help="Class, Class.member, member, or text with --search")
    ap.add_argument("--search", action="store_true", help="list names that contain the text")
    ap.add_argument("--full", action="store_true", help="with a class: every signature")
    ap.add_argument("--describe", action="store_true", help="add the official description (downloads once)")
    ap.add_argument("--project", default=".", help="project folder, for toolkit.json's Godot path (default: .)")
    ap.add_argument("--godot", help="Godot executable or folder")
    ap.add_argument("--refresh", action="store_true", help="rebuild the cached index")
    a = ap.parse_args(argv)
    project = Path(a.project).resolve()
    try:
        if a.refresh:
            load_index(find_godot(a.godot, project), refresh=True)
        print(answer(project, a.query, full=a.full, find=a.search, desc=a.describe, godot=a.godot))
        return 0
    except NotFound as e:
        print(e)
        return 1
    except (SetupError, netlib.NetError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
