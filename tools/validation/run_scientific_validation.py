# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""Scientific validation runner for the RASH-HIT engines (v1.3.0+).

Proof chain (each step independently checkable):

  1. EXACT THEORY (machine-exact counts, not just Db):
     * square_full.svg  [area]      N(L) = 16*4^(L-1) exactly (grid policy starts
       at 4x4 and doubles)          -> Db = 2.000000 (machine exact)
     * horizontal_line.svg [super]  full-width interior line: N(L) doubles exactly
       (8, 16, ... 512)             -> Db = 1.000000 (machine exact)
     * carpet.svg (depth 5)         self-similar, s=1/3, 8 pieces
                                    -> area Db = log8/log3 = 1.892789...
     * gasket.svg (depth 7)         self-similar, s=1/2, 3 pieces
                                    -> supercover Db = log3/log2 = 1.584963...

  2. INDEPENDENT ENGINE ORACLE:
     exact_oracle.py counts the SAME cells with a different mathematical
     formulation of the same semantics:
       * carpet (area semantics): a cell counts iff it is NOT fully inside a
         white hole -- pure integer floor/ceil arithmetic, no geometry library.
       * gasket (supercover semantics): per-segment closed-box intersection via
         an independent Shapely/GEOS predicate stack (the engine uses its own
         int64 fixed-point Liang-Barsky lattice kernels).
     Engine counts must equal oracle counts level-by-level, bit for bit.

  3. INDEPENDENT RASTER CROSS-CHECK (Pillow rendered, pure NumPy counting):
     A completely separate rendering + counting pipeline must reproduce the
     engine's Db within loose tolerance.

  Note on regressions: the AREA pipeline ships with the blind best-window
  scan (select_best_scaling_window, min 4 points), while the legacy supercover
  pipeline deliberately keeps the historical full-range OLS to stay
  bit-compatible with earlier releases and with Fraktal Studio.  For theory
  comparison of supercover fixtures we therefore report BOTH the engine's
  full-range number and the same windowed estimator science recommends.

Usage:
  python tools/validation/run_scientific_validation.py            # validate + print
  python tools/validation/run_scientific_validation.py --export-md # also write REPORT.md
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.path.insert(0, str(ROOT / "tools" / "validation"))

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"

from run_analysis import analyze_svg_data  # noqa: E402
from src.backend.area.regression import (  # noqa: E402
    RegressionResult,
    compute_loglog_regression,
)
from exact_oracle import (  # noqa: E402
    carpet_expected_counts,
    carpet_holes,
    gasket_expected_counts,
)

DB_CARPET = math.log(8) / math.log(3)      # 1.8927891107579245
DB_GASKET = math.log(3) / math.log(2)      # 1.5849625007211563

LEVELS = 7
REPORT_LINES: list = []


def out(text: str = "") -> None:
    print(text)
    REPORT_LINES.append(text)


def run_engine(svg: Path, levels: int, mode: str) -> dict:
    r = analyze_svg_data(str(svg), levels=levels, measure_mode=mode)
    if r.get("error"):
        raise RuntimeError(r["error"])
    reg = compute_loglog_regression(
        [
            {
                "level": int(lv),
                "grid_label": f"{p['cols']}x{p['rows']}",
                "cell_w": r["manifest"]["viewBox"][2] / p["cols"],
                "cell_h": r["manifest"]["viewBox"][3] / p["rows"],
                "filled_cells": p["occupied_cells"],
                "total_cells": p["total_cells"],
            }
            for lv, p in r["manifest"]["per_level"].items()
        ]
    )
    return {
        "counts": [row["filled_count"] for row in r["levels"]],
        "totals": [row["total_cells"] for row in r["levels"]],
        "db": r["fractal_db"],
        "r2": r["r2_score"],
        "time_ms": r["calc_time_ms"],
        "windowed_db": reg.db,
        "windowed_r2": reg.r2,
        "window_levels": [s.level for s in reg.scale_table if s.included_in_fit],
    }


def exact_square_checks(res: dict, levels: int) -> dict:
    """Filled full-canvas square with the engine's doubling grid:
    L = 1 -> 4 x 4 grid, so N(L) = 16*4^(L-1) = 4^(L+1), Db = 2.0 exactly."""
    expected = [4 ** (lv + 1) for lv in range(1, levels + 1)]
    return {
        "expected_counts": expected,
        "counts_exact": res["counts"] == expected,
        "db_expected": 2.0,
        "db_abs_error": abs(res["db"] - 2.0),
        "r2": res["r2"],
    }


