# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek

from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class OutputProfile:
    name: str
    generate_workbook: bool = True
    generate_xlsx_tables: bool = False
    generate_tables_html: bool = False
    generate_map_svgs: bool = True
    generate_map_svgs_legacy: bool = False
    generate_html_report: bool = True
    generate_pdf_report: bool = False
    generate_markdown_report: bool = False
    generate_manifest: bool = True
    generate_terminal_log: bool = False
    generate_ascii: bool = False
    generate_ascii_book: bool = False
    generate_masks: bool = False
    generate_rle: bool = False
    generate_raw_csv: bool = False
    generate_levels_csv: bool = False
    generate_levels_json: bool = False
    generate_summary_json: bool = False

    # ── RASH-HIT Fractal Analiz Engine: Negative Space Cache & High-Level Output Policy ────────────
    # Thresholds that cut both compute and artifact generation at high levels
    # (L9/L10/L11+). All values are per-profile overrides with safe defaults.
    #
    # Level gating is *strict* on the ``after_*`` fields (``level > threshold``
    # or ``total_cells > threshold`` disables/forces the behaviour) and *inclusive*
    # on the ``max_*`` caps (``level <= cap and total_cells <= cap`` stays enabled).
    max_excel_cell_map_level: int = 6
    max_excel_cell_map_cells: int = 65_536
    disable_raw_cell_indices_after_level: int = 8
    disable_raw_cell_indices_after_cells: int = 500_000
    force_svg_rle_after_level: int = 9
    force_svg_rle_after_cells: int = 250_000
    summary_only_after_level: int = 8
    svg_only_after_level: int = 9
    generate_high_level_svg: bool = True
    generate_high_level_excel_summary: bool = True
    generate_high_level_cell_tables: bool = False

    # ── RASH-HIT Fractal Analiz Engine B: Parallel Multi-Core Candidate Evaluation ──────────────────
    enable_parallel_counting: bool = True
    parallel_min_candidates: int = 4000
    parallel_workers: Optional[int] = None
    parallel_backend: str = "thread"
    parallel_chunk_target: int = 250_000

PROFILES: Dict[str, OutputProfile] = {
    "lean": OutputProfile(
        name="lean", generate_workbook=True,
        generate_map_svgs=True, generate_map_svgs_legacy=False, generate_html_report=True, generate_pdf_report=False,
        generate_markdown_report=False, generate_manifest=True, generate_terminal_log=False,
        generate_ascii=False, generate_ascii_book=False, generate_masks=False, generate_rle=False,
        generate_raw_csv=False, generate_levels_csv=False, generate_levels_json=False, generate_summary_json=False,
    ),
    "reproducible": OutputProfile(
        name="reproducible", generate_workbook=True, generate_xlsx_tables=True, generate_tables_html=True,
        generate_map_svgs=True, generate_map_svgs_legacy=False, generate_html_report=True, generate_pdf_report=False,
        generate_markdown_report=False, generate_manifest=True, generate_terminal_log=False,
        generate_ascii=False, generate_ascii_book=False, generate_masks=True, generate_rle=True,
        generate_raw_csv=False, generate_levels_csv=True, generate_levels_json=True, generate_summary_json=True,
    ),
    "debug": OutputProfile(
        name="debug", generate_workbook=True, generate_xlsx_tables=True, generate_tables_html=True,
        generate_map_svgs=True, generate_map_svgs_legacy=True, generate_html_report=True, generate_pdf_report=False,
        generate_markdown_report=False, generate_manifest=True, generate_terminal_log=False,
        generate_ascii=True, generate_ascii_book=True, generate_masks=True, generate_rle=True,
        generate_raw_csv=True, generate_levels_csv=True, generate_levels_json=True, generate_summary_json=True,
        # RASH-HIT Engine explicit override: debug must never emit raw cell indices at L10+
        # even though generate_* flags above allow everything else. The counting
        # engine honours disable_raw_cell_indices_after_*; debug keeps its verbose
        # cell maps only up to L9.
        disable_raw_cell_indices_after_level=9,
        disable_raw_cell_indices_after_cells=500_000,
        force_svg_rle_after_level=9,
        summary_only_after_level=9,
    ),
    "presentation": OutputProfile(
        name="presentation", generate_workbook=True,
        generate_map_svgs=True, generate_map_svgs_legacy=True, generate_html_report=True, generate_pdf_report=False,
        generate_markdown_report=False, generate_manifest=True, generate_terminal_log=False,
        generate_ascii=False, generate_ascii_book=False, generate_masks=False, generate_rle=False,
        generate_raw_csv=False, generate_levels_csv=False, generate_levels_json=False, generate_summary_json=False,
    ),
    # `batch` is lean-derived but tuned for multi-SVG throughput: the SVG-only
    # gate is pulled down from L10 to L9, so L10+ batch packages keep their
    # SVG maps while dropping per-cell Excel tables / cell payloads one level
    # earlier. Every other RASH-HIT Engine threshold stays at the lean defaults.
    "batch": OutputProfile(
        name="batch", generate_workbook=True,
        generate_map_svgs=True, generate_map_svgs_legacy=False, generate_html_report=True, generate_pdf_report=False,
        generate_markdown_report=False, generate_manifest=True, generate_terminal_log=False,
        generate_ascii=False, generate_ascii_book=False, generate_masks=False, generate_rle=False,
        generate_raw_csv=False, generate_levels_csv=False, generate_levels_json=False, generate_summary_json=False,
        svg_only_after_level=9,
    ),
}

