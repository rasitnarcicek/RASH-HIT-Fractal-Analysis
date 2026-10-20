# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek

# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
#
# intersection_hierarchical.py -- Hierarchical Quadtree Area Engine (Vectorized v2)
#
# Key optimizations vs v1 (per-cell Python loop):
#   1. shapely.box(x0_arr,y0_arr,x1_arr,y1_arr) builds all cells in one C++ call.
#   2. STRtree.query(cell_array) -> (2,K) ndarray [geom_idxs; cell_idxs] in bulk C++.
#   3. shapely.intersects() / shapely.distance() ufuncs -- no Python iteration.
#   4. Active parent set is a NumPy (M,2) int32 array; child expansion is pure NumPy.
#
# Pruning rule (safe EMPTY-only):
#   EMPTY parent  -> children skipped (safe: if parent misses geometry, children do too).
#   PARTIAL/NON-EMPTY -> subdivided into 4 children, each re-evaluated exactly.
#   FULL shortcut NOT used (caused overcounting vs CPU baseline for dense SVGs).
#
# Expected to match CPU GEOS exact baseline; equivalence must be verified by benchmark.

from __future__ import annotations
import time
from typing import Any, List, Optional, Tuple

import numpy as np
import os
from concurrent.futures import ThreadPoolExecutor
import shapely
from shapely.strtree import STRtree

from .intersection_cpu import CPULevelResult
from .grid_offset_optimizer import optimize_grid_offset
from .grid_policy import (
    GridPolicy,
    GridPolicyConfig,
    resolve_grid_policy,
)
from .grid_planner import GridPlan


class HierarchicalLevelResult:
    def __init__(self, level_result, empty_parents_skipped, full_parents_counted,
                 partial_parents_subdivided, exact_geos_tests, pruning_time_ms,
                 negative_space_cached_cells=0,
                 candidate_count=0, filled_candidate_count=0,
                 empty_candidate_count=0, active_parent_count=0,
                 previous_active_parent_count=0, active_growth_rate=0.0,
                 empty_descendants_skipped_estimate=0, return_cell_indices_enabled=False, known_empty_contrib=0, strict_2x_guard_passed=True,
                 storage_mode="summary_only", empty_parents_skipped_estimate=0):
        self.level_result               = level_result
        self.empty_parents_skipped      = empty_parents_skipped
        self.full_parents_counted       = full_parents_counted
        self.partial_parents_subdivided = partial_parents_subdivided
        self.exact_geos_tests           = exact_geos_tests
        self.pruning_time_ms            = pruning_time_ms
        # RASH-HIT Engine: number of child cells that were NEVER evaluated because their
        # parent block was empty (negative-space cache). For a doubling grid this
        # equals ``total_cells - exact_geos_tests`` at each level.
        self.negative_space_cached_cells = int(negative_space_cached_cells or 0)
        # RASH-HIT Engine expanded metrics (visible Negative-Space-Cache description).
        # candidate_count: total boxes actually tested at this level.
        # filled/empty_candidate_count: geoms-touched / empty at this level.
        # active_parent_count: parents carried forward to the next level.
        # previous_active_parent_count: the parent set of the *previous* level.
        # active_growth_rate: active_parent_count / previous_active_parent_count
        #   (1.0 == flat; <1 collapse of empty space; >1 expansion of filled space).
        # empty_descendants_skipped_estimate: empty_candidate_count * (4 ** remaining_levels)
        #   -> performance/audit metric (NOT a correctness input).
        # return_cell_indices_enabled: did the policy collect raw cell indices?
        # storage_mode: raw | rle | summary_only | svg_only
        self.candidate_count = int(candidate_count or 0)
        self.filled_candidate_count = int(filled_candidate_count or 0)
        self.empty_candidate_count = int(empty_candidate_count or 0)
        self.active_parent_count = int(active_parent_count or 0)
        self.previous_active_parent_count = int(previous_active_parent_count or 0)
        self.active_growth_rate = float(active_growth_rate or 0.0)
        self.empty_descendants_skipped_estimate = int(empty_descendants_skipped_estimate or 0)
        self.return_cell_indices_enabled = bool(return_cell_indices_enabled)
        self.known_empty_contrib = int(known_empty_contrib or 0)
        self.strict_2x_guard_passed = bool(strict_2x_guard_passed)
        self.storage_mode = storage_mode
        # Back-compat alias (some callers read this on detail objects).
        self.empty_parents_skipped_estimate = self.empty_descendants_skipped_estimate

    # Proxy attributes -- callers can treat this like a CPULevelResult
    @property
    def level(self):             return self.level_result.level
    @property
    def filled_count(self):      return self.level_result.filled_count
    @property
    def empty_count(self):       return self.level_result.empty_count
    @property
    def fill_ratio(self):        return self.level_result.fill_ratio
    @property
    def total_cells(self):       return self.level_result.total_cells
    @property
    def execution_time_ms(self): return self.level_result.execution_time_ms