def exact_line_checks(res: dict, levels: int) -> dict:
    """Full-width interior horizontal line: N(L) doubles exactly, Db = 1.0."""
    counts = res["counts"]
    ratios_exact = all(counts[i + 1] == 2 * counts[i] for i in range(levels - 1))
    return {
        "expected_doubling": [counts[0] * (2 ** i) for i in range(levels)],
        "doubling_exact": ratios_exact,
        "db_expected": 1.0,
        "db_abs_error": abs(res["db"] - 1.0),
        "r2": res["r2"],
    }


def window_theory_checks(res: dict, db_theory: float, tolerance: float) -> dict:
    """Compare the windowed (min-4, R^2>=0.99) estimator against self-similar theory."""
    err = abs(res["windowed_db"] - db_theory)
    return {
        "window_levels": res["window_levels"],
        "windowed_db": res["windowed_db"],
        "windowed_r2": res["windowed_r2"],
        "db_theory": db_theory,
        "window_abs_error": err,
        "full_range_db": res["db"],
        "tolerance": tolerance,
        "pass": err < tolerance,
    }


# ---------------------------------------------------------------------------
# Independent raster cross-check (Pillow + pure NumPy bitmap box counting)
# ---------------------------------------------------------------------------

def bitmap_occupancy(img_arr, cols: int, rows: int) -> int:
    """Bitmap box counting: a cell is occupied iff ANY pixel in it is black."""
    import numpy as np

    h, w = img_arr.shape
    cell_w = w / cols
    cell_h = h / rows
    occupied = 0
    for r in range(rows):
        y0 = int(round(r * cell_h))
        y1 = h if r == rows - 1 else int(round((r + 1) * cell_h))
        for c in range(cols):
            x0 = int(round(c * cell_w))
            x1 = w if c == cols - 1 else int(round((c + 1) * cell_w))
            if img_arr[y0:y1, x0:x1].min() < 128:  # any dark pixel
                occupied += 1
    return occupied


def ols_loglog_db(counts: list, inv_r: list) -> tuple:
    xs = [math.log(v) for v in inv_r]
    ys = [math.log(n) for n in counts]
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    slope = (n * sxy - sx * sy) / denom
    mean_y = sy / n
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + (sy - slope * sx) / n)) ** 2 for x, y in zip(xs, ys))
    r2 = 1 - ss_res / ss_tot if ss_tot else 1.0
    return slope, r2


def raster_cross_check_carpet(levels: int, upscale: int = 8) -> dict:
    """Render the carpet with Pillow (independent renderer) and count bitmap cells."""
    import numpy as np

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return {"skipped": True, "reason": "pillow not installed (dev-only dependency)"}

    side = 243 * upscale  # exact: 3^5 lattice scaled
    base = side // 3 ** 5  # pixels per lattice unit = upscale
    img = Image.new("L", (side, side), 0)
    draw = ImageDraw.Draw(img)
    for x, y, s in carpet_holes(5, 3 ** 5):
        draw.rectangle([(x) * base, (y) * base, (x + s) * base - 1, (y + s) * base - 1], fill=255)
    arr = np.asarray(img)  # white=255 holes, black background = carpet

    counts = []
    for lv in range(1, levels + 1):
        cols = rows = 4 * 2 ** (lv - 1)
        counts.append(bitmap_occupancy(arr, cols, rows))
    inv_r = [2 ** lv / 256 for lv in range(1, levels + 1)]
    slope, r2 = ols_loglog_db(counts, inv_r)
    return {"db_bitmap": round(slope, 6), "r2_bitmap": round(r2, 6), "counts_bitmap": counts}


