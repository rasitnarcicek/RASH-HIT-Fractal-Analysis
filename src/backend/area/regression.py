# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""
regression.py - Log-log linear regression engine and pure SVG plot generator.
Calculates slope (Db), R-squared, scale table entries, and renders loglog_plot.svg.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ScaleTableEntry:
    level: int
    grid_label: str
    box_size_w: float
    box_size_h: float
    inv_box_size: float
    occupied_count: int
    total_count: int
    log_inv_r: float
    log_nr: float
    included_in_fit: bool = True
    exclusion_reason: str = ""
    gpu_cells: Optional[int] = None
    cpu_cells: Optional[int] = None
    verified_equal: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "level": self.level,
            "grid_label": self.grid_label,
            "box_size_w": round(self.box_size_w, 4),
            "box_size_h": round(self.box_size_h, 4),
            "inv_box_size": round(self.inv_box_size, 4),
            "occupied_count": self.occupied_count,
            "total_count": self.total_count,
            "log_inv_r": round(self.log_inv_r, 4),
            "log_nr": round(self.log_nr, 4),
            "included_in_fit": self.included_in_fit,
            "exclusion_reason": self.exclusion_reason,
        }
        if self.gpu_cells is not None:
            d["gpu_cells"] = self.gpu_cells
        if self.cpu_cells is not None:
            d["cpu_cells"] = self.cpu_cells
        if self.verified_equal is not None:
            d["verified_equal"] = self.verified_equal
        return d


@dataclass
class RegressionResult:
    db: float
    r2: float
    intercept: float
    scale_table: List[ScaleTableEntry] = field(default_factory=list)
    valid_scales_count: int = 0
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "db": round(self.db, 4),
            "r2": round(self.r2, 4),
            "intercept": round(self.intercept, 4),
            "valid_scales_count": self.valid_scales_count,
            "scale_table": [s.to_dict() for s in self.scale_table],
            "warnings": self.warnings,
        }


def select_best_scaling_window(scale_entries: List[ScaleTableEntry]) -> List[int]:
    """
    Blind contiguous window scan (min size 4 points).
    Ranks by highest R², then max length, then earliest start.
    Returns indices (levels) of the best window.
    """
    candidates = []

    # We need at least 4 points for a meaningful regression
    n = len(scale_entries)
    if n < 4:
        return [s.level for s in scale_entries] # Fallback if not enough data

    for start in range(n - 3):
        for end in range(start + 4, n + 1):
            window = scale_entries[start:end]
            x_vals = [s.log_inv_r for s in window]
            y_vals = [s.log_nr for s in window]

            # Regression for this window
            n_w = len(window)
            sum_x = sum(x_vals)
            sum_y = sum(y_vals)
            sum_xx = sum(x * x for x in x_vals)
            sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))

            denom = (n_w * sum_xx) - (sum_x * sum_x)
            if abs(denom) < 1e-12:
                continue
            slope = ((n_w * sum_xy) - (sum_x * sum_y)) / denom
            intercept = (sum_y - (slope * sum_x)) / n_w
            mean_y = sum_y / n_w
            ss_tot = sum((y - mean_y) ** 2 for y in y_vals)
            ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_vals, y_vals))
            r2 = max(0.0, min(1.0, 1.0 - (ss_res / ss_tot))) if ss_tot > 1e-12 else 1.0

            # Filter
            if 1.0 <= abs(slope) <= 2.0 and r2 >= 0.99:
                candidates.append({
                    'r2': r2,
                    'length': n_w,
                    'start': start,
                    'levels': [s.level for s in window]
                })

    if not candidates:
        return [s.level for s in scale_entries] # Fallback

    # Rank: highest R², then max length, then earliest start
    candidates.sort(key=lambda c: (c['r2'], c['length'], -c['start']), reverse=True)

    return candidates[0]['levels']

