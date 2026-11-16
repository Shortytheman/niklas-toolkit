"""Read-only index of a Godot 4 project: scene trees, resource usages, symbol definitions, unused files.

Standard library only. Used by server.py (the MCP server) and usable on its own:

    python godot_index.py <project> tree res://main.tscn
    python godot_index.py <project> usages res://art/icon.png
    python godot_index.py <project> symbol Player
    python godot_index.py <project> unused res://art
"""
from __future__ import annotations

import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Files whose text can reference other resources.
TEXT_EXTS = {".gd", ".tscn", ".tres", ".godot", ".cfg", ".csv", ".json", ".gdshader", ".gdshaderinc", ".import"}
# Files that are resources in their own right (candidates for "unused").
RESOURCE_EXTS = {".tscn", ".tres", ".gd", ".gdshader", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".wav", ".ogg",
                 ".mp3", ".ttf", ".otf", ".woff", ".woff2", ".glb", ".gltf", ".obj", ".fbx", ".csv", ".json"}
SKIP_DIRS = {".godot", ".git", ".import", "__pycache__", "node_modules"}

RES_PATH = re.compile(r"res://[^\"'\s()\[\]{}<>,;|]+")  # stops at BBCode too: [img]res://x.png[/img]
UID_REF = re.compile(r"uid://[a-z0-9]+")
WORD = re.compile(r"\b\w+\b")
DYNAMIC_PREFIX = re.compile(r"[\"'](res://[^\"'%{}]*?/)(?:[^\"'/]*%[sd]|[^\"'/]*\{)|[\"'](res://[^\"']*/)[\"']\s*\+")


def to_res(project: Path, path: Path) -> str:
    s, p = str(path), str(project)
    if s.startswith(p) and s[len(p):len(p) + 1] in ("\\", "/"):  # fast path: plain string work, no pathlib
        return "res://" + s[len(p) + 1:].replace("\\", "/")
    return "res://" + path.relative_to(project).as_posix()


def from_res(project: Path, res: str) -> Path:
    return project / res[len("res://"):] if res.startswith("res://") else project / res


