# SPDX-License-Identifier: Apache-2.0
# Minimal vendored copy of LevelReportModel (exact dataclass as Studio exporter models).
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple


@dataclass
class LevelReportModel:
    level: int
    cols: int
    rows: int
    grid_label: str
    total_cells: int
    filled_cells: int
    empty_cells: int
    fill_ratio: float
    occupancy_percent: float
    cell_w: float
    cell_h: float
    execution_time_ms: float
    mode: str = "CPU_GEOS"
    export_full_cells: bool = True
    filled_set: Set[Tuple[int, int]] = field(default_factory=set)
    row_runs: List[Tuple[int, int, int]] = field(default_factory=list)
    gpu_cells: Optional[int] = None
    cpu_cells: Optional[int] = None
    verified_equal: Optional[bool] = None

