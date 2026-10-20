# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek

"""
intersection_cpu.py — CPU Exact Vector Geometry Box-Counting Engine.
Uses Shapely 2.0 C++ vectorized STRtree spatial indexing to bulk-query grid cell boxes
against exact polygon fills and buffered stroke lines.
"""

from __future__ import annotations
from typing import List, Tuple, Dict, Any

from .grid_planner import GridLevel


class CellDebugInfo:
    """Stores detailed debug information for a filled grid cell."""
    def __init__(
        self,
        level_idx: int,
        col: int,
        row: int,
        reason: str,
        geometry_id: int,
        geometry_type: str,
        fill_or_stroke: str,
        stroke_width: float,
        cell_bounds: Tuple[float, float, float, float]
    ):
        self.level_idx = level_idx
        self.col = col
        self.row = row
        self.reason = reason
        self.geometry_id = geometry_id
        self.geometry_type = geometry_type
        self.fill_or_stroke = fill_or_stroke
        self.stroke_width = stroke_width
        self.cell_bounds = cell_bounds

    def to_dict(self) -> Dict[str, Any]:
        return {
            'level': int(self.level_idx),
            'col': int(self.col),
            'row': int(self.row),
            'reason': str(self.reason),
            'geometry_id': int(self.geometry_id),
            'geometry_type': str(self.geometry_type),
            'fill_or_stroke': str(self.fill_or_stroke),
            'stroke_width': float(round(self.stroke_width, 4)),
            'cell_bounds': [float(round(b, 4)) for b in self.cell_bounds]
        }


class CPULevelResult:
    """Stores box-counting result for a single grid level."""
    def __init__(
        self,
        level: GridLevel,
        filled_count: int,
        empty_count: int,
        execution_time_ms: float,
        filled_cells_indices: List[Tuple[int, int]] = None,
        debug_cells: List[CellDebugInfo] = None,
        row_runs: List[Tuple[int, int, int]] = None
    ):
        self.level = level
        self.filled_count = filled_count
        self.empty_count = empty_count
        self.total_cells = level.total_cells
        self.fill_ratio = (filled_count / level.total_cells) if level.total_cells > 0 else 0.0
        self.execution_time_ms = execution_time_ms
        self.filled_cells_indices = filled_cells_indices or []
        self.debug_cells = debug_cells or []
        # RASH-HIT Fractal Analiz Engine: compact per-row filled runs ``(row, col_start, col_end_exclusive)``
        # used for run-length/row-run merged SVG maps when raw indices are disabled.
        self.row_runs = row_runs or []

    def to_dict(self) -> Dict[str, Any]:
        d = self.level.to_dict()
        d.update({
            'filled_cells': self.filled_count,
            'empty_cells': self.empty_count,
            'fill_ratio': round(self.fill_ratio, 4),
            'execution_time_ms': round(self.execution_time_ms, 2),
            'mode': 'CPU'
        })
        return d