def compute_loglog_regression(levels_data: List[Dict[str, Any]]) -> RegressionResult:
    """Computes box-counting fractal dimension (Db) and R2 fit from per-level metrics."""
    scale_entries: List[ScaleTableEntry] = []

    # 1. Parse entries
    for lvl in levels_data:
        raw_lvl = lvl.get("level", 1)
        l_idx = raw_lvl.level_idx if hasattr(raw_lvl, "level_idx") else int(raw_lvl)
        g_lbl = str(lvl.get("grid_label", f"L{l_idx}"))
        cell_w = float(lvl.get("cell_w", 1.0))
        cell_h = float(lvl.get("cell_h", 1.0))
        filled = int(lvl.get("filled_cells", 0))
        total = int(lvl.get("total_cells", 1))

        avg_size = (cell_w + cell_h) / 2.0
        inv_r = 1.0 / avg_size if avg_size > 0 else 1.0

        log_inv_r = math.log10(inv_r) if inv_r > 0 else 0.0
        log_nr = math.log10(filled) if filled > 0 else 0.0

        entry = ScaleTableEntry(
            level=l_idx,
            grid_label=g_lbl,
            box_size_w=cell_w,
            box_size_h=cell_h,
            inv_box_size=inv_r,
            occupied_count=filled,
            total_count=total,
            log_inv_r=log_inv_r,
            log_nr=log_nr,
            included_in_fit=True, # Will be set by window selection
            exclusion_reason="",
            gpu_cells=lvl.get("gpu_cells"),
            cpu_cells=lvl.get("cpu_cells"),
            verified_equal=lvl.get("verified_equal"),
        )
        scale_entries.append(entry)

    # 2. Apply sliding window
    best_levels = select_best_scaling_window(scale_entries)

    x_vals: List[float] = []
    y_vals: List[float] = []
    for entry in scale_entries:
        if entry.occupied_count <= 0:
            # log10(0) sözde-noktası (0.0) regresyonu bozar: hiç dolu hücresi
            # olmayan seviye fit'e giremez (tablo gösteriminde kalır).
            entry.included_in_fit = False
            entry.exclusion_reason = "no_occupied_boxes"
        elif entry.level not in best_levels:
            entry.included_in_fit = False
            entry.exclusion_reason = "outside_selected_sliding_window"
        else:
            x_vals.append(entry.log_inv_r)
            y_vals.append(entry.log_nr)

    # 3. Compute regression
    n = len(x_vals)
    if n == 0:
        # Boş geometri: hiçbir seviyede dolu kutu yok (ör. W3C butt-cap sıfır uzunluk
        # subpath mürekkep üretmez). Boş kümenin ölçüsü 0'dır: Db = 0.0, R² = 1.0.
        return RegressionResult(
            db=0.0,
            r2=1.0,
            intercept=0.0,
            scale_table=scale_entries,
            valid_scales_count=0,
            warnings=["No occupied boxes at any level (empty geometry); Db reported as 0.0."],
        )
    if n < 2:
        return RegressionResult(
            db=1.0,
            r2=0.0,
            intercept=0.0,
            scale_table=scale_entries,
            valid_scales_count=n,
            warnings=["Insufficient valid scales (<2) for log-log regression."],
        )

    sum_x = sum(x_vals)
    sum_y = sum(y_vals)
    sum_xx = sum(x * x for x in x_vals)
    sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))

    denom = (n * sum_xx) - (sum_x * sum_x)
    if abs(denom) < 1e-12:
        slope = 1.0
        intercept = 0.0
    else:
        slope = ((n * sum_xy) - (sum_x * sum_y)) / denom
        intercept = (sum_y - (slope * sum_x)) / n

    mean_y = sum_y / n
    ss_tot = sum((y - mean_y) ** 2 for y in y_vals)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(x_vals, y_vals))

    r2 = max(0.0, min(1.0, 1.0 - (ss_res / ss_tot))) if ss_tot > 1e-12 else 1.0

    return RegressionResult(
        db=abs(slope),
        r2=r2,
        intercept=intercept,
        scale_table=scale_entries,
        valid_scales_count=n,
    )