def _bulk_fill_decision_single(x0, y0, x1, y1,
                        fill_tree, fill_objs,
                        stroke_tree, stroke_objs, stroke_widths,
                        fill_obj_arr=None, stroke_obj_arr=None):
    """
    Returns bool ndarray (N,): True = cell is filled.

    STRtree.query(geometry_array) in Shapely 2.1.2 returns shape (2, K):
        row 0 = indices into the QUERY geometry array  (cell side)
        row 1 = indices into the TREE geometries       (geom side)
    Confirmed empirically: r[0].max() <= n_cells, r[1].max() <= n_tree_geoms.

    ``fill_obj_arr`` / ``stroke_obj_arr`` (optional) are precomputed NumPy
    object arrays of the geometry objects; when omitted they are rebuilt from
    ``fill_objs`` / ``stroke_objs`` on each call.

    The fill pass uses **round-based early exit** (RASH-HIT Engine performance): the
    STRtree returns one (cell, geom) pair per bbox-overlapping geometry, so a
    cell covered by several overlapping geometries appears once per geometry.
    A cell is filled as soon as ANY pair intersects, so the duplicate pairs of
    an already-filled cell are never sent to GEOS.  This is exact (identical to
    testing every pair) and cuts the number of ``intersects()`` calls -- the
    dominant cost in high-level runs.  Verified bit-for-bit equivalent on
    sparse and    dense motifs; on a 9-level sparse run it cuts the exact predicate work
    by ~1.3x.
    """
    n      = len(x0)
    filled = np.zeros(n, dtype=bool)

    cell_boxes = shapely.box(x0, y0, x1, y1)  # single C++ call

    # --- Fill geometries -------------------------------------------------
    if fill_tree is not None and n > 0:
        if fill_obj_arr is None:
            fill_obj_arr = np.asarray(fill_objs, dtype=object)
        pairs = fill_tree.query(cell_boxes)    # (2, K) or (0,) if no hits
        if pairs.ndim == 2 and pairs.shape[1] > 0:
            cell_idxs = pairs[0]   # r[0] = cell indices
            geom_idxs = pairs[1]   # r[1] = geom indices
            # Group pairs by cell so each cell's duplicates are contiguous.
            order = np.lexsort((geom_idxs, cell_idxs))
            cs     = cell_idxs[order]
            gs     = geom_idxs[order]
            uniq_cells, counts = np.unique(cs, return_counts=True)
            offsets = np.zeros(len(uniq_cells) + 1, dtype=np.int64)
            np.cumsum(counts, out=offsets[1:])
            base = offsets[:-1]   # first sorted pair index of each unique cell

            # Round 0 tests each cell's first pair; filled cells are dropped;
            # round r tests the (r+1)-th pair of the remaining cells only.
            alive_cells  = uniq_cells
            alive_counts = counts
            alive_base   = base
            round_idx    = 0
            while len(alive_cells) > 0:
                has_round = alive_counts > round_idx
                if not has_round.any():
                    break
                pos  = alive_base[has_round] + round_idx
                hits = shapely.intersects(fill_obj_arr[gs[pos]], cell_boxes[cs[pos]])
                if hits.any():
                    filled[cs[pos[hits]]] = True
                still = ~filled[alive_cells]
                alive_cells  = alive_cells[still]
                alive_counts = alive_counts[still]
                alive_base   = alive_base[still]
                round_idx   += 1

    # --- Stroke geometries -----------------------------------------------
    if stroke_tree is not None and n > 0 and not filled.all():
        if stroke_obj_arr is None:
            stroke_obj_arr = np.asarray(stroke_objs, dtype=object)
        pairs = stroke_tree.query(cell_boxes)  # (2, K)
        if pairs.ndim == 2 and pairs.shape[1] > 0:
            cell_idxs = pairs[0]   # r[0] = cell indices
            geom_idxs = pairs[1]   # r[1] = geom indices
            unfilled  = ~filled[cell_idxs]
            if unfilled.any():
                gi     = geom_idxs[unfilled]
                ci     = cell_idxs[unfilled]
                g_arr  = stroke_obj_arr[gi]
                c_arr  = cell_boxes[ci]
                hw     = stroke_widths[gi] / 2.0
                zw     = hw <= 0.0
                if zw.any():
                    hits_z = shapely.intersects(g_arr[zw], c_arr[zw])
                    filled[ci[zw][hits_z]] = True
                if (~zw).any():
                    dists  = shapely.distance(g_arr[~zw], c_arr[~zw])
                    hits_d = dists <= hw[~zw]
                    filled[ci[~zw][hits_d]] = True

    return filled



