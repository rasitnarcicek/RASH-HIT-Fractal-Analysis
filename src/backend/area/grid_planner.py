# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek

"""
grid_planner.py — Aspect-Ratio Aware & Dynamic Square Grid Generator.
Calculates the exact analysis bounding box, aspect ratio AR = W/H,
and generates optimal multi-level grid series where cells are 100% square.
"""

from __future__ import annotations
import math
from fractions import Fraction
from typing import List, Tuple, Dict, Any, Optional


class GridLevel:
    """Represents a single grid resolution level in box-counting analysis."""
    def __init__(self, level_idx: int, cols: int, rows: int, analysis_w: float, analysis_h: float):
        self.level_idx = level_idx
        self.cols = cols
        self.rows = rows
        self.total_cells = cols * rows
        self.cell_w = analysis_w / cols
        self.cell_h = analysis_h / rows
        self.cell_aspect_ratio = self.cell_w / self.cell_h if self.cell_h > 0 else 1.0

        # Scale parameter epsilon = max(cell_w, cell_h) / max(analysis_w, analysis_h)
        max_dim = max(analysis_w, analysis_h)
        self.scale_epsilon = max(self.cell_w, self.cell_h) / max_dim if max_dim > 0 else 1.0
        self.log_inv_epsilon = math.log(1.0 / self.scale_epsilon) if self.scale_epsilon > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'level': self.level_idx,
            'cols': self.cols,
            'rows': self.rows,
            'total_cells': self.total_cells,
            'cell_w': round(self.cell_w, 4),
            'cell_h': round(self.cell_h, 4),
            'cell_aspect_ratio': round(self.cell_aspect_ratio, 4),
            'scale_epsilon': round(self.scale_epsilon, 6),
            'log_inv_epsilon': round(self.log_inv_epsilon, 6),
        }


class GridPlan:
    """Holds analysis bounding box and the list of generated grid levels."""
    def __init__(self, bounds: Tuple[float, float, float, float], levels: List[GridLevel], grid_mode: str = "canvas_aspect"):
        self.xmin, self.ymin, self.xmax, self.ymax = bounds
        self.width = max(1e-6, self.xmax - self.xmin)
        self.height = max(1e-6, self.ymax - self.ymin)
        self.aspect_ratio = self.width / self.height
        self.levels = levels
        self.grid_mode = grid_mode


def create_grid_plan(
    svg_viewbox: Optional[Tuple[float, float, float, float]],
    svg_width: float,
    svg_height: float,
    geometry_bounds: Optional[Tuple[float, float, float, float]] = None,
    num_levels: int = 7,
    base_cells: Optional[int] = 4,
    manual_grids: Optional[List[Tuple[int, int]]] = None,
    grid_mode: str = "canvas_aspect"
) -> GridPlan:
    """
    Determines analysis bounding box and generates optimal grid levels.
    
    Modes:
      - 'canvas_aspect' (Default): Dynamically calculates (cols_1, rows_1) from the SVG canvas width & height
        ratio (W:H) so that EVERY SINGLE CELL IS A 100% PERFECT SQUARE on the canvas.
      - 'square_bbox': Encloses the design geometry in a square bounding box S x S.
    """
    # 1. Determine Base Raw Bounds
    if geometry_bounds and (geometry_bounds[2] > geometry_bounds[0]) and (geometry_bounds[3] > geometry_bounds[1]) and grid_mode == "square_bbox":
        raw_bounds = geometry_bounds
    elif svg_viewbox and svg_viewbox[2] > 0 and svg_viewbox[3] > 0:
        raw_bounds = (svg_viewbox[0], svg_viewbox[1], svg_viewbox[0] + svg_viewbox[2], svg_viewbox[1] + svg_viewbox[3])
    elif svg_width > 0 and svg_height > 0:
        raw_bounds = (0.0, 0.0, svg_width, svg_height)
    elif geometry_bounds and (geometry_bounds[2] > geometry_bounds[0]) and (geometry_bounds[3] > geometry_bounds[1]):
        raw_bounds = geometry_bounds
    else:
        raw_bounds = (0.0, 0.0, 100.0, 100.0)

    raw_w = raw_bounds[2] - raw_bounds[0]
    raw_h = raw_bounds[3] - raw_bounds[1]

    # 2. Apply Square Bounding Box Transformation if requested
    if grid_mode in ("square_bbox", "square_canvas"):
        max_s = max(raw_w, raw_h)
        cx = (raw_bounds[0] + raw_bounds[2]) / 2.0
        cy = (raw_bounds[1] + raw_bounds[3]) / 2.0
        bounds = (cx - max_s / 2.0, cy - max_s / 2.0, cx + max_s / 2.0, cy + max_s / 2.0)
        analysis_w = max_s
        analysis_h = max_s
        is_square = True
    else:
        bounds = raw_bounds
        analysis_w = raw_w
        analysis_h = raw_h
        is_square = False

    ar = analysis_w / analysis_h
    levels: List[GridLevel] = []

    if manual_grids:
        for idx, (c, r) in enumerate(manual_grids, start=1):
            levels.append(GridLevel(idx, max(1, c), max(1, r), analysis_w, analysis_h))
    elif is_square:
        # Equal N x N Square Grid Planner
        bc = base_cells if (base_cells is not None and base_cells > 0) else 4
        for i in range(num_levels):
            n_side = bc * (2 ** i)
            levels.append(GridLevel(i + 1, n_side, n_side, analysis_w, analysis_h))
    else:
        # Dynamic Aspect-Ratio Square Grid Planner (No hardcoded fixed 4)
        if base_cells is not None and base_cells > 0:
            if ar >= 1.0:
                base_rows = base_cells
                base_cols = max(1, int(round(base_rows * ar)))
            else:
                base_cols = base_cells
                base_rows = max(1, int(round(base_cols / ar)))
        else:
            # Dynamic reduced fraction ratio from W:H
            frac = Fraction(ar).limit_denominator(50)
            base_cols = frac.numerator
            base_rows = frac.denominator

        for i in range(num_levels):
            multiplier = 2 ** i
            cols = base_cols * multiplier
            rows = base_rows * multiplier
            levels.append(GridLevel(i + 1, cols, rows, analysis_w, analysis_h))

    return GridPlan(bounds, levels, grid_mode=grid_mode)


def generate_doubling_grid_spec(vw: float, vh: float, levels: int = 7, grid_mode: str = "canvas_aspect") -> List[Tuple[int, int]]:
    """Helper returning a list of (cols, rows) grid tuples for specified viewBox dimensions and level count."""
    plan = create_grid_plan(svg_viewbox=(0.0, 0.0, vw, vh), svg_width=vw, svg_height=vh, num_levels=levels, grid_mode=grid_mode)
    return [(lvl.cols, lvl.rows) for lvl in plan.levels]
