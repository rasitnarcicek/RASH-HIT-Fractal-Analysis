# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""Generates the scientific ground-truth SVG fixtures for validation.

Every fixture has a mathematically known box-counting dimension, so the
engines' numbers can be compared against exact theory, not just against
themselves:

  square_full.svg      filled square covering the whole viewBox  -> area Db = 2.000000 (exact)
  horizontal_line.svg  interior horizontal line, full width      -> supercover Db = 1.000000 (exact)
  carpet.svg           Sierpinski carpet recursion (depth 5)     -> area Db = log(8)/log(3) = 1.892789
  gasket.svg           Sierpinski gasket edge recursion (depth 7)-> supercover Db = log(3)/log(2) = 1.584963

Run:  python tools/validation/gen_fixtures.py [outdir]
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "fixtures"


def write_square_full() -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">\n'
        '  <rect x="0" y="0" width="256" height="256" fill="black"/>\n'
        '</svg>'
    )
    (FIXTURES / "square_full.svg").write_text(svg, encoding="utf-8")


def write_horizontal_line() -> None:
    # Non-dyadic y (47.36 = 0.37 * 128) keeps the whole stroke inside one
    # grid row at every doubling level; a full-width horizontal line then
    # occupies exactly `cols` cells per level, so N(L) doubles exactly
    # and Db = 1.0 to machine precision.
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="128" viewBox="0 0 256 128">\n'
        '  <line x1="0" y1="47.36" x2="256" y2="47.36" stroke="black" stroke-width="1"/>\n'
        '</svg>'
    )
    (FIXTURES / "horizontal_line.svg").write_text(svg, encoding="utf-8")


def _carpet_holes(depth: int):
    """Yield (x, y, side) of every removed center square (3^d lattice)."""
    holes = []
    size = 3 ** depth

    def rec(x, y, side, d):
        if d == 0:
            return
        third = side // 3
        for row in range(3):
            for col in range(3):
                if row == 1 and col == 1:
                    holes.append((x + third, y + third, third))
                else:
                    rec(x + col * third, y + row * third, third, d - 1)

    rec(0, 0, size, depth)
    return holes


def write_carpet(depth: int = 5) -> None:
    size = 3 ** depth
    parts = [f"M0 0 H{size} V{size} H0 Z"]
    for x, y, s in _carpet_holes(depth):
        parts.append(f"M{x} {y} H{x + s} V{y + s} H{x} Z")
    d_str = " ".join(parts)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">\n'
        f'  <path d="{d_str}" fill="black" fill-rule="evenodd"/>\n'
        '</svg>'
    )
    (FIXTURES / f"carpet.svg").write_text(svg, encoding="utf-8")


def _gasket_triangles(depth: int):
    """Vertex triples of the Sierpinski gasket edge recursion."""
    tris = []

    def rec(ax, ay, bx, by, cx, cy, d):
        if d == 0:
            tris.append(((ax, ay), (bx, by), (cx, cy)))
            return
        abx, aby = (ax + bx) / 2.0, (ay + by) / 2.0
        bcx, bcy = (bx + cx) / 2.0, (by + cy) / 2.0
        cax, cay = (cx + ax) / 2.0, (cy + ay) / 2.0
        rec(ax, ay, abx, aby, cax, cay, d - 1)
        rec(bx, by, bcx, bcy, abx, aby, d - 1)
        rec(cx, cy, cax, cay, bcx, bcy, d - 1)

    size = 2 ** (depth + 1)  # base 256 at depth 7
    rec(0, 0, size, size, size, 0, depth)
    return tris


def write_gasket(depth: int = 7) -> None:
    tris = _gasket_triangles(depth)
    edges = list({tuple(sorted((p1, p2))) for (A, B, C) in tris for p1, p2 in ((A, B), (B, C), (C, A))})
    size = 2 ** (depth + 1)
    parts = []
    for (x1, y1), (x2, y2) in edges:
        fmt = lambda v: str(int(v)) if float(v).is_integer() else f"{v:.3f}".rstrip("0").rstrip(".")
        parts.append(f"M{fmt(x1)} {fmt(y1)} L{fmt(x2)} {fmt(y2)}")
    d_str = " ".join(parts)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">\n'
        f'  <path d="{d_str}" fill="none" stroke="black" stroke-width="1"/>\n'
        '</svg>'
    )
    (FIXTURES / "gasket.svg").write_text(svg, encoding="utf-8")
    return len(edges)


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    write_square_full()
    write_horizontal_line()
    write_carpest = write_carpet(depth=5)
    n_edges = write_gasket(depth=7)
    for p in sorted(FIXTURES.glob("*.svg")):
        print(f"{p.name:<24} {p.stat().st_size:>9,} bytes")
    print(f"gasket edge count: {n_edges}")


if __name__ == "__main__":
    main()