def _get_default_max_workers() -> int:
    cpus = os.cpu_count() or 4
    return max(1, int(cpus * 0.85))


def _bulk_fill_decision(x0, y0, x1, y1,
                        fill_tree, fill_objs,
                        stroke_tree, stroke_objs, stroke_widths,
                        fill_obj_arr=None, stroke_obj_arr=None,
                        max_workers=None):
    """
    Parallel multi-threaded wrapper for _bulk_fill_decision_single.
    Utilises ~85-90% of available logical CPU threads via ThreadPoolExecutor.
    """
    n = len(x0)
    if n == 0:
        return np.zeros(0, dtype=bool)

    if max_workers is None:
        max_workers = _get_default_max_workers()

    if n < 4000 or max_workers <= 1:
        return _bulk_fill_decision_single(
            x0, y0, x1, y1,
            fill_tree, fill_objs,
            stroke_tree, stroke_objs, stroke_widths,
            fill_obj_arr=fill_obj_arr,
            stroke_obj_arr=stroke_obj_arr
        )

    chunk_size = max(2000, n // (max_workers * 2))
    chunks = [(s, min(s + chunk_size, n)) for s in range(0, n, chunk_size)]
    filled = np.zeros(n, dtype=bool)

    def _worker(c):
        s, e = c
        res = _bulk_fill_decision_single(
            x0[s:e], y0[s:e], x1[s:e], y1[s:e],
            fill_tree, fill_objs,
            stroke_tree, stroke_objs, stroke_widths,
            fill_obj_arr=fill_obj_arr,
            stroke_obj_arr=stroke_obj_arr
        )
        return s, e, res

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        results = list(ex.map(_worker, chunks))
        for s, e, res in results:
            filled[s:e] = res

    return filled


def _resolve_level_flag(flag, level_idx, total_cells):
    """Resolve a per-level collection flag that is either a bool or a callable
    ``(level_idx, total_cells) -> bool`` (used to tie collection to the RASH-HIT Engine
    output policy on a per-level basis)."""
    if callable(flag):
        return bool(flag(level_idx, total_cells))
    return bool(flag)


def _build_row_runs(filled_rows, filled_cols):
    """Compress filled (row, col) candidates into per-row horizontal runs.

    Returns a list of ``(row, col_start, col_end_exclusive)`` tuples. Fully
    vectorised except for the final O(num_runs) list comprehension, so it stays
    cheap even at L10/L11 where millions of filled cells collapse into far fewer
    runs. This is the compact representation that powers run-length / row-run
    merged SVG maps when raw filled-cell indices are disabled (RASH-HIT Engine).
    """
    if filled_rows is None or filled_rows.size == 0:
        return []
    order = np.lexsort((filled_cols, filled_rows))
    fr = filled_rows[order]
    fc = filled_cols[order]

    row_change = np.empty_like(fr, dtype=bool)
    row_change[0] = True
    np.not_equal(fr[1:], fr[:-1], out=row_change[1:])
    col_gap = np.empty_like(fc, dtype=bool)
    col_gap[0] = True
    np.not_equal(fc[1:], fc[:-1] + 1, out=col_gap[1:])
    run_start = row_change | col_gap

    starts = np.flatnonzero(run_start)
    ends = np.append(starts[1:] - 1, fr.size - 1)
    rows = fr[starts]
    col_starts = fc[starts]
    col_ends = fc[ends] + 1
    return [(int(r), int(cs), int(ce))
            for r, cs, ce in zip(rows.tolist(), col_starts.tolist(), col_ends.tolist())]


def analyze_grid_hierarchical(parsed_geometries, grid_plan,
                               return_cell_indices=False,
                               collect_debug_info=False,
                               return_row_runs=False,
                               on_level_done=None,
                               grid_policy_config: GridPolicyConfig = None):
    """Vectorized hierarchical quadtree area engine.

    Returns (cpu_results_list, hierarchical_detail_list).
    cpu_results_list[i] is a CPULevelResult -- same interface as CPU engine.

    ``return_cell_indices`` / ``return_row_runs`` may each be a plain bool or a
    per-level callable ``(level_idx, total_cells) -> bool`` so the RASH-HIT Engine output
    policy can gate raw filled-cell index collection (expensive) while still
    collecting compact row-runs for run-length merged SVG maps.

    ``on_level_done`` (optional): ``Callable[[int, CPULevelResult, HierarchicalLevelResult], None]``
    invoked immediately after each level's counting finishes (not after the whole
    run), enabling realtime per-level progress (live scale rows) in the UI.

    ``grid_policy_config`` (optional): the grid-origin policy (Stage 3.2).
    Defaults to ``FIXED_ORIGIN`` (canonical viewBox origin; no per-level offset
    search).  This guarantees that a common level's result never depends on the
    requested maximum level.
    """
    if grid_policy_config is None:
        grid_policy_config = GridPolicyConfig()
    else:
        grid_policy_config = resolve_grid_policy(grid_policy_config)
    results, details = [], []

    valid_geoms = [g for g in parsed_geometries
                   if g.shapely_obj and not g.shapely_obj.is_empty]
    if not valid_geoms:
        for lvl in grid_plan.levels:
            r = CPULevelResult(lvl, 0, lvl.total_cells, 0.0)
            detail = HierarchicalLevelResult(r, 0, 0, 0, 0, 0.0)
            results.append(r)
            details.append(detail)
            if on_level_done is not None:
                try:
                    on_level_done(len(results) - 1, r, detail)
                except Exception:
                    pass
        return results, details

    fill_geoms    = [g for g in valid_geoms if g.geom_type == 'fill']
    stroke_geoms  = [g for g in valid_geoms if g.geom_type == 'stroke']
    fill_objs     = [g.shapely_obj for g in fill_geoms]
    stroke_objs   = [g.shapely_obj for g in stroke_geoms]
    stroke_widths = np.array([g.stroke_width for g in stroke_geoms], dtype=np.float64)

    fill_tree   = STRtree(fill_objs)   if fill_objs   else None
    stroke_envelope_objs = [
        shapely.box(s.bounds[0] - w / 2.0, s.bounds[1] - w / 2.0, s.bounds[2] + w / 2.0, s.bounds[3] + w / 2.0)
        if w > 0 else s
        for s, w in zip(stroke_objs, stroke_widths)
    ] if stroke_objs else None
    stroke_tree = STRtree(stroke_envelope_objs) if stroke_envelope_objs else None
    # Precompute geometry object arrays once per analysis instead of rebuilding
    # a Python list-comp into an object array on every level (RASH-HIT Engine perf).
    fill_obj_arr   = np.asarray(fill_objs,   dtype=object) if fill_objs   else None
    stroke_obj_arr = np.asarray(stroke_objs, dtype=object) if stroke_objs else None

    xmin, ymin     = grid_plan.xmin, grid_plan.ymin
    active_parents = None   # (M,2) int32; None means full grid at L1
    known_empty_contrib = np.zeros(len(grid_plan.levels), dtype=np.int64)
    strict_2x_guard_passed = True
    for i in range(1, len(grid_plan.levels)):
        prev_l = grid_plan.levels[i-1]
        curr_l = grid_plan.levels[i]
        if curr_l.cols != prev_l.cols * 2 or curr_l.rows != prev_l.rows * 2:
            strict_2x_guard_passed = False
            break
    prev_total_cells = 0
    prev_active_parent_count = 0

    for lvl_idx, lvl in enumerate(grid_plan.levels):
        t0             = time.perf_counter()
        cols, rows     = lvl.cols, lvl.rows
        cell_w, cell_h = lvl.cell_w, lvl.cell_h

        # RASH-HIT Engine per-level collection flags (bool or policy callable)
        want_indices = _resolve_level_flag(return_cell_indices, lvl.level_idx, lvl.total_cells)
        want_runs    = _resolve_level_flag(return_row_runs,    lvl.level_idx, lvl.total_cells)

        # --- Generate candidate (row, col) pairs -------------------------
        if lvl_idx > 0 and active_parents is not None and len(active_parents) == 0:
            # Negative-space cache: every parent block was empty, so every child
            # is empty too (safe EMPTY-only pruning) -- skip evaluation entirely.
            cand_rows = np.zeros(0, dtype=np.int32)
            cand_cols = np.zeros(0, dtype=np.int32)
            nc = 0
            filled_mask = np.zeros(0, dtype=bool)
            filled_count = 0
        else:
            if lvl_idx == 0 or active_parents is None or len(active_parents) == 0:
                rr, cc    = np.meshgrid(np.arange(rows, dtype=np.int32),
                                        np.arange(cols, dtype=np.int32), indexing='ij')
                cand_rows = rr.ravel()
                cand_cols = cc.ravel()
            else:
                pr = active_parents[:, 0]
                pc = active_parents[:, 1]
                cand_rows = np.stack([pr*2,   pr*2,     pr*2+1, pr*2+1], axis=1).ravel()
                cand_cols = np.stack([pc*2,   pc*2+1,   pc*2,   pc*2+1], axis=1).ravel()

            x0_a = xmin + cand_cols.astype(np.float64) * cell_w
            y0_a = ymin + cand_rows.astype(np.float64) * cell_h
            x1_a = x0_a + cell_w
            y1_a = y0_a + cell_h
            nc   = len(cand_rows)

            filled_mask = (_bulk_fill_decision(x0_a, y0_a, x1_a, y1_a,
                                               fill_tree, fill_objs,
                                               stroke_tree, stroke_objs, stroke_widths,
                                               fill_obj_arr, stroke_obj_arr)
                           if nc > 0 else np.zeros(0, dtype=bool))

            # Grid-origin policy (Stage 3.2 scientific fix).
            # FIXED_ORIGIN: every level shares the canonical origin; no offset
            # search, so results are reproducible and level-count independent.
            # PER_LEVEL_OPTIMIZED_ORIGIN: each level independently minimises
            # over a FIXED candidate set (never the finest level's cell size).
            if grid_policy_config.policy == GridPolicy.PER_LEVEL_OPTIMIZED_ORIGIN:
                if lvl_idx > 0 and nc > 0:
                    filled_count_opt, filled_mask = optimize_grid_offset(
                        _bulk_fill_decision,
                        cand_rows, cand_cols, filled_mask,
                        rows, cols, cell_w, cell_h,
                        xmin, ymin,
                        fill_tree, fill_objs, stroke_tree, stroke_objs, stroke_widths,
                        fill_obj_arr, stroke_obj_arr,
                        offset_candidate_policy=grid_policy_config.offset_candidate_policy,
                    )
                    # Ensure the filled_count reflects the optimized mask
                    filled_count = filled_count_opt
                else:
                    filled_count = int(filled_mask.sum())
            else:
                filled_count = int(filled_mask.sum())
        new_empty_count = int(nc - filled_count) if nc > 0 else 0
        if strict_2x_guard_passed and new_empty_count > 0:
            for future_idx in range(lvl_idx + 1, len(grid_plan.levels)):
                delta = future_idx - lvl_idx
                known_empty_contrib[future_idx] += np.int64(new_empty_count) * np.int64(4 ** delta)

        filled_indices = None
        if want_indices and filled_mask.any():
            filled_indices = list(zip(cand_rows[filled_mask].tolist(),
                                      cand_cols[filled_mask].tolist()))

        row_runs = None
        if want_runs and filled_mask.any():
            row_runs = _build_row_runs(cand_rows[filled_mask].astype(np.int64),
                                       cand_cols[filled_mask].astype(np.int64))

        t1            = time.perf_counter()
        ms            = (t1 - t0) * 1000.0
        empty_count   = lvl.total_cells - filled_count

        # RASH-HIT Engine expanded Negative-Space-Cache metrics.
        filled_candidate_count = int(filled_count)            # cells touching geometry
        empty_candidate_count  = int(nc - filled_candidate_count) if nc > 0 else int(empty_count)
        negative_space_cached  = max(0, lvl.total_cells - nc)
        prev_active = int(prev_active_parent_count) if lvl_idx > 0 else 0
        if lvl_idx == 0:
            empty_parents_skipped = 0
            partial_sub           = 0
            active_parent_count   = int(filled_candidate_count)
        else:
            partial_sub           = len(active_parents) if active_parents is not None else 0
            active_parent_count   = partial_sub
            empty_parents_skipped = max(0, prev_total_cells - active_parent_count)
        active_growth_rate = (active_parent_count / prev_active) if prev_active > 0 else 0.0
        remaining_delta = max(0, len(grid_plan.levels) - 1 - lvl_idx)
        empty_desc_skip_est = empty_candidate_count * (4 ** remaining_delta)

        res = CPULevelResult(
            level=lvl, filled_count=filled_count, empty_count=empty_count,
            execution_time_ms=ms,
            filled_cells_indices=filled_indices,
            debug_cells=None,
            row_runs=row_runs)
        results.append(res)
        detail = HierarchicalLevelResult(
            res, empty_parents_skipped, 0, partial_sub, nc, ms,
            negative_space_cached_cells=negative_space_cached,
            candidate_count=nc,
            filled_candidate_count=filled_candidate_count,
            empty_candidate_count=empty_candidate_count,
            active_parent_count=active_parent_count,
            previous_active_parent_count=prev_active,
            active_growth_rate=active_growth_rate,
            empty_descendants_skipped_estimate=empty_desc_skip_est,
            return_cell_indices_enabled=bool(want_indices),
            known_empty_contrib=int(known_empty_contrib[lvl_idx]),
            strict_2x_guard_passed=bool(strict_2x_guard_passed),
            storage_mode=("raw" if want_indices else ("rle" if want_runs else "summary_only")),
        )
        details.append(detail)

        # Realtime per-level progress: fire the callback the moment THIS level's
        # counting completes (not after the whole run), so UIs can render the
        # live scale table row-by-row instead of in bulk at the end.
        if on_level_done is not None:
            try:
                on_level_done(lvl_idx, res, detail)
            except Exception:
                pass

        active_parents = (np.stack([cand_rows[filled_mask], cand_cols[filled_mask]], axis=1)
                          .astype(np.int32)
                          if filled_mask.any()
                          else np.empty((0, 2), dtype=np.int32))
        prev_total_cells = lvl.total_cells
        prev_active_parent_count = active_parent_count



    return results, details


def compute_hierarchical_box_counting(
    geoms: List[Any],
    vw: float,
    vh: float,
    grid_specs: Optional[List[Tuple[int, int]]] = None,
    grid_plan: Optional[GridPlan] = None,
    measure_mode: str = "area",
    progress_callback=None,
    profile=None,
    grid_policy_config: GridPolicyConfig = None,
    viewbox_origin: Optional[Tuple[float, float]] = None,
):
    """Executes hierarchical box counting and returns (LevelReportModel list, summary dict).

    progress_callback is invoked once per completed level with the freshly built
    LevelReportModel, enabling live per-level progress (scale rows) in the UI.

    ``profile`` (Optional[OutputProfile | str]): when provided, the RASH-HIT Engine
    output policy decides per level whether the engine collects the expensive raw
    filled-cell index list (``filled_set``) or only the compact row-runs used for
    run-length merged SVG maps. When ``None`` the legacy behaviour is kept:
    every level collects raw indices and no row-runs.

    ``grid_policy_config``: grid-origin policy (default FIXED_ORIGIN).
    ``viewbox_origin``: ``(min_x, min_y)`` of the SVG viewBox; used as the
    canonical FIXED_ORIGIN anchor when provided (defaults to ``(0.0, 0.0)``).
    """
    from .grid_planner import create_grid_plan
    from .level_model import LevelReportModel
    from .output_profiles import (load_output_profile,
                                         should_collect_raw_cell_indices,
                                         should_collect_row_runs)

    if profile is None:
        def _indices_flag(level, total_cells):  # noqa: E306 (legacy behaviour)
            return True

        def _runs_flag(level, total_cells):  # noqa: E306
            return False
    else:
        if isinstance(profile, str):
            profile = load_output_profile(profile)

        def _indices_flag(level, total_cells):
            return should_collect_raw_cell_indices(profile, level, total_cells)

        def _runs_flag(level, total_cells):
            return should_collect_row_runs(profile, level, total_cells)

    if grid_plan is None:
        origin = viewbox_origin if viewbox_origin is not None else (0.0, 0.0)
        grid_plan = create_grid_plan(
            svg_viewbox=(origin[0], origin[1], vw, vh),
            svg_width=vw,
            svg_height=vh,
            manual_grids=grid_specs,
            num_levels=len(grid_specs) if grid_specs else 7
        )

    if grid_policy_config is None:
        grid_policy_config = GridPolicyConfig()
    else:
        grid_policy_config = resolve_grid_policy(grid_policy_config)
    # FIXED_ORIGIN is anchored at the analysis bounds (viewBox min) -- the
    # canonical origin that all levels share.
    if grid_policy_config.policy == GridPolicy.FIXED_ORIGIN:
        grid_policy_config = GridPolicyConfig(
            policy=GridPolicy.FIXED_ORIGIN,
            origin_x=grid_plan.xmin,
            origin_y=grid_plan.ymin,
            offset_candidate_policy=grid_policy_config.offset_candidate_policy,
            policy_version=grid_policy_config.policy_version,
        )

    lvl_models: List[LevelReportModel] = []

    def _emit_level(idx, hr, hd):
        """Build the LevelReportModel for a freshly finished level and fire the
        realtime callback immediately (realtime live scale rows)."""
        lvl_idx = hr.level.level_idx if hasattr(hr.level, 'level_idx') else hr.level
        g_lvl = grid_plan.levels[lvl_idx - 1]
        filled = hr.filled_count
        total = hr.total_cells
        empty = total - filled
        ratio = filled / total if total > 0 else 0.0
        occ_pct = ratio * 100.0

        lm = LevelReportModel(
            level=lvl_idx,
            cols=g_lvl.cols,
            rows=g_lvl.rows,
            grid_label=f"{g_lvl.cols}x{g_lvl.rows}",
            total_cells=total,
            filled_cells=filled,
            empty_cells=empty,
            fill_ratio=ratio,
            occupancy_percent=occ_pct,
            cell_w=g_lvl.cell_w,
            cell_h=g_lvl.cell_h,
            execution_time_ms=hr.execution_time_ms,
            mode=measure_mode.upper()
        )
        if hd is not None:
            lm.empty_parents_skipped = hd.empty_parents_skipped
            lm.negative_space_cached_cells = hd.negative_space_cached_cells
            # RASH-HIT Engine expanded metrics propagate to the level report model so the
            # UI / realtime console can surface them without re-deriving.
            lm.candidate_count = getattr(hd, "candidate_count", 0)
            lm.filled_candidate_count = getattr(hd, "filled_candidate_count", 0)
            lm.empty_candidate_count = getattr(hd, "empty_candidate_count", 0)
            lm.active_parent_count = getattr(hd, "active_parent_count", 0)
            lm.previous_active_parent_count = getattr(hd, "previous_active_parent_count", 0)
            lm.active_growth_rate = getattr(hd, "active_growth_rate", 0.0)
            lm.empty_descendants_skipped_estimate = getattr(hd, "empty_descendants_skipped_estimate", 0)
            lm.return_cell_indices_enabled = getattr(hd, "return_cell_indices_enabled", False)
            lm.cell_storage_mode = getattr(hd, "storage_mode", "summary_only")
        if getattr(hr, "filled_cells_indices", None):
            lm.filled_set = set(hr.filled_cells_indices)
        if getattr(hr, "row_runs", None):
            lm.row_runs = list(hr.row_runs)
        # RASH-HIT Engine: stamp the policy note + storage mode for gated levels.
        if profile is not None and not lm.return_cell_indices_enabled:
            lm.cell_storage_mode = "rle" if lm.row_runs else ("summary_only" if not profile.generate_high_level_svg else "svg_only")
            lm.output_policy_note = (
                f"L{lm.level:02d}: raw cell indices disabled by RASH-HIT Engine policy "
                f"(disable_raw_cell_indices_after_level={profile.disable_raw_cell_indices_after_level}). "
                f"SVG map {'RLE/run-merge' if lm.row_runs else 'summary-only'} rendering."
            )
        lvl_models.append(lm)
        if progress_callback is not None:
            try:
                progress_callback(lm)
            except Exception:
                pass

    analyze_grid_hierarchical(
        geoms, grid_plan,
        return_cell_indices=_indices_flag,
        return_row_runs=_runs_flag,
        on_level_done=_emit_level,
        grid_policy_config=grid_policy_config,
    )

    summary = {
        "total_time_ms": sum(lm.execution_time_ms for lm in lvl_models),
        "levels_count": len(lvl_models),
        "rh_engine_total_empty_parents_skipped": sum(lm.empty_parents_skipped for lm in lvl_models),
        "rh_engine_total_negative_space_cached_cells": sum(lm.negative_space_cached_cells for lm in lvl_models),
    }
    return lvl_models, summary
