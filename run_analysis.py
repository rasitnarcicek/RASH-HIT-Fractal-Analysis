# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek

"""
RASH-HIT Fractal Analysis
Version: 1.3.0

This module is the public library surface (analyze_svg_data,
print_analysis_report, write_analysis_file) — also a thin CLI wrapper
that delegates the TUI menu and direct-mode entry points to
``launcher.py``.  In every distribution channel, both
``rash-hit-fractal`` (console script) and ``python run_analysis.py``
end up at the same place.

Measure modes (v1.3.0):
  * ``area`` (default) — exact vector-geometry visual-fill box counting
    (filled areas + stroke-expanded polygons + polygon interiors over
    Shapely/GEOS).  Bit-for-bit identical to the RASH-HIT Fraktal
    Studio v2.0.0 engine (vendored subpackage ``src/backend/area``).
  * ``supercover`` — legacy pure NumPy geometric-contact engine
    (v1.2.2 behaviour, touch_counts boundary policy, no Shapely).
"""

import argparse
import sys
from pathlib import Path

# src/ layout: run_analysis.py ve launcher.py proje kökündedir; paket
# kodları src/ altındadır. Hem kök hem de src sys.path'e eklenir.
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
for _p in (str(_ROOT), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.backend.geometric_contact_pipeline import run_geometric_contact
from src.backend.ascii_exporter import (
    generate_ascii_file,
    generate_batch_ascii_book,
    build_output_filename,
    build_book_filename,
    now_stamp,
)
from src.backend import __version__ as VERSION, __engine_name__ as ENGINE_NAME

#: Supported measure modes (v1.3.0).  ``area`` is the default: exact
#: vector-geometry visual-fill counting identical to Fraktal Studio;
#: ``supercover`` keeps the v1.2.2 pure-NumPy contact semantics.
MEASURE_MODES = {
    "area": "Exact Vector Geometry Engine ( Shapely/GEOS Area )",
    "supercover": "Pure NumPy Supercover Engine ( Geometric-Contact CPU )",
}

# Windows'ta varsayılan konsol kodlaması (cp1254 vb.) ASCII logodaki blok
# karakterleri (█) yazamıyor: UnicodeEncodeError. stdout/stderr'i UTF-8'e
# sabitle; aksi halde logo ve raporlar Türkçe konsolda çöküyor.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError, OSError):
        pass


def analyze_svg_data(input_file: str, levels: int = 7,
                     measure_mode: str = "area") -> dict:
    """
    Executes box-counting analysis on an SVG file in pure memory.

    v1.3.0: two measure modes.
      * ``area`` (default): the vendored exact vector-geometry engine from
        RASH-HIT Fraktal Studio (fill + stroke-expanded polygons + polygon
        interiors over Shapely/GEOS, FIXED_ORIGIN doubling grids).  Bit-for-
        bit identical numbers with the Studio visual-fill pipeline.
      * ``supercover``: the v1.2.2 pure NumPy geometric-contact engine
        (touch_counts boundary policy, no Shapely), kept for backward
        compatibility.
    Returns structured results for zero-disk stdout reporting.
    """
    if levels < 1:
        return {"input_file": input_file, "error": f"Invalid --levels '{levels}'. Number of grid levels must be >= 1."}
    if measure_mode not in MEASURE_MODES:
        return {
            "input_file": input_file,
            "error": f"Invalid measure_mode '{measure_mode}'. Expected one of: {', '.join(MEASURE_MODES)}.",
        }

    from pathlib import Path
    input_path = Path(input_file)
    if not input_path.exists():
        return {"input_file": input_file, "error": f"Input file not found: {input_file}"}

    try:
        if measure_mode == "area":
            # Lazy import: keeps the supercover path usable without Shapely.
            from src.backend.area.area_pipeline import run_area
            manifest = run_area(input_path, max_level=levels)
        else:
            manifest = run_geometric_contact(input_path, max_level=levels)
    except Exception as e:
        return {"input_file": input_file, "error": f"Failed to run {measure_mode} analysis on '{input_file}': {e}"}

    level_rows = []
    for lv in range(1, levels + 1):
        p = manifest["per_level"][str(lv)]
        level_rows.append({
            "level_idx": lv,
            "grid": f"{p['cols']}x{p['rows']}",
            "total_cells": p["total_cells"],
            "filled_count": p["occupied_cells"],
            "empty_count": p["empty_cells"],
            "fill_ratio": p["occupancy_ratio"],
            "execution_time_ms": float(p.get("execution_time_ms", 0.0) or 0.0),
        })

    return {
        "input_file": input_file,
        "motif_name": input_path.stem,
        "measure_mode": manifest.get("measure_mode", measure_mode),
        "vw": manifest["viewBox"][2],
        "vh": manifest["viewBox"][3],
        "geoms_count": manifest["segment_count"],
        "calc_time_ms": manifest["total_compute_seconds"] * 1000.0,
        "levels": level_rows,
        "fractal_db": manifest["fractal_dimension"],
        "r2_score": manifest["r_squared"],
        "engine_name": manifest.get("engine_name", MEASURE_MODES[measure_mode]),
        "manifest": manifest,
        "error": None,
    }


def print_analysis_report(data: dict) -> None:
    """Compact on-screen summary table for a single analysis result."""
    if data.get("error"):
        print(f"[ERROR] {data['error']}", file=sys.stderr)
        return

    print("+------------------------------------------------------------------------------+")
    print("|               RASH-HIT FRACTAL ANALYSIS - ANALYSIS REPORT                 |")
    print("+------------------------------------------------------------------------------+")
    print(f"  Motif Loaded       : {data['motif_name']} ({data['vw']:.2f} x {data['vh']:.2f})")
    print(f"  Geometries         : {data['geoms_count']:,} vector elements")
    print("  Analysis Engine    : cpu")
    print(f"  Measure Mode       : {data.get('measure_mode', 'area')}")
    print(f"  Selected Engine    : {data.get('engine_name', ENGINE_NAME)}")
    print("+------------------------------------------------------------------------------+")
    print("| Level | Grid     | Total Cells | Filled Cells | Empty Cells | Occupancy % | Time ms  |")
    print("+-------+----------+-------------+--------------+-------------+-------------+----------+")

    for r in data["levels"]:
        print(
            f"|  L{r['level_idx']:02d}  | {r['grid']:<8} | {r['total_cells']:>11,} | "
            f"{r['filled_count']:>12,} | {r['empty_count']:>11,} | {r['fill_ratio']*100:>10.2f}% | "
            f"{r['execution_time_ms']:>8.2f} |"
        )

    print("+-------+----------+-------------+--------------+-------------+-------------+----------+")
    print(f"  [RESULT] Box-Counting Fractal Dimension Db = {data['fractal_db']:.4f}")
    print(f"  [RESULT] Linear Regression Fit R2           = {data['r2_score']:.4f}")
    print(f"  [RESULT] Total Execution Time               = {data['calc_time_ms']:.2f} ms")
    print("+------------------------------------------------------------------------------+")


def write_analysis_file(data: dict, out_path, stamp: str | None = None):
    """Write the per-motif ASCII report to ``out_path``."""
    if data.get("error"):
        return out_path
    from pathlib import Path
    manifest = data["manifest"]
    levels = len(data["levels"])
    return generate_ascii_file(
        manifest=manifest,
        motif_stem=data["motif_name"],
        levels=levels,
        out_path=Path(out_path),
        stamp=stamp or now_stamp(),
    )


def main() -> None:
    """Delegate to launcher.main() so all channels behave identically."""
    # Lazy import: launcher pulls in `rich` and the TUI flow; only when
    # `python run_analysis.py` is invoked do we need it.
    from launcher import main as launcher_main
    raise SystemExit(launcher_main())


if __name__ == "__main__":
    main()