@dataclass
class Index:
    project: Path
    files: list[Path] = field(default_factory=list)          # every file Godot would see
    uid_to_res: dict[str, str] = field(default_factory=dict)
    refs: dict[str, list[tuple[str, int]]] = field(default_factory=lambda: defaultdict(list))  # target -> (file, line)
    dynamic_prefixes: set[str] = field(default_factory=set)
    texts: dict[Path, str] = field(default_factory=dict)      # .gd/.tscn/.tres contents, read once

    def text(self, f: Path) -> str:
        if f not in self.texts:
            self.texts[f] = f.read_text(encoding="utf-8", errors="replace")
        return self.texts[f]

    @classmethod
    def build(cls, project: Path) -> "Index":
        idx = cls(project.resolve())
        idx._walk()
        idx._read_uids()
        idx._read_refs()
        return idx

    def _walk(self) -> None:
        for root, dirs, files in os.walk(self.project):
            if ".gdignore" in files:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            self.files.extend(Path(root) / f for f in files)

    def _read_uids(self) -> None:
        for f in self.files:
            if f.suffix == ".uid":  # Godot 4.4+: script.gd.uid holds the script's uid
                uid = f.read_text(encoding="utf-8", errors="replace").strip()
                self.uid_to_res[uid] = to_res(self.project, f.with_suffix(""))
            elif f.suffix == ".import":
                m = re.search(r'^uid="(uid://[a-z0-9]+)"', f.read_text(encoding="utf-8", errors="replace"), re.M)
                if m:
                    self.uid_to_res[m.group(1)] = to_res(self.project, f.with_suffix(""))
            elif f.suffix in (".tscn", ".tres"):
                with f.open(encoding="utf-8", errors="replace") as fh:
                    m = re.search(r'uid="(uid://[a-z0-9]+)"', fh.readline())
                if m:
                    self.uid_to_res[m.group(1)] = to_res(self.project, f)

    def _read_refs(self) -> None:
        for f in self.files:
            if f.suffix not in TEXT_EXTS or f.suffix == ".import" or f.name == "toolkit.json":
                continue  # toolkit.json is the toolkit's own settings, not game data
            src = to_res(self.project, f)
            try:
                text = self.text(f) if f.suffix in (".gd", ".tscn", ".tres") else \
                    f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = text.splitlines()
            is_gd = f.suffix == ".gd"
            for n, line in enumerate(lines, 1):
                if is_gd and line.lstrip().startswith("#"):
                    continue  # a path in a GDScript comment is not a use
                targets = set(RES_PATH.findall(line))
                targets.update(self.uid_to_res[u] for u in UID_REF.findall(line) if u in self.uid_to_res)
                if line.lstrip().startswith("[gd_scene") or line.lstrip().startswith("[gd_resource"):
                    targets.discard(src)  # a file's own uid in its header is not a use
                for t in targets:
                    if t != src:
                        self.refs[t].append((src, n))
                for m in DYNAMIC_PREFIX.finditer(line):
                    self.dynamic_prefixes.add(m.group(1) or m.group(2))
        # A res:// string naming a folder ("res://art/props", often a const) means files there are loaded by name.
        for target in list(self.refs):
            if from_res(self.project, target.rstrip("/")).is_dir():
                self.dynamic_prefixes.add(target.rstrip("/") + "/")
                del self.refs[target]

    # ------------------------------------------------------------ queries

    def resolve(self, path: str) -> str:
        if path.startswith("uid://"):
            return self.uid_to_res.get(path, path)
        if path.startswith("res://"):
            return path
        p = Path(path)
        if p.is_absolute():
            return to_res(self.project, p.resolve())
        return "res://" + path.replace("\\", "/").lstrip("./")

    def usages(self, path: str) -> list[tuple[str, int]]:
        return sorted(set(self.refs.get(self.resolve(path), [])))

    def class_names(self) -> dict[str, str]:
        names = {}
        for f in self.files:
            if f.suffix == ".gd":
                with f.open(encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        m = re.match(r"\s*class_name\s+(\w+)", line)
                        if m:
                            names[to_res(self.project, f)] = m.group(1)
                            break
        return names

    def unused(self, folder: str = "res://") -> list[tuple[str, str]]:
        """Resources nothing references. Returns (res path, note); note says when a dynamic load may still use it."""
        folder = self.resolve(folder).rstrip("/") + "/"
        class_names = self.class_names()
        word_cache: dict[str, bool] = {}
        code = None
        out = []
        for f in self.files:
            if f.suffix not in RESOURCE_EXTS:
                continue
            res = to_res(self.project, f)
            if not res.startswith(folder) or self.refs.get(res):
                continue
            name = class_names.get(res)
            if name:  # a script with class_name is used by its name, not its path
                if code is None:
                    code = Counter(WORD.findall("\n".join(
                        self.text(p) for p in self.files if p.suffix in (".gd", ".tscn", ".tres"))))
                if name not in word_cache:  # used if the name appears anywhere besides its own file
                    word_cache[name] = code[name] > WORD.findall(self.text(f)).count(name)
                if word_cache[name]:
                    continue
            dyn = next((p for p in sorted(self.dynamic_prefixes) if res.startswith(p)), None)
            out.append((res, f"may be loaded dynamically via {dyn}..." if dyn else ""))
        return sorted(out)

    def symbol(self, name: str) -> list[tuple[str, int, str]]:
        pattern = re.compile(
            rf"^\s*(?:static\s+)?(?:class_name|class|func|signal|const|var|enum|@export\S*\s+var|@onready\s+var)"
            rf"\s+{re.escape(name)}\b")
        hits = []
        for f in self.files:
            if f.suffix != ".gd":
                continue
            with f.open(encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    if pattern.match(line):
                        hits.append((to_res(self.project, f), n, line.strip()))
        project_godot = self.project / "project.godot"
        if project_godot.is_file():
            for n, line in enumerate(project_godot.read_text(encoding="utf-8").splitlines(), 1):
                if re.match(rf"^{re.escape(name)}=\"\*?res://", line):
                    hits.append(("res://project.godot", n, f"autoload {line.strip()}"))
        return hits


# ---------------------------------------------------------------- doctor

@dataclass
class Finding:
    check: str     # broken-path, wrong-case, stale-uid, unknown-uid, unused
    severity: str  # error | warning | info
    file: str      # where the reference is (or the unused file itself)
    line: int
    message: str


EXT_RESOURCE = re.compile(r'^\[ext_resource\b[^\]]*?\]', re.M)


def _is_concrete(ref: str) -> bool:
    """A literal path, not a prefix for building one ("res://icons/" + name, "res://x/%s.png")."""
    return len(ref) > len("res://") and not ref.endswith("/") and not any(c in ref for c in "%{}$*")


def doctor(idx: Index, include_unused: bool = False) -> list[Finding]:
    """Problems that break at runtime or only after export, found without running Godot.

    broken-path  a res:// path that points at nothing
    wrong-case   a path whose letter case differs from the file on disk: works on Windows, breaks in exports
                 and on Linux/macOS, because the exported .pck is case-sensitive
    stale-uid    an ext_resource whose uid names a different file than its path (Godot follows the uid)
    unknown-uid  a uid:// reference no file in the project owns
    duplicate-class  two scripts declare the same class_name; Godot keeps only one of them
    orphan-file  a .import or .uid file whose source file is gone (left behind by a delete or rename
                 outside the editor)
    unused       resources nothing references (info only, with --unused)
    """
    project = idx.project
    files = {to_res(project, f) for f in idx.files}
    actual = set(files)
    for res in files:  # folders too, so "res://dir" counts as existing
        while (cut := res.rfind("/")) > len("res://"):
            res = res[:cut]
            if res in actual:
                break
            actual.add(res)
    lower = {}
    for a in actual:
        lower.setdefault(a.lower(), a)

    findings: list[Finding] = []
    for target, places in sorted(idx.refs.items()):
        if not _is_concrete(target) or target in actual or target.startswith("res://.godot/"):
            continue
        real = lower.get(target.lower())
        for src, line in places:
            if real:
                findings.append(Finding("wrong-case", "error", src, line,
                                        f"{target} differs in case from the file {real}; exports will not find it"))
            else:
                findings.append(Finding("broken-path", "error", src, line, f"{target} does not exist"))

    for f in idx.files:
        if f.suffix not in (".tscn", ".tres", ".gd"):
            continue
        src = to_res(project, f)
        text = idx.text(f)
        if f.suffix != ".gd":
            for m in EXT_RESOURCE.finditer(text):
                uid = re.search(r'\buid="(uid://[a-z0-9]+)"', m.group(0))
                path = re.search(r'\bpath="([^"]+)"', m.group(0))
                line = text.count("\n", 0, m.start()) + 1
                if not uid:
                    continue
                owner = idx.uid_to_res.get(uid.group(1))
                if owner is None:
                    if path and path.group(1) not in actual:
                        continue  # already reported as broken-path
                    findings.append(Finding("unknown-uid", "warning", src, line,
                                            f"{uid.group(1)} belongs to no file; Godot falls back to "
                                            f"{path.group(1) if path else 'nothing'}"))
                elif path and owner != path.group(1) and path.group(1) in actual:
                    findings.append(Finding("stale-uid", "warning", src, line,
                                            f"uid {uid.group(1)} is {owner}, but the path says {path.group(1)}; "
                                            f"Godot loads {owner}"))
        for n, line_text in enumerate(text.splitlines(), 1):
            if line_text.lstrip().startswith(("#", ";")) or (f.suffix != ".gd" and line_text.startswith("[gd_")):
                continue
            for uid in UID_REF.findall(line_text):
                if uid not in idx.uid_to_res and 'uid="' + uid not in line_text:
                    findings.append(Finding("unknown-uid", "error", src, n, f"{uid} belongs to no file"))

    by_class: dict[str, list[str]] = defaultdict(list)
    for res, name in idx.class_names().items():
        by_class[name].append(res)
    for name, scripts in sorted(by_class.items()):
        if len(scripts) > 1:
            for res in sorted(scripts):
                others = ", ".join(s for s in sorted(scripts) if s != res)
                findings.append(Finding("duplicate-class", "error", res, 1,
                                        f"class_name {name} is also declared in {others}"))

    for f in idx.files:
        if f.suffix in (".import", ".uid") and to_res(project, f)[:-len(f.suffix)] not in files:
            findings.append(Finding("orphan-file", "warning", to_res(project, f), 0,
                                    f"{f.with_suffix('').name} is gone; delete this {f.suffix} file"))

    if include_unused:
        for res, note in idx.unused():
            if not note:
                findings.append(Finding("unused", "info", res, 0, "nothing references this file"))
    return findings


# ---------------------------------------------------------------- scene tree

@dataclass
class SceneNode:
    name: str
    type: str
    parent: str | None
    script: str = ""
    instance: str = ""
    groups: str = ""


def parse_scene(text: str) -> tuple[list[SceneNode], dict[str, str]]:
    """Nodes of a .tscn file in file order, plus ext_resource id -> path."""
    ext: dict[str, str] = {}
    nodes: list[SceneNode] = []
    current: SceneNode | None = None
    for line in text.splitlines():
        if line.startswith("[ext_resource"):
            rid = re.search(r'\bid="([^"]+)"', line)
            path = re.search(r'\bpath="([^"]+)"', line)
            if rid and path:
                ext[rid.group(1)] = path.group(1)
            current = None
        elif line.startswith("[node "):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', line))
            inst = re.search(r'instance=ExtResource\(\s*"([^"]+)"\s*\)', line)
            groups = re.search(r"groups=\[([^\]]*)\]", line)
            current = SceneNode(attrs.get("name", "?"), attrs.get("type", ""), attrs.get("parent"),
                                instance=ext.get(inst.group(1), "") if inst else "",
                                groups=groups.group(1).replace('"', "") if groups else "")
            nodes.append(current)
        elif line.startswith("["):
            current = None
        elif current is not None:
            m = re.match(r'script\s*=\s*ExtResource\(\s*"([^"]+)"\s*\)', line)
            if m:
                current.script = ext.get(m.group(1), m.group(1))
    return nodes, ext


def scene_tree(project: Path, scene: str, max_nodes: int = 300) -> str:
    path = from_res(project, scene)
    if not path.is_file():
        raise FileNotFoundError(f"scene not found: {scene}")
    nodes, _ = parse_scene(path.read_text(encoding="utf-8", errors="replace"))
    if not nodes:
        return f"{scene}: no nodes"
    root = nodes[0]
    lines = [f"{scene}"]

    def describe(n: SceneNode) -> str:
        bits = [n.name]
        if n.type:
            bits.append(f"({n.type})")
        if n.instance:
            bits.append(f"[instance {n.instance}]")
        if n.script:
            bits.append(f"script={n.script}")
        if n.groups:
            bits.append(f"groups=[{n.groups}]")
        return " ".join(bits)

    lines.append(describe(root))
    for n in nodes[1:max_nodes]:
        depth = 1 if n.parent in (None, ".") else n.parent.count("/") + 2
        lines.append("  " * depth + describe(n))
    if len(nodes) > max_nodes:
        lines.append(f"... {len(nodes) - max_nodes} more nodes")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    project, cmd, arg = Path(argv[0]), argv[1], argv[2]
    if cmd == "tree":
        print(scene_tree(project, arg))
        return 0
    idx = Index.build(project)
    if cmd == "usages":
        for f, n in idx.usages(arg):
            print(f"{f}:{n}")
    elif cmd == "symbol":
        for f, n, text in idx.symbol(arg):
            print(f"{f}:{n}: {text}")
    elif cmd == "unused":
        for res, note in idx.unused(arg):
            print(res + (f"  ({note})" if note else ""))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