def generate_loglog_plot_svg(reg: RegressionResult, out_path: Path) -> Path:
    """Generates a clean publication-ready pure vector SVG log-log regression plot."""
    vw, vh = 600, 420
    margin_l, margin_r, margin_t, margin_b = 65, 40, 50, 55
    pw, ph = vw - margin_l - margin_r, vh - margin_t - margin_b

    all_entries = reg.scale_table or []

    if not all_entries:
        min_x, max_x = 0.0, 1.0
        min_y, max_y = 0.0, 1.0
    else:
        min_x = min(s.log_inv_r for s in all_entries)
        max_x = max(s.log_inv_r for s in all_entries)
        min_y = min(s.log_nr for s in all_entries)
        max_y = max(s.log_nr for s in all_entries)

    dx = (max_x - min_x) or 1.0
    dy = (max_y - min_y) or 1.0

    min_x -= dx * 0.08
    max_x += dx * 0.08
    min_y -= dy * 0.08
    max_y += dy * 0.08

    def map_x(val: float) -> float:
        return margin_l + ((val - min_x) / (max_x - min_x)) * pw

    def map_y(val: float) -> float:
        return margin_t + ph - (((val - min_y) / (max_y - min_y)) * ph)

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {vw} {vh}" width="100%" height="100%">',
        '  <rect width="100%" height="100%" fill="#FFFFFF"/>',
        '  <!-- Background Panel -->',
        f'  <rect x="{margin_l}" y="{margin_t}" width="{pw}" height="{ph}" fill="#F8FAFC" stroke="#D8DEE9" stroke-width="1"/>',
        '  <!-- Grid Lines -->',
    ]

    # Horizontal gridlines
    for i in range(5):
        y_val = min_y + (i / 4.0) * (max_y - min_y)
        y_pos = map_y(y_val)
        svg_lines.append(f'  <line x1="{margin_l}" y1="{y_pos:.2f}" x2="{margin_l + pw}" y2="{y_pos:.2f}" stroke="#E2E8F0" stroke-width="1" stroke-dasharray="4,4"/>')
        svg_lines.append(f'  <text x="{margin_l - 8}" y="{y_pos + 4:.2f}" font-family="Consolas, monospace" font-size="11" fill="#64748B" text-anchor="end">{y_val:.2f}</text>')

    # Vertical gridlines
    for i in range(5):
        x_val = min_x + (i / 4.0) * (max_x - min_x)
        x_pos = map_x(x_val)
        svg_lines.append(f'  <line x1="{x_pos:.2f}" y1="{margin_t}" x2="{x_pos:.2f}" y2="{margin_t + ph}" stroke="#E2E8F0" stroke-width="1" stroke-dasharray="4,4"/>')
        svg_lines.append(f'  <text x="{x_pos:.2f}" y="{margin_t + ph + 18}" font-family="Consolas, monospace" font-size="11" fill="#64748B" text-anchor="middle">{x_val:.2f}</text>')

    # Regression Line
    x1_fit = min_x
    y1_fit = reg.db * x1_fit + reg.intercept
    x2_fit = max_x
    y2_fit = reg.db * x2_fit + reg.intercept

    svg_lines.append(f'  <line x1="{map_x(x1_fit):.2f}" y1="{map_y(y1_fit):.2f}" x2="{map_x(x2_fit):.2f}" y2="{map_y(y2_fit):.2f}" stroke="#2454A6" stroke-width="2.5"/>')

    # Data Points
    for entry in reg.scale_table:
        cx = map_x(entry.log_inv_r)
        cy = map_y(entry.log_nr)
        col = "#166534" if entry.included_in_fit else "#DC2626"
        svg_lines.append(f'  <circle cx="{cx:.2f}" cy="{cy:.2f}" r="5" fill="{col}" stroke="#FFFFFF" stroke-width="1.5"/>')
        svg_lines.append(f'  <text x="{cx + 8:.2f}" y="{cy - 6:.2f}" font-family="Inter, sans-serif" font-size="10" font-weight="bold" fill="#1E293B">{entry.grid_label}</text>')

    # Title & Legend
    svg_lines.append(f'  <text x="{margin_l}" y="{margin_t - 22}" font-family="Inter, sans-serif" font-size="15" font-weight="bold" fill="#0F172A">Log-Log Box-Counting Regression Plot</text>')
    svg_lines.append(f'  <text x="{margin_l}" y="{margin_t - 7}" font-family="Consolas, monospace" font-size="12" fill="#2454A6" font-weight="bold">Slope (Db) = {reg.db:.4f}  |  R² = {reg.r2:.4f}</text>')

    # Axis Labels
    svg_lines.append(f'  <text x="{margin_l + pw / 2:.2f}" y="{vh - 12}" font-family="Inter, sans-serif" font-size="12" font-weight="bold" fill="#334155" text-anchor="middle">log(1 / box size)</text>')
    svg_lines.append(f'  <text x="18" y="{margin_t + ph / 2:.2f}" font-family="Inter, sans-serif" font-size="12" font-weight="bold" fill="#334155" text-anchor="middle" transform="rotate(-90 18 {margin_t + ph / 2:.2f})">log(occupied count N(r))</text>')

    svg_lines.append('</svg>')

    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text("\n".join(svg_lines), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Backward-compatibility adapter — replaces the deleted fractal_analyzer.py
# ---------------------------------------------------------------------------
# Previously backend/fractal_analyzer.py exposed FractalAnalysisResult and
# compute_fractal_dimension.  Both are preserved here so that existing tests
# (test_audit_gaps.py, test_audit_gaps2.py) that import from this module
# continue to pass without modification.
# ---------------------------------------------------------------------------

import numpy as _np  # noqa: E402 — lazy import kept at end to avoid hoisting


class FractalAnalysisResult:
    """Backward-compat result class (formerly fractal_analyzer.FractalAnalysisResult)."""

    def __init__(
        self,
        fractal_dimension_db: float,
        r2_score: float,
        level_results: list,
        scaling_levels_used: list,
    ):
        self.fractal_dimension_db = fractal_dimension_db
        self.r2_score = r2_score
        self.level_results = level_results
        self.scaling_levels_used = scaling_levels_used

    def to_dict(self) -> dict:
        return {
            "fractal_dimension_db": round(self.fractal_dimension_db, 4),
            "r2_score": round(self.r2_score, 4),
            "scaling_levels_used": self.scaling_levels_used,
            "levels": [res.to_dict() for res in self.level_results],
        }


def compute_fractal_dimension(
    level_results: list,
    selected_levels: list = None,
) -> FractalAnalysisResult:
    """Backward-compat function (formerly fractal_analyzer.compute_fractal_dimension).

    Computes log-log linear regression slope Db = d(log N) / d(log 1/eps)
    and R² using NumPy least-squares.  Returns NaN R² when fill counts have
    zero variance (degenerate fit).
    """
    if not level_results:
        return FractalAnalysisResult(0.0, 0.0, [], [])

    if selected_levels:
        target = [r for r in level_results if r.level.level_idx in selected_levels]
    else:
        target = level_results

    x_vals: list = []
    y_vals: list = []
    used_indices: list = []

    for r in target:
        if r.filled_count > 0 and r.level.log_inv_epsilon >= 0:
            x_vals.append(r.level.log_inv_epsilon)
            y_vals.append(math.log(r.filled_count))
            used_indices.append(r.level.level_idx)

    if len(x_vals) < 2:
        return FractalAnalysisResult(0.0, 0.0, level_results, used_indices)

    x = _np.array(x_vals, dtype=_np.float64)
    y = _np.array(y_vals, dtype=_np.float64)

    A = _np.vstack([x, _np.ones(len(x))]).T
    m, c = _np.linalg.lstsq(A, y, rcond=None)[0]

    y_pred = m * x + c
    ss_res = _np.sum((y - y_pred) ** 2)
    ss_tot = _np.sum((y - _np.mean(y)) ** 2)
    if ss_tot > 0:
        r2 = float(1.0 - (ss_res / ss_tot))
    else:
        r2 = float("nan")

    return FractalAnalysisResult(float(m), r2, level_results, used_indices)
