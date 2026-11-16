"""Package registry lookups (latest version, license) and version comparison. Standard library only, no keys.

Registries: PyPI JSON API, npm registry, crates.io API, Go module proxy, Packagist, RubyGems.
"""
from __future__ import annotations

import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import netlib
from lockfiles import Package

TTL = 6 * 3600  # registry answers are cached for 6 hours


@dataclass
class Info:
    latest: str = ""
    license: str = ""
    error: str = ""


# ---------------------------------------------------------------- versions

def version_key(v: str) -> tuple:
    """Sort key for versions across ecosystems: numbers compare as numbers, and a pre-release
    (1.0.0rc1, 1.0.0-beta.2) sorts before its release."""
    v = v.strip().lstrip("vV=").split("+")[0]  # build metadata (+abc) does not affect order
    m = re.match(r"^(\d+(?:\.\d+)*)(.*)$", v)
    if not m:
        return ((), (0, v))
    nums = tuple(int(x) for x in m.group(1).split("."))
    nums = nums + (0,) * (4 - len(nums))
    rest = m.group(2).lstrip(".-_")
    if not rest:
        return (nums, (1, ""))
    if re.match(r"^(post|p)\d*$", rest):
        return (nums, (2, rest))
    return (nums, (0, rest))  # a, b, rc, alpha, beta, dev...: before the release


def is_prerelease(v: str) -> bool:
    return bool(re.search(r"(a|b|rc|alpha|beta|dev|pre|preview|canary|next)\.?\d*$|-", v.lstrip("vV").split("+")[0],
                          re.IGNORECASE))


def bump_kind(current: str, latest: str) -> str:
    """'major', 'minor', 'patch' or '' when latest is not newer."""
    if not current or not latest or version_key(latest) <= version_key(current):
        return ""
    a, b = version_key(current)[0], version_key(latest)[0]
    if a[0] != b[0] or (a[0] == 0 and a[1] != b[1]):  # 0.x: a minor bump may break, like a major one
        return "major"
    return "minor" if a[1] != b[1] else "patch"


def smallest_fix(current: str, fixed: list[str]) -> str:
    """The lowest fixed version above the current one, or ''."""
    newer = [f for f in fixed if version_key(f) > version_key(current)]
    return min(newer, key=version_key) if newer else ""


# ---------------------------------------------------------------- lookups

def _license_name(value) -> str:
    if isinstance(value, dict):
        return str(value.get("type", ""))
    if isinstance(value, list):
        return " OR ".join(_license_name(v) for v in value if v)
    return str(value or "").strip()


def _pypi(name: str) -> Info:
    d = netlib.get_json(f"https://pypi.org/pypi/{urllib.parse.quote(name)}/json", ttl=TTL, source="PyPI")
    info = d.get("info", {})
    lic = info.get("license_expression") or ""
    if not lic:
        classifiers = [c.split(" :: ")[-1] for c in info.get("classifiers", []) if c.startswith("License ::")]
        raw = (info.get("license") or "").strip()
        lic = ", ".join(classifiers) or (raw if raw and len(raw) < 60 and "\n" not in raw else "")
    return Info(info.get("version", ""), lic)


def _npm(name: str) -> Info:
    d = netlib.get_json(f"https://registry.npmjs.org/{name.replace('/', '%2F')}/latest", ttl=TTL, source="npm")
    return Info(d.get("version", ""), _license_name(d.get("license") or d.get("licenses")))


def _crates(name: str) -> Info:
    d = netlib.get_json(f"https://crates.io/api/v1/crates/{urllib.parse.quote(name)}", ttl=TTL, source="crates.io")
    crate = d.get("crate", {})
    versions = d.get("versions") or [{}]
    return Info(crate.get("max_stable_version") or crate.get("max_version", ""), versions[0].get("license") or "")


def _go(module: str) -> Info:
    escaped = re.sub(r"[A-Z]", lambda m: "!" + m.group(0).lower(), module)
    d = netlib.get_json(f"https://proxy.golang.org/{escaped}/@latest", ttl=TTL, source="Go proxy")
    return Info(d.get("Version", ""), "")


def _packagist(name: str) -> Info:
    d = netlib.get_json(f"https://repo.packagist.org/p2/{name}.json", ttl=TTL, source="Packagist")
    releases = [r for r in (d.get("packages", {}).get(name) or []) if not is_prerelease(str(r.get("version", "")))]
    top = releases[0] if releases else {}
    return Info(str(top.get("version", "")).lstrip("v"), _license_name(top.get("license")))


def _rubygems(name: str) -> Info:
    d = netlib.get_json(f"https://rubygems.org/api/v1/gems/{urllib.parse.quote(name)}.json", ttl=TTL,
                        source="RubyGems")
    return Info(d.get("version", ""), _license_name(d.get("licenses")))


LOOKUPS = {"PyPI": _pypi, "npm": _npm, "crates.io": _crates, "Go": _go, "Packagist": _packagist,
           "RubyGems": _rubygems}


def lookup(pkg: Package) -> Info:
    fn = LOOKUPS.get(pkg.ecosystem)
    if fn is None:
        return Info(error=f"no registry lookup for {pkg.ecosystem}")
    try:
        return fn(pkg.name)
    except netlib.NetError as e:
        return Info(error=str(e))


def lookup_all(packages: list[Package], workers: int = 8) -> dict[Package, Info]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip(packages, pool.map(lookup, packages)))
