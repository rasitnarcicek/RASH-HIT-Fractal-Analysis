# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""Exact vector-geometry AREA box-counting pipeline (visual-fill measure).

Vendored 1:1 from the RASH-HIT Fraktal Studio v2.0.0 area engine so the CLI is
a low-version sibling of the main project and produces bit-for-bit identical
numbers:

  svg_health -> svg_loader -> geometry_engine -> grid_planner
  -> intersection_hierarchical (Shapely/GEOS exact fill + stroke-expanded
     polygons + polygon interiors, FIXED_ORIGIN doubling grids)
  -> compute_loglog_regression (identical fit code as Studio)

This is the DEFAULT measure mode of the CLI (v1.3.0+).  The legacy pure-NumPy
supercover engine (geometric-contact semantics) remains available via
``measure_mode="supercover"``.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, List

from .grid_policy import GridPolicyConfig
from .grid_planner import generate_doubling_grid_spec
from .intersection_hierarchical import compute_hierarchical_box_counting
from .regression import compute_loglog_regression
from .svg_health import inspect_svg_health
from .svg_loader import load_svg_geometries


def run_area(input_path: Path, max_level: int = 7) -> Dict:
    """Run the exact vector-geometry AREA box-counting on one SVG file.

    Mirrors the Studio processor CPU area path (steps 2-6) with the default
    FIXED_ORIGIN policy and canvas_aspect doubling grids.  Returns the same
    manifest schema as ``run_geometric_contact`` so downstream reporting is a
    drop-in replacement:  ``viewBox``,  ``per_level`` (cols / rows /
    total_cells / occupied_cells / empty_cells / occupancy_ratio),
    ``segment_count``, ``total_compute_seconds``, ``fractal_dimension``,
    ``r_squared`` plus engine metadata fields.
    """
    if max_level < 1:
        raise ValueError(
            f"Invalid max_level '{max_level}'. Number of grid levels must be >= 1."
        )

    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    t_total0 = time.perf_counter()

    # Step 2: SVG health inspection (viewBox, suitability, element counts).
    health_res = inspect_svg_health(input_path)
    health = health_res.to_dict()
    vb = health_res.viewbox or (0.0, 0.0, 0.0, 0.0)
    vb_origin = (float(vb[0]), float(vb[1]))

    # Step 3: exact vector geometry extraction (fill + stroke-expanded).
    geoms, vw, vh = load_svg_geometries(input_path)

    # Step 4: doubling grid plan (canvas_aspect default, as the Studio).
    grid_specs = generate_doubling_grid_spec(float(vw), float(vh), levels=max_level)

    # Step 5: hierarchical Shapely/GEOS box counting (area semantics).
    lvl_models, summary = compute_hierarchical_box_counting(
        geoms,
        float(vw),
        float(vh),
        grid_specs,
        measure_mode="area",
        progress_callback=None,
        profile=None,
        grid_policy_config=GridPolicyConfig(),
        viewbox_origin=vb_origin,
    )

    per_level: Dict[str, Dict] = {}
    for idx, lm in enumerate(lvl_models):
        cols, rows = grid_specs[idx] if idx < len(grid_specs) else (0, 0)
        total = int(lm.total_cells)
        occupied = int(lm.filled_cells)
        empty = int(lm.empty_cells)
        ratio = (occupied / total) if total else 0.0
        pct = ratio * 100.0
        per_level[str(int(lm.level))] = {
            "cols": int(cols) if cols else int(lm.cols),
            "rows": int(rows) if rows else int(lm.rows),
            "total_cells": total,
            "occupied_cells": occupied,
            "empty_cells": empty,
            "occupancy_ratio": round(ratio, 6),
            "occupancy_percent": round(pct, 2),
            "cell_w": float(lm.cell_w),
            "cell_h": float(lm.cell_h),
            "execution_time_ms": round(float(lm.execution_time_ms), 3),
            "mode": str(lm.mode),
        }

    levels_data_raw: List[Dict] = []
    for lv in range(1, max_level + 1):
        p = per_level[str(lv)]
        levels_data_raw.append({
            "level": lv,
            "grid_label": f"{p['cols']}x{p['rows']}",
            "rows": p["rows"],
            "columns": p["cols"],
            "cell_w": p["cell_w"],
            "cell_h": p["cell_h"],
            "filled_cells": p["occupied_cells"],
            "empty_cells": p["empty_cells"],
            "total_cells": p["total_cells"],
            "occupancy_percent": p["occupancy_percent"],
            "execution_time_ms": p["execution_time_ms"],
            "mode": p["mode"],
        })

    # Step 6: identical log-log regression code as the Studio.
    reg = compute_loglog_regression(levels_data_raw)

    manifest = {
        "measure_mode": "area",
        "engine": "shapely_exact_area",
        "engine_name": "RASH-HIT Exact Vector Geometry Engine ( AREA Mode Shapely GEOS )",
        "viewBox": [float(vb[0]), float(vb[1]), float(vb[2]), float(vb[3])],
        "grid_policy": GridPolicyConfig().to_dict(),
        "svg_health": {
            "suitability_score": getattr(health_res, "suitability_score", None),
            "total_shape_elements": getattr(health_res, "total_shape_elements", None),
        },
        "segment_count": len(geoms),
        "total_compute_seconds": round(time.perf_counter() - t_total0, 6),
        "per_level": per_level,
        "fractal_dimension": round(float(reg.db), 6),
        "r_squared": round(float(reg.r2), 6),
    }
    return manifest