def main(export_md: bool = False) -> int:
    out("=" * 100)
    out("RASH-HIT SCIENTIFIC VALIDATION  (engine v1.3.0, levels=%d)" % LEVELS)
    out("=" * 100)

    # --- 1. square_full: machine-exact AREA counts --------------------------
    res = run_engine(FIXTURES / "square_full.svg", LEVELS, "area")
    chk = exact_square_checks(res, LEVELS)
    out()
    out("1) square_full.svg [area] -- N(L)=16*4^(L-1) EXACT -> Db=2.000000")
    out(f"   counts      : {res['counts']}")
    out(f"   expected    : {chk['expected_counts']}")
    out(f"   counts exact: {chk['counts_exact']}   Db: {res['db']} (err {chk['db_abs_error']:.2e})  R2: {res['r2']}")

    # --- 2. horizontal_line: machine-exact SUPERCOVER doubling --------------
    res2 = run_engine(FIXTURES / "horizontal_line.svg", LEVELS, "supercover")
    chk2 = exact_line_checks(res2, LEVELS)
    out()
    out("2) horizontal_line.svg [supercover] -- N(L) tam olarak 2x katlanir -> Db=1.000000")
    out(f"   counts        : {res2['counts']}")
    out(f"   doubling exact: {chk2['doubling_exact']}  Db: {res2['db']} (err {chk2['db_abs_error']:.2e})  R2: {res2['r2']}")

    # --- 3. carpet: theory + integer oracle ORACLE -------------------------
    res3 = run_engine(FIXTURES / "carpet.svg", LEVELS, "area")
    oracle3 = carpet_expected_counts(5, LEVELS)
    oracle3_exact = res3["counts"] == oracle3
    wchk3 = window_theory_checks(res3, DB_CARPET, 0.03)
    out()
    out("3) carpet.svg [area] -- TEORI: Db = log(8)/log(3) = %.7f" % DB_CARPET)
    out(f"   counts       : {res3['counts']}")
    out(f"   tam-sayi oracle: {oracle3}")
    out(f"   ENGINE == ORACLE (birebir): {oracle3_exact}")
    out(f"   Db (best window L{min(wchk3['window_levels'])}-L{max(wchk3['window_levels'])}): "
        f"{wchk3['windowed_db']:.6f} (R2 {wchk3['windowed_r2']:.6f}, err {wchk3['window_abs_error']:.4f})")
    out(f"   PASS tolerance (|err|<{wchk3['tolerance']}): {wchk3['pass']}")

    # --- 4. gasket: theory + GEOS oracle ------------------------------------
    res4 = run_engine(FIXTURES / "gasket.svg", LEVELS, "supercover")
    oracle4 = gasket_expected_counts(LEVELS)
    oracle4_exact = res4["counts"] == oracle4
    wchk4 = window_theory_checks(res4, DB_GASKET, 0.06)
    out()
    out("4) gasket.svg [supercover] -- TEORI: Db = log(3)/log(2) = %.7f" % DB_GASKET)
    out(f"   counts       : {res4['counts']}")
    out(f"   GEOS oracle  : {oracle4}")
    out(f"   ENGINE == ORACLE (birebir): {oracle4_exact}")
    out(f"   Db (best window L{min(wchk4['window_levels'])}-L{max(wchk4['window_levels'])}): "
        f"{wchk4['windowed_db']:.6f} (R2 {wchk4['windowed_r2']:.6f}, err {wchk4['window_abs_error']:.4f})")
    out(f"   (legacy full-range Db engine raporu: {res4['db']} -- backward-compat surumu)")
    out(f"   PASS tolerance (|err|<{wchk4['tolerance']}): {wchk4['pass']}")

    # --- 5. Pillow raster cross-check on carpet -----------------------------
    rx = raster_cross_check_carpet(LEVELS)
    out()
    out("5) carpet -- Pillow bagimsiz raster + saf NumPy bitmap sayim")
    if rx.get("skipped"):
        out("   " + json.dumps(rx))
        rx_ok = None
    else:
        diff = abs(res3["windowed_db"] - rx["db_bitmap"])
        out(f"   bitmap Db: {rx['db_bitmap']} (R2 {rx['r2_bitmap']})")
        out(f"   engine windowed Db: {res3['windowed_db']:.6f}  fark: {diff:.4f}")
        rx_ok = diff < 0.05

    passed = (
        chk["counts_exact"] and chk["db_abs_error"] < 1e-9
        and chk2["doubling_exact"] and chk2["db_abs_error"] < 1e-9
        and oracle3_exact and wchk3["pass"]
        and oracle4_exact and wchk4["pass"]
        and (rx_ok is None or rx_ok)
    )
    out()
    out("=" * 100)
    out(f"OVERALL SCIENTIFIC VALIDATION: {'PASS' if passed else 'REVIEW'}")

    if export_md:
        report = (HERE / "REPORT.md")
        header = (
            "# RASH-HIT v1.3.0 Bilimsel Dogrulama Protorolu\n\n"
            f"- Tarih: {__import__('datetime').date.today().isoformat()}\n"
            f"- Sonuc: **{'PASS' if passed else 'REVIEW'}**\n"
            "- Kavramsal zincir: kesik teori (exact counts) -> bagimsiz oracle birebir eslesme -> "
            "bagimsiz Pillow raster teyidi -> pencerelestirilmis Db teori yaklasimi.\n"
        )
        body = "\n```\n" + "\n".join(REPORT_LINES) + "\n```\n"
        report.write_text(header + body, encoding="utf-8")
        print(f"\nREPORT.md yazildi: {report}")

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main("--export-md" in sys.argv))
