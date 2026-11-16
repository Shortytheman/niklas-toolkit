#!/usr/bin/env python3
"""Report the license of every dependency and flag the ones that need a closer look.

Runs without Claude. Standard library only, no API keys. This is an inventory, not legal advice: registries
report what package authors declared, which can be missing or wrong.

    python licenses.py [project_dir] [--direct-only] [--fail-on copyleft|unknown] [--json]

Categories:
    permissive      MIT, BSD, Apache, ISC, Zlib, Unlicense, PSF, CC0, BSL-1.0, ...
    weak copyleft   LGPL, MPL, EPL, CDDL: usually fine to use, changes to the library itself must be shared
    copyleft        GPL, AGPL, SSPL, EUPL, OSL: can require releasing your own code; check before shipping
    unknown         nothing declared, or a name this script does not recognize

Exit codes: 0 report done, 1 a category named by --fail-on was found, 2 setup problem.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import netlib  # noqa: E402
from lockfiles import scan  # noqa: E402
from registry import lookup_all  # noqa: E402

PERMISSIVE = r"MIT|BSD|Apache|ISC|Zlib|Unlicense|PSF|Python Software Foundation|CC0|BSL-1\.0|Boost|0BSD|WTFPL|" \
             r"X11|Artistic|PostgreSQL|NCSA|BlueOak|Public Domain|HPND|Unicode"
WEAK = r"LGPL|Lesser General Public|MPL|Mozilla|EPL|Eclipse|CDDL"
STRONG = r"AGPL|Affero|\bGPL|General Public License|SSPL|EUPL|OSL|CC-BY-SA|CPAL"
CATEGORIES = ["copyleft", "weak copyleft", "unknown", "permissive"]


def classify(license_text: str) -> str:
    """For an expression like 'MIT OR GPL-3.0' the most permissive choice counts (you may pick it);
    for 'MIT AND GPL-3.0' the strictest does."""
    text = (license_text or "").strip()
    if not text or text.upper() in ("UNKNOWN", "NONE", "SEE LICENSE IN LICENSE", "UNLICENSED"):
        return "unknown"
    if " OR " in text.upper() or "/" in text:
        parts = re.split(r"\s+OR\s+|/", text, flags=re.IGNORECASE)
        return min((classify(p.strip("() ")) for p in parts), key=lambda c: (c == "unknown", -CATEGORIES.index(c)))
    if " AND " in text.upper():
        parts = re.split(r"\s+AND\s+", text, flags=re.IGNORECASE)
        return min((classify(p.strip("() ")) for p in parts), key=CATEGORIES.index)
    if re.search(WEAK, text, re.IGNORECASE):
        return "weak copyleft"
    if re.search(STRONG, text, re.IGNORECASE):
        return "copyleft"
    if re.search(PERMISSIVE, text, re.IGNORECASE):
        return "permissive"
    return "unknown"


def main(argv: list[str] | None = None) -> int:
    netlib.force_utf8_output()
    ap = argparse.ArgumentParser(description="Inventory of dependency licenses.")
    ap.add_argument("project", nargs="?", default=".", help="project folder (default: .)")
    ap.add_argument("--direct-only", action="store_true", help="only dependencies the project lists itself")
    ap.add_argument("--fail-on", action="append", choices=["copyleft", "weak-copyleft", "unknown"],
                    help="exit 1 when this category is present (repeatable)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    root = Path(args.project).resolve()
    result = scan(root)
    if not result.files:
        print(f"No dependency files found in {root}.", file=sys.stderr)
        return 2
    packages = [p for p in result.packages if p.direct or not args.direct_only]
    packages += [p for p in result.unpinned]
    infos = lookup_all(packages)

    groups: dict[str, list[tuple]] = defaultdict(list)
    for p, info in infos.items():
        lic = info.license if not info.error else ""
        groups[classify(lic)].append((p, lic or ("lookup failed" if info.error else "not declared")))

    if args.json:
        print(json.dumps({c: [{"ecosystem": p.ecosystem, "name": p.name, "license": lic, "direct": p.direct}
                              for p, lic in sorted(rows, key=lambda r: r[0].name)]
                          for c, rows in groups.items()}, indent=2))
    else:
        print(f"{root.name}: {len(packages)} package(s)  |  " +
              ", ".join(f"{len(groups[c])} {c}" for c in CATEGORIES if groups[c]))
        for category in CATEGORIES:
            rows = sorted(groups[category], key=lambda r: r[0].name)
            if not rows:
                continue
            if category == "permissive":
                counts: dict[str, int] = defaultdict(int)
                for _, lic in rows:
                    counts[lic] += 1
                print(f"\npermissive: " + ", ".join(f"{lic} x{n}" for lic, n in sorted(counts.items(),
                                                                                      key=lambda kv: -kv[1])))
                continue
            print(f"\n{category} ({len(rows)}):")
            for p, lic in rows:
                print(f"  {p.name} {p.version}  {lic}  ({p.ecosystem}, {'direct' if p.direct else 'transitive'})")
        print("\nDeclared licenses from the registries; this is an inventory, not legal advice.")

    wanted = {c.replace("-", " ") for c in (args.fail_on or [])}
    return 1 if any(groups[c] for c in wanted) else 0


if __name__ == "__main__":
    sys.exit(main())
