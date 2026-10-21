# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""Independent exact oracles for the scientific validation fixtures.

Every oracle here is *deliberately implemented with different mathematics*:
  * carpet oracle: pure integer interval containment (no floating point,
    no Shapely, no Scapely-cache tricks).  Rule: a cell touches the
    carpet iff its rectangle is not fully contained in a (white) hole.
  * gasket oracle: brute-force per-segment closed-box intersection with
    independent shapely/GESO predicates (different code stack from the
    int64 fixed-point supercover engine).
If engine counts equal the oracle counts level-by-level, the engines are
not just self-consistent: they are right.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Sierpinski carpet (area semantics) - exact integer oracle
# ---------------------------------------------------------------------------

def carpet_holes(depth: int, size: int) -> List[Tuple[int, int, int]]:
    """Same recursion as the fixture generator (axis-aligned white holes)."""
    holes: List[Tuple[int, int, int]] = []

    def rec(x: int, y: int, side: int, d: int) -> None:
        if d == 0:
            return
        t = side // 3
        for row in range(3):
            for col in range(3):
                if row == 1 and col == 1:
                    holes.append((x + t, y + t, t))
                else:
                    rec(x + col * t, y + row * t, t, d - 1)

    rec(0, 0, size, depth)
    return holes


def carpet_expected_counts(depth: int = 5, levels: int = 7) -> List[int]:
    """Exact 'cell touches carpet' counts on the engine's canvas-aspect
    doubling grids for a square canvas.

    Grid plan (canvas_aspect, square canvas): L -> (4*2^(L-1), 4*2^(L-1)).
    A cell [c0, c1] x [r0, r1] is EMPTY iff it lies fully inside one white
    hole (holes are disjoint axis-aligned squares).  Therefore
    occupied(L) = 4^L - sum(per-hole fully-contained cell count).
    Integer arithmetic only: cell bounds are exact dyadic fractions of the
    canvas, so containment is a floor/ceil problem on scaled integers.
    """
    size = 3 ** depth
    holes = carpet_holes(depth, size)
    out: List[int] = []
    for lv in range(1, levels + 1):
        n = 4 * 2 ** (lv - 1)
        total = n * n
        full_white = 0
        for hx, hy, hs in holes:
            # cells (integer-indexed) fully inside the interval
            # x in [hx, hx+hs] scaled to the ny col grid:
            # min col c with c >= nx*hx/size, max col c with (c+1)*size <= nx*(hx+hs)
            c0 = -(-n * hx // size)  # ceil
            x_end_full = n * (hx + hs) // size  # floor
            cc0 = -(-n * hy // size)
            rr_end = n * (hy + hs) // size
            wx = max(0, x_end_full - c0)
            wy = max(0, rr_end - cc0)
            full_white += wx * wy
        out.append(total - full_white)
    return out


# ---------------------------------------------------------------------------
# Sierpinski gasket (supercover semantics) - independent GEOS oracle
# ---------------------------------------------------------------------------

def gasket_expected_counts(levels: int = 7, canvas: int = 256) -> List[int]:
    """Per-segment closed-box intersection counting with Shapely/GEOS.

    The supercover engine (fixed-point int64, Liang-Barsky) and this oracle
    share no code, no lattice arithmetic and no traversal kernels, yet must
    produce identical cell sets for the same touch_counts semantics.
    """
    import numpy as np
    import shapely
    from shapely.strtree import STRtree

    fixture = _fixture_dir() / "gasket.svg"
    segs = _parse_line_pairs(fixture.read_text(encoding="utf-8"))
    lines = [shapely.LineString([(x1, y1), (x2, y2)]) for (x1, y1, x2, y2) in segs]

    counts: List[int] = []
    for lv in range(1, levels + 1):
        cols = rows = 4 * 2 ** (lv - 1)
        cell_w = cell_h = canvas / cols
        xs0 = np.arange(cols) * cell_w
        ys0 = np.arange(rows) * cell_h
        x1 = xs0 + cell_w
        y1 = ys0 + cell_h
        boxes = shapely.box(
            np.repeat(xs0, rows), np.tile(ys0, cols),
            np.repeat(x1, rows), np.tile(y1, cols),
        )
        tree = STRtree(boxes)
        occupied = set()
        for line in lines:
            hits = tree.query(line)
            if len(hits) == 0:
                continue
            cand = boxes[hits]
            found = shapely.intersects(cand, line)
            for k in hits[found]:
                occupied.add(int(k))
        counts.append(len(occupied))
    return counts


def _fixture_dir():
    from pathlib import Path
    return Path(__file__).resolve().parent / "fixtures"


def _parse_line_pairs(d_str: str) -> List[Tuple[float, float, float, float]]:
    import re
    pat = re.compile(r"M([\d.]+) ([\d.]+) L([\d.]+) ([\d.]+)")
    return [tuple(float(g) for g in m.groups()) for m in pat.finditer(d_str)]
