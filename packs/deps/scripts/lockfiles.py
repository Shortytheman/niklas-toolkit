"""Find and read dependency files: lockfiles (exact versions) and manifests (direct dependencies).

Standard library only; works on Python 3.10 (no tomllib there, so TOML lockfiles use a small fallback reader).

Supported, with the OSV ecosystem name each maps to:
    PyPI       requirements*.txt (pinned ==), poetry.lock, uv.lock, Pipfile.lock, pdm.lock; pyproject.toml (direct)
    npm        package-lock.json / npm-shrinkwrap.json (v1-v3), yarn.lock (v1 and berry), pnpm-lock.yaml;
               package.json (direct)
    crates.io  Cargo.lock; Cargo.toml (direct)
    Go         go.sum; go.mod (direct)
    Packagist  composer.lock
    RubyGems   Gemfile.lock
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - exercised on 3.10 in CI
    tomllib = None

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "target", "vendor", "dist", "build",
             ".godot", ".tox", ".mypy_cache", ".pytest_cache", "site-packages"}


@dataclass(frozen=True)
class Package:
    ecosystem: str
    name: str
    version: str          # exact version, or "" when the file does not pin one
    source: str           # the file it came from, relative to the project
    direct: bool = False  # listed in a manifest, not only pulled in by something else


@dataclass
class Scan:
    packages: list[Package] = field(default_factory=list)
    unpinned: list[Package] = field(default_factory=list)  # direct deps without an exact version
    files: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def normalize(ecosystem: str, name: str) -> str:
    """PyPI names compare case- and separator-insensitively (PEP 503); others are kept as written."""
    return re.sub(r"[-_.]+", "-", name).lower() if ecosystem == "PyPI" else name


# ---------------------------------------------------------------- TOML

def load_toml(text: str) -> dict:
    if tomllib is not None:
        return tomllib.loads(text)
    return _mini_toml(text)


def _mini_toml(text: str) -> dict:
    """Enough TOML for lockfiles and simple manifests: tables, arrays of tables, strings, numbers, booleans,
    and one-line arrays/inline tables of strings. Not a general parser."""
    root: dict = {}
    current = root
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^\[\[([^\]]+)\]\]$", line)
        if m:
            current = {}
            _dig(root, m.group(1), array=True).setdefault("__list__", []).append(current)
            continue
        m = re.match(r"^\[([^\]]+)\]$", line)
        if m:
            current = _dig(root, m.group(1))
            continue
        m = re.match(r'^("?)([^"=]+)\1\s*=\s*(.+)$', line)
        if m:
            current[m.group(2).strip()] = _toml_value(m.group(3).strip())
    return _unlist(root)


def _dig(root: dict, dotted: str, array: bool = False) -> dict:
    """The table a header names. Inside an array of tables ([[package]]), a sub-table such as
    [package.dependencies] belongs to the latest element; `array` returns the array holder itself."""
    parts = [p.strip().strip('"') for p in dotted.split(".")]
    node = root
    for i, part in enumerate(parts):
        nxt = node.setdefault(part, {})
        last = i == len(parts) - 1
        if isinstance(nxt, dict) and nxt.get("__list__") and not (last and array):
            nxt = nxt["__list__"][-1]
        node = nxt
    return node


def _unlist(node):
    if isinstance(node, dict):
        if set(node) == {"__list__"}:
            return [_unlist(x) for x in node["__list__"]]
        return {k: _unlist(v) for k, v in node.items()}
    return node


def _toml_value(v: str):
    if v.startswith('"'):
        m = re.match(r'^"((?:[^"\\]|\\.)*)"', v)
        return m.group(1) if m else v.strip('"')
    if v.startswith("'"):
        return v.split("'")[1]
    if v.startswith("["):
        return re.findall(r'"((?:[^"\\]|\\.)*)"', v)
    if v.startswith("{"):
        return dict(re.findall(r'(\w[\w-]*)\s*=\s*"([^"]*)"', v))
    if v in ("true", "false"):
        return v == "true"
    try:
        return int(v)
    except ValueError:
        return v


# ---------------------------------------------------------------- readers

def read_requirements(path: Path, rel: str, seen: set | None = None) -> tuple[list[Package], list[Package]]:
    seen = seen or set()
    if path in seen:
        return [], []
    seen.add(path)
    pinned, unpinned = [], []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split(" #")[0].strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r ", "--requirement ")):
            inc = path.parent / line.split(None, 1)[1].strip()
            if inc.is_file():
                p, u = read_requirements(inc, rel, seen)
                pinned += p
                unpinned += u
            continue
        if line.startswith("-") or "://" in line or line.startswith((".", "/")):
            continue
        line = line.split(";")[0].split("--hash")[0].strip().rstrip("\\").strip()
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*)$", line)
        if not m:
            continue
        name, spec = m.group(1), m.group(3).strip()
        exact = re.fullmatch(r"===?\s*([^\s,;]+)", spec)
        pkg = Package("PyPI", normalize("PyPI", name), exact.group(1) if exact else "", rel, True)
        (pinned if exact else unpinned).append(pkg)
    return pinned, unpinned


def _toml_packages(path: Path, rel: str, ecosystem: str) -> list[Package]:
    data = load_toml(path.read_text(encoding="utf-8", errors="replace"))
    out = []
    for p in data.get("package", []) or []:
        if isinstance(p, dict) and p.get("name") and p.get("version"):
            source = p.get("source")
            if isinstance(source, dict) and (source.get("editable") or source.get("virtual") or source.get("path")):
                continue  # the project itself or a local path dependency
            out.append(Package(ecosystem, normalize(ecosystem, p["name"]), str(p["version"]), rel))
    return out


def read_pipfile_lock(path: Path, rel: str) -> list[Package]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for section in ("default", "develop"):
        for name, info in (data.get(section) or {}).items():
            v = str(info.get("version", "")).lstrip("=")
            if v:
                out.append(Package("PyPI", normalize("PyPI", name), v, rel))
    return out


def read_pyproject(path: Path, rel: str) -> list[Package]:
    """Direct dependencies from [project.dependencies] / [tool.poetry.dependencies]; versions are usually ranges."""
    data = load_toml(path.read_text(encoding="utf-8", errors="replace"))
    names = []
    for spec in (data.get("project", {}) or {}).get("dependencies", []) or []:
        m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(===?\s*([^\s,;]+))?", spec)
        if m:
            names.append((m.group(1), m.group(3) or ""))
    poetry = ((data.get("tool", {}) or {}).get("poetry", {}) or {}).get("dependencies", {}) or {}
    for name, spec in poetry.items():
        if name.lower() != "python":
            exact = spec if isinstance(spec, str) and re.fullmatch(r"\d[\w.]*", spec) else ""
            names.append((name, exact))
    return [Package("PyPI", normalize("PyPI", n), v, rel, True) for n, v in names]


def read_package_lock(path: Path, rel: str) -> list[Package]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    packages = data.get("packages")
    if isinstance(packages, dict):  # lockfileVersion 2 and 3
        for key, info in packages.items():
            if not key or info.get("link") or not info.get("version"):
                continue
            name = info.get("name") or key.split("node_modules/")[-1]
            out.append(Package("npm", name, info["version"], rel))
        return out

    def walk(deps: dict):  # lockfileVersion 1
        for name, info in (deps or {}).items():
            if info.get("version") and not str(info["version"]).startswith(("file:", "link:", "git")):
                out.append(Package("npm", name, info["version"], rel))
            walk(info.get("dependencies"))
    walk(data.get("dependencies"))
    return out


def read_yarn_lock(path: Path, rel: str) -> list[Package]:
    out = []
    names: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line and not line.startswith((" ", "#")) and line.rstrip().endswith(":"):
            names = []
            for spec in line.rstrip(":").split(","):
                spec = spec.strip().strip('"')
                at = spec.rfind("@")
                if at > 0:
                    names.append(spec[:at])
        m = re.match(r'^\s+version:?\s+"?([^"\s]+)"?', line)
        if m and names:
            for n in sorted(set(names)):
                out.append(Package("npm", n, m.group(1), rel))
            names = []
    return out


def read_pnpm_lock(path: Path, rel: str) -> list[Package]:
    out = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        # v6+: "  /name@1.2.3:" or "  name@1.2.3:" or "  '@scope/name@1.2.3(peer@x)':"
        m = re.match(r"^\s{2}'?/?((?:@[^/@\s]+/)?[^@\s/']+)@(\d[^()'\s:]*)", line)
        if m:
            out.add(Package("npm", m.group(1), m.group(2), rel))
            continue
        m = re.match(r"^\s{2}/((?:@[^/\s]+/)?[^/\s]+)/(\d[^:_\s]*)", line)  # v5: "  /name/1.2.3:"
        if m:
            out.add(Package("npm", m.group(1), m.group(2), rel))
    return sorted(out, key=lambda p: (p.name, p.version))


def read_package_json(path: Path, rel: str) -> list[Package]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        for name, spec in (data.get(section) or {}).items():
            exact = spec if isinstance(spec, str) and re.fullmatch(r"\d+\.\d+\.\d+[\w.-]*", spec) else ""
            out.append(Package("npm", name, exact, rel, True))
    return out


def read_cargo_toml(path: Path, rel: str) -> list[Package]:
    data = load_toml(path.read_text(encoding="utf-8", errors="replace"))
    out = []
    for section in ("dependencies", "dev-dependencies", "build-dependencies"):
        for name, spec in (data.get(section) or {}).items():
            out.append(Package("crates.io", name, "", rel, True))
    return out


def read_go_sum(path: Path, rel: str) -> list[Package]:
    out = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and not parts[1].endswith("/go.mod"):
            out.add(Package("Go", parts[0], parts[1].split("/")[0], rel))
    return sorted(out, key=lambda p: (p.name, p.version))


def read_go_mod(path: Path, rel: str) -> list[Package]:
    out = []
    in_block = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.split("//")[0].strip()
        if s.startswith("require ("):
            in_block = True
            continue
        if in_block and s == ")":
            in_block = False
            continue
        m = re.match(r"^(?:require\s+)?(\S+)\s+(v\S+)$", s) if (in_block or s.startswith("require ")) else None
        if m:
            out.append(Package("Go", m.group(1), m.group(2), rel, "// indirect" not in line))
    return out


def read_composer_lock(path: Path, rel: str) -> list[Package]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Package("Packagist", p["name"], str(p["version"]).lstrip("v"), rel)
            for section in ("packages", "packages-dev") for p in (data.get(section) or [])
            if p.get("name") and p.get("version") and not str(p["version"]).startswith("dev-")]


def read_gemfile_lock(path: Path, rel: str) -> list[Package]:
    out = []
    in_specs = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip() == "specs:":
            in_specs = True
            continue
        if in_specs:
            m = re.match(r"^ {4}([^\s(]+) \(([^)-]+)(?:-[^)]+)?\)$", line)
            if m:
                out.append(Package("RubyGems", m.group(1), m.group(2), rel))
            elif line and not line.startswith("  "):
                in_specs = False
    return out


LOCKFILES = {
    "poetry.lock": lambda p, r: _toml_packages(p, r, "PyPI"),
    "uv.lock": lambda p, r: _toml_packages(p, r, "PyPI"),
    "pdm.lock": lambda p, r: _toml_packages(p, r, "PyPI"),
    "Pipfile.lock": read_pipfile_lock,
    "package-lock.json": read_package_lock,
    "npm-shrinkwrap.json": read_package_lock,
    "yarn.lock": read_yarn_lock,
    "pnpm-lock.yaml": read_pnpm_lock,
    "Cargo.lock": lambda p, r: _toml_packages(p, r, "crates.io"),
    "go.sum": read_go_sum,
    "composer.lock": read_composer_lock,
    "Gemfile.lock": read_gemfile_lock,
}
MANIFESTS = {
    "pyproject.toml": read_pyproject,
    "package.json": read_package_json,
    "Cargo.toml": read_cargo_toml,
    "go.mod": read_go_mod,
}


def is_dependency_file(name: str) -> bool:
    return name in LOCKFILES or name in MANIFESTS or bool(re.fullmatch(r"requirements[\w.-]*\.txt", name))


def find_files(root: Path, max_depth: int = 4) -> list[Path]:
    found = []
    root = root.resolve()
    for dirpath, dirs, files in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".") and depth < max_depth]
        found += [Path(dirpath) / f for f in files if is_dependency_file(f)]
    return sorted(found)


def scan(root: Path, files: list[Path] | None = None) -> Scan:
    """Read every dependency file under root (or just `files`). Lockfile versions win over manifest entries."""
    root = root.resolve()
    result = Scan()
    locked: dict[tuple[str, str], Package] = {}
    direct: dict[tuple[str, str], Package] = {}
    for path in files if files is not None else find_files(root):
        path = path.resolve()
        rel = path.relative_to(root).as_posix() if root in path.parents or path.parent == root else str(path)
        result.files.append(rel)
        try:
            if path.name in LOCKFILES:
                for p in LOCKFILES[path.name](path, rel):
                    locked.setdefault((p.ecosystem, p.name, p.version), p)
            elif path.name in MANIFESTS:
                for p in MANIFESTS[path.name](path, rel):
                    direct.setdefault((p.ecosystem, p.name), p)
            else:
                pinned, unpinned = read_requirements(path, rel)
                for p in pinned:
                    locked.setdefault((p.ecosystem, p.name, p.version), p)
                for p in unpinned:
                    direct.setdefault((p.ecosystem, p.name), p)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            result.problems.append(f"{rel}: could not read ({e})")

    direct_names = set(direct)
    for (eco, name, version), p in sorted(locked.items()):
        is_direct = p.direct or (eco, name) in direct_names
        result.packages.append(Package(eco, name, version, p.source, is_direct))
    locked_names = {(p.ecosystem, p.name) for p in result.packages}
    for key, p in sorted(direct.items()):
        if key in locked_names:
            continue
        if p.version:
            result.packages.append(p)
        else:
            result.unpinned.append(p)
    return result