def load_output_profile(name: Optional[str] = None) -> OutputProfile:
    if not name:
        return PROFILES["lean"]
    key = name.lower().strip()
    if key not in PROFILES:
        valid_keys = ", ".join(PROFILES.keys())
        raise ValueError(f"Unknown output profile '{name}'. Valid profiles: {valid_keys}")
    return PROFILES[key]


# ── RASH-HIT Fractal Analiz Engine policy helpers ────────────────────────────────────────────────────
#
# These gate both the counting engine (raw filled-cell index collection) and the
# exporter (Excel cell maps, per-cell XLSX tables, per-cell JSON, SVG run-length maps).
# The rules are strictly EMPTY-pruning safe: nothing here ever short-circuits a
# non-empty parent (no FULL shortcut) and every gated artifact is *skipped*, never
# approximated.


def should_collect_raw_cell_indices(profile: OutputProfile, level: int, total_cells: int) -> bool:
    """True when the engine should return the raw filled-cell index list for a level.

    Disabled when ``level > disable_raw_cell_indices_after_level`` OR
    ``total_cells > disable_raw_cell_indices_after_cells``. When disabled, the
    engine returns compact row-runs instead (sufficient for exact SVG maps), so
    ``filled_set`` stays empty and every filled-set dependent artifact is skipped.
    """
    if level > profile.disable_raw_cell_indices_after_level:
        return False
    if total_cells > profile.disable_raw_cell_indices_after_cells:
        return False
    return True


def is_high_level(profile: OutputProfile, level: int) -> bool:
    """Levels subject to the RASH-HIT Engine high-level policy (default: L9+)."""
    return level > profile.max_excel_cell_map_level


def should_generate_excel_cell_map(profile: OutputProfile, level: int, total_cells: int) -> bool:
    """True when per-level Excel cell-map sheets and per-cell XLSX tables are produced.

    A level is mapped only while raw cell data is available (indices collected),
    it is inside the ``max_excel_cell_map_*`` caps, it is not SVG-only or
    summary-only, and the high-level cell-tables master switch is not turned off.

    Note: ``summary_only_after_level`` is consulted here too, so a level that is
    "summary-only" never emits per-cell tables even if ``max_excel_cell_map_*``
    caps were raised past it.
    """
    if level > profile.svg_only_after_level:
        return False
    if not should_collect_raw_cell_indices(profile, level, total_cells):
        return False
    if is_summary_only_level(profile, level):
        return False
    if level <= profile.max_excel_cell_map_level and total_cells <= profile.max_excel_cell_map_cells:
        return True
    return profile.generate_high_level_cell_tables


def should_generate_svg_map(profile: OutputProfile, level: int) -> bool:
    """True when a pure-vector SVG map is generated for a level (incl. RLE maps)."""
    if not profile.generate_map_svgs:
        return False
    if is_high_level(profile, level) and not profile.generate_high_level_svg:
        return False
    return True


def should_collect_row_runs(profile: OutputProfile, level: int, total_cells: int) -> bool:
    """True when the engine should return compact per-row filled runs for a level.

    Row runs are collected exactly when raw indices are disabled but an SVG map is
    still wanted (run-length / row-run merged SVG rendering).
    """
    if should_collect_raw_cell_indices(profile, level, total_cells):
        return False
    return should_generate_svg_map(profile, level)


def should_force_svg_rle(profile: OutputProfile, level: int, total_cells: int) -> bool:
    """True when the SVG map for a level uses run-length / row-run merged rects.

    Forced when ``level >= force_svg_rle_after_level`` OR
    ``total_cells > force_svg_rle_after_cells``.
    """
    if level >= profile.force_svg_rle_after_level:
        return True
    if total_cells > profile.force_svg_rle_after_cells:
        return True
    return False


def is_summary_only_level(profile: OutputProfile, level: int) -> bool:
    """Levels strictly above ``summary_only_after_level`` emit summary data only
    (no per-cell JSON payloads, no cell tables)."""
    return level > profile.summary_only_after_level


def is_svg_only_level(profile: OutputProfile, level: int) -> bool:
    """Levels strictly above ``svg_only_after_level`` produce SVG maps only."""
    return level > profile.svg_only_after_level


# Aliases for RASH-HIT Engine contract
should_materialize_cell_indices = should_collect_raw_cell_indices
should_export_excel_cell_map = should_generate_excel_cell_map
should_use_svg_rle = should_force_svg_rle

