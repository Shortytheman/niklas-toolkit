#!/usr/bin/env python3
"""Copy shared modules into the packs that use them (packs are installed separately and cannot share imports).

    python tools/sync_shared.py          copy
    python tools/sync_shared.py --check  exit 1 if a copy differs from the master (used by the tests)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPIES = {
    "shared/netlib.py": ["packs/deps/scripts/netlib.py", "packs/brief/scripts/netlib.py",
                         "packs/godot/scripts/netlib.py"],
}
HEADER = "# GENERATED from {src} by tools/sync_shared.py; edit the master copy, not this file.\n"


def expected(src: str) -> str:
    return HEADER.format(src=src) + (ROOT / src).read_text(encoding="utf-8")


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for src, targets in COPIES.items():
        want = expected(src)
        for t in targets:
            path = ROOT / t
            if check:
                if not path.is_file() or path.read_text(encoding="utf-8") != want:
                    stale.append(t)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(want, encoding="utf-8", newline="\n")
                print(f"wrote {t}")
    if stale:
        print("out of date (run python tools/sync_shared.py): " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
