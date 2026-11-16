#!/usr/bin/env python3
"""Draw the pack icons (512x512 PNG) with the standard library only.

    python tools/make_icons.py

core:  a ring around a dot, on deep blue (the center everything else builds on)
godot: a play triangle in a rounded frame, on dark green (run the game)
"""
from __future__ import annotations

import math
import sys
import struct
import zlib
from pathlib import Path

SIZE = 512
SS = 3  # supersampling per axis, for smooth edges
ROOT = Path(__file__).resolve().parent.parent


def rounded_rect_sd(x: float, y: float, cx: float, cy: float, half: float, r: float) -> float:
    """Signed distance to a rounded square (negative inside)."""
    qx, qy = abs(x - cx) - (half - r), abs(y - cy) - (half - r)
    outside = math.hypot(max(qx, 0), max(qy, 0))
    return outside + min(max(qx, qy), 0) - r


def triangle_sd(x: float, y: float, pts: list[tuple[float, float]]) -> float:
    """Signed distance to a convex triangle given clockwise (negative inside)."""
    d = float("inf")
    inside = True
    for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
        ex, ey = bx - ax, by - ay
        wx, wy = x - ax, y - ay
        t = max(0.0, min(1.0, (wx * ex + wy * ey) / (ex * ex + ey * ey)))
        d = min(d, math.hypot(wx - ex * t, wy - ey * t))
        if ex * wy - ey * wx < 0:
            inside = False
    return -d if inside else d


def render(shape, bg: tuple[int, int, int], fg: tuple[int, int, int]) -> bytes:
    rows = []
    c = SIZE / 2
    for py in range(SIZE):
        row = bytearray([0])  # PNG filter type 0
        for px in range(SIZE):
            cover_bg = cover_fg = 0
            for sy in range(SS):
                for sx in range(SS):
                    x = px + (sx + 0.5) / SS
                    y = py + (sy + 0.5) / SS
                    if rounded_rect_sd(x, y, c, c, SIZE / 2, SIZE * 0.22) <= 0:
                        cover_bg += 1
                        if shape(x, y) <= 0:
                            cover_fg += 1
            n = SS * SS
            a = cover_bg / n
            f = cover_fg / max(cover_bg, 1)
            rgb = [round(bg[i] * (1 - f) + fg[i] * f) for i in range(3)]
            row += bytes(rgb + [round(a * 255)])
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def core_shape(x: float, y: float) -> float:
    c = SIZE / 2
    r = math.hypot(x - c, y - c)
    ring = abs(r - SIZE * 0.27) - SIZE * 0.045
    dot = r - SIZE * 0.095
    return min(ring, dot)


def godot_shape(x: float, y: float) -> float:
    c = SIZE / 2
    frame = abs(rounded_rect_sd(x, y, c, c, SIZE * 0.31, SIZE * 0.09)) - SIZE * 0.03
    s = SIZE
    play = triangle_sd(x, y, [(s * 0.42, s * 0.36), (s * 0.66, s * 0.5), (s * 0.42, s * 0.64)])
    return min(frame, play)


def capsule_sd(x: float, y: float, ax: float, ay: float, bx: float, by: float, r: float) -> float:
    """Signed distance to a line segment with round ends of radius r."""
    px, py, ex, ey = x - ax, y - ay, bx - ax, by - ay
    t = max(0.0, min(1.0, (px * ex + py * ey) / (ex * ex + ey * ey)))
    return math.hypot(px - ex * t, py - ey * t) - r


def box_sd(x: float, y: float, cx: float, cy: float, hw: float, hh: float, r: float) -> float:
    """Signed distance to a rounded rectangle with half-width hw and half-height hh."""
    qx, qy = abs(x - cx) - (hw - r), abs(y - cy) - (hh - r)
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def deps_shape(x: float, y: float) -> float:
    """Three stacked packages, outlined."""
    s = SIZE
    boxes = [box_sd(x, y, s * 0.5, s * (0.33 + 0.17 * i), s * 0.22, s * 0.065, s * 0.025) for i in range(3)]
    return min(abs(b) - s * 0.022 for b in boxes)


def brief_shape(x: float, y: float) -> float:
    """A sun: a disc and eight rays."""
    c, s = SIZE / 2, SIZE
    disc = math.hypot(x - c, y - c) - s * 0.15
    rays = min(capsule_sd(x, y, c + math.cos(a) * s * 0.23, c + math.sin(a) * s * 0.23,
                          c + math.cos(a) * s * 0.33, c + math.sin(a) * s * 0.33, s * 0.03)
               for a in [i * math.pi / 4 for i in range(8)])
    return min(disc, rays)


def audit_shape(x: float, y: float) -> float:
    """A magnifying glass."""
    s = SIZE
    cx, cy = s * 0.44, s * 0.44
    ring = abs(math.hypot(x - cx, y - cy) - s * 0.17) - s * 0.04
    handle = capsule_sd(x, y, s * 0.57, s * 0.57, s * 0.72, s * 0.72, s * 0.05)
    return min(ring, handle)


def main() -> None:
    icons = {
        "core": (core_shape, (37, 56, 140), (240, 244, 255)),
        "godot": (godot_shape, (24, 92, 70), (236, 252, 244)),
        "deps": (deps_shape, (150, 72, 24), (255, 243, 232)),
        "brief": (brief_shape, (18, 110, 140), (255, 246, 214)),
        "audit": (audit_shape, (88, 50, 130), (244, 236, 255)),
    }
    only = set(sys.argv[1:])
    for pack, (shape, bg, fg) in icons.items():
        if only and pack not in only:
            continue
        out = ROOT / "packs" / pack / ".claude-plugin" / "icon.png"
        out.write_bytes(render(shape, bg, fg))
        print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
