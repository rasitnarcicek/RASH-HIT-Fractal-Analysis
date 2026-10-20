# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""ASCII report generator for the pure NumPy supercover engine.

Writes a human-readable .txt report per motif (and a combined book for batch
runs).  Each report contains a numeric summary table only; no grid map.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

__all__ = [
    "generate_ascii_file",
    "generate_batch_ascii_book",
    "build_output_filename",
    "build_book_filename",
    "now_stamp",
]

ENGINE_NAME = "RASH-HIT Fractal Analysis Engine"

try:
    from . import __version__ as SOFTWARE_VERSION
except Exception:  # pragma: no cover
    SOFTWARE_VERSION = "1.2.1"
HEADER_WIDTH = 80


def now_stamp() -> str:
    """Return ``YYYY-MM-DD_HH-MM-SS`` in local time (filename-safe on Windows)."""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")


def build_output_filename(motif_stem: str, levels: int, stamp: str | None = None,
                          extension: str = "txt") -> str:
    """<stem>_L<n>_<YYYY-MM-DD>_<HH-MM-SS>.<ext>"""
    return f"{motif_stem}_L{int(levels)}_{stamp or now_stamp()}.{extension}"


def build_book_filename(levels: int, stamp: str | None = None,
                        extension: str = "txt") -> str:
    """ascii_book_L<n>_<YYYY-MM-DD>_<HH-MM-SS>.<ext>"""
    return f"ascii_book_L{int(levels)}_{stamp or now_stamp()}.{extension}"


def _format_numeric_summary(levels: Sequence[Dict], max_level: int) -> List[str]:
    """L01..Lnn rows: grid / total / filled / empty / occupancy%."""
    bar = "+-------+----------+-------------+--------------+-------------+-------------+"
    lines: List[str] = []
    lines.append(bar)
    lines.append("| Level | Grid     | Total Cells | Filled Cells | Empty Cells | Occupancy % |")
    lines.append("+-------+----------+-------------+--------------+-------------+-------------+")
    for r in levels:
        lv = r["level_idx"]
        grid = f"{r['cols']}x{r['rows']}" if "cols" in r else r.get("grid", "?")
        total = r["total_cells"]
        filled = r["filled_cells"]
        empty = r["empty_cells"]
        occ = (filled / total * 100.0) if total else 0.0
        lines.append(
            f"|  L{lv:02d}  | {grid:<8} | {total:>11,} | {filled:>12,} | "
            f"{empty:>11,} | {occ:>10.2f}% |"
        )
    lines.append(bar)
    return lines


def generate_ascii_file(manifest: Dict, motif_stem: str, levels: int,
                        out_path: Path, stamp: str | None = None) -> Path:
    """Write a single-motif ASCII report to ``out_path``."""
    out_path = Path(out_path)
    stamp = stamp or now_stamp()
    per_level = manifest["per_level"]
    summary_rows: List[Dict] = []
    for lv in range(1, levels + 1):
        p = per_level[str(lv)]
        summary_rows.append({
            "level_idx": lv,
            "cols": p["cols"],
            "rows": p["rows"],
            "total_cells": p["total_cells"],
            "filled_cells": p["occupied_cells"],
            "empty_cells": p["empty_cells"],
        })

    lines: List[str] = []
    lines.append("=" * HEADER_WIDTH)
    lines.append(f"RASH-HIT FRACTAL ANALYSIS v{SOFTWARE_VERSION} - ASCII OCCUPANCY REPORT")
    lines.append("=" * HEADER_WIDTH)
    lines.append(f"  Motif     : {motif_stem}.svg")
    lines.append(f"  Date      : {stamp}")
    lines.append(f"  Levels    : L{levels}")
    lines.append(f"  Engine    : {ENGINE_NAME}")
    lines.append(f"  ViewBox   : {manifest['viewBox'][2]:.4f} x {manifest['viewBox'][3]:.4f}")
    lines.append(f"  Segments  : {manifest['segment_count']:,}")
    lines.append(f"  Time      : {manifest['total_compute_seconds'] * 1000.0:.2f} ms")
    lines.append("-" * HEADER_WIDTH)
    lines.extend(_format_numeric_summary(summary_rows, levels))
    lines.append(f"  [RESULT] Box-Counting Fractal Dimension Db = {manifest['fractal_dimension']:.4f}")
    lines.append(f"  [RESULT] Linear Regression Fit R2           = {manifest['r_squared']:.4f}")
    lines.append("-" * HEADER_WIDTH)
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def generate_batch_ascii_book(per_motif: Iterable[Tuple[str, Dict]], levels: int,
                              out_path: Path, stamp: str | None = None) -> Path:
    """Write a combined batch book: per-motif summary table only."""
    out_path = Path(out_path)
    stamp = stamp or now_stamp()
    items = list(per_motif)

    lines: List[str] = []
    lines.append("=" * HEADER_WIDTH)
    lines.append(f"RASH-HIT FRACTAL ANALYSIS v{SOFTWARE_VERSION} - BATCH ASCII BOOK")
    lines.append("=" * HEADER_WIDTH)
    lines.append(f"  Date      : {stamp}")
    lines.append(f"  Motifs    : {len(items)}")
    lines.append(f"  Levels    : L{levels}")
    lines.append(f"  Engine    : {ENGINE_NAME}")
    lines.append("-" * HEADER_WIDTH)
    lines.append("")

    lines.append("MASTER SUMMARY")
    lines.append("-" * HEADER_WIDTH)
    lines.append(f"{'Motif':<32} {'Segments':>10} {'Db':>10} {'R2':>10} {'Time ms':>10}")
    lines.append("-" * HEADER_WIDTH)
    for stem, m in items:
        lines.append(
            f"{stem[:32]:<32} {m['segment_count']:>10,} "
            f"{m['fractal_dimension']:>10.4f} {m['r_squared']:>10.4f} "
            f"{m['total_compute_seconds'] * 1000.0:>10.2f}"
        )
    lines.append("-" * HEADER_WIDTH)
    lines.append("")

    for stem, m in items:
        per_level = m["per_level"]
        lines.append("=" * HEADER_WIDTH)
        lines.append(f"MOTIF: {stem}.svg")
        lines.append("=" * HEADER_WIDTH)
        summary_rows = []
        for lv in range(1, levels + 1):
            p = per_level[str(lv)]
            summary_rows.append({
                "level_idx": lv, "cols": p["cols"], "rows": p["rows"],
                "total_cells": p["total_cells"], "filled_cells": p["occupied_cells"],
                "empty_cells": p["empty_cells"],
            })
        lines.extend(_format_numeric_summary(summary_rows, levels))
        lines.append(f"  [RESULT] Db = {m['fractal_dimension']:.4f}    "
                     f"R2 = {m['r_squared']:.4f}")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
