# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""
test_audit_gaps.py — Audit bulgu testleri
Findings covered:
  Bulgu 8:  fill-opacity / stroke-opacity channel alpha in visibility
  Bulgu 9:  SVGLoader.warnings are accessible after get_elements()
  Bulgu 14: --input and --dir are mutually exclusive
  Bulgu 16: fractal R2 returns NaN on zero-variance data
"""

import unittest
import math
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


class TestFillOpacityVisibility(unittest.TestCase):
    """Bulgu 8: fill-opacity / stroke-opacity per-channel alpha."""

    def _node(self, styles: dict):
        from src.backend.svg_loader import SVGNode
        return SVGNode(tag="path", attribs={}, styles=styles, transform_str="")

    def test_fill_opacity_zero_makes_invisible(self):
        """fill-opacity:0 with solid fill must make has_fill=False."""
        n = self._node({'fill': '#000000', 'fill-opacity': '0', 'stroke': 'none', 'opacity': '1.0'})
        self.assertFalse(n.has_fill, "fill-opacity:0 should suppress has_fill")
        self.assertFalse(n.is_visible)

    def test_stroke_opacity_zero_makes_stroke_invisible(self):
        """stroke-opacity:0 with visible stroke must make has_stroke=False."""
        n = self._node({'fill': 'none', 'stroke': '#000000', 'stroke-width': '2',
                        'stroke-opacity': '0', 'opacity': '1.0'})
        self.assertFalse(n.has_stroke, "stroke-opacity:0 should suppress has_stroke")
        self.assertFalse(n.is_visible)

    def test_fill_visible_stroke_opacity_zero_still_visible(self):
        """Visible fill + stroke-opacity:0 => element is still visible via fill."""
        n = self._node({'fill': '#ff0000', 'fill-opacity': '1.0',
                        'stroke': '#000000', 'stroke-width': '2', 'stroke-opacity': '0',
                        'opacity': '1.0'})
        self.assertTrue(n.has_fill)
        self.assertFalse(n.has_stroke)
        self.assertTrue(n.is_visible)

    def test_global_opacity_zero_makes_invisible(self):
        """global opacity:0 should suppress both channels."""
        n = self._node({'fill': '#000000', 'stroke': '#000000', 'stroke-width': '2', 'opacity': '0'})
        self.assertFalse(n.has_fill)
        self.assertFalse(n.has_stroke)
        self.assertFalse(n.is_visible)

    def test_effective_alpha_product(self):
        """effective_fill_alpha must equal opacity * fill-opacity."""
        n = self._node({'fill': '#000000', 'fill-opacity': '0.5', 'opacity': '0.4'})
        self.assertAlmostEqual(n.effective_fill_alpha, 0.2, places=5)


class TestLoaderWarnings(unittest.TestCase):
    """Bulgu 9: SVGLoader.warnings populated after get_elements()."""

    def test_clippath_warning_surfaced(self):
        svg_content = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">
              <clipPath id="cp1"><rect x="0" y="0" width="50" height="50"/></clipPath>
              <rect x="10" y="10" width="80" height="80" fill="#000"/>
            </svg>
        """)
        with tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False, encoding="utf-8") as f:
            f.write(svg_content)
            tmp = f.name
        try:
            from src.backend.svg_loader import SVGLoader
            loader = SVGLoader(tmp)
            loader.get_elements()   # warnings are filled during traversal
            self.assertIsInstance(loader.warnings, list)
            self.assertTrue(
                any('clip' in w.lower() for w in loader.warnings),
                f"Expected clipPath warning after get_elements(); got: {loader.warnings}"
            )
        finally:
            Path(tmp).unlink(missing_ok=True)


class TestInputDirMutuallyExclusive(unittest.TestCase):
    """Bulgu 14: --input and --dir must be mutually exclusive."""

    def test_both_flags_rejected(self):
        cwd = str(Path(__file__).resolve().parent.parent)
        cmd = [sys.executable, "run_analysis.py",
               "--input", "input_svgs/test.svg", "--dir", "input_svgs"]
        res = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", cwd=cwd)
        self.assertNotEqual(res.returncode, 0,
            f"Expected non-zero exit; stdout={res.stdout!r} stderr={res.stderr!r}")
        combined = res.stdout.lower() + res.stderr.lower()
        self.assertTrue(
            "not allowed" in combined or "error" in combined or "mutually exclusive" in combined,
            f"Expected error message; got: {combined[:300]}"
        )


class TestFractalZeroVariance(unittest.TestCase):
    """Bulgu 16: R2 must return NaN when fill counts have zero variance."""

    def _results(self, counts):
        from src.backend.grid_planner import GridLevel
        from src.backend.intersection_cpu import CPULevelResult
        items = []
        for i, cnt in enumerate(counts, start=1):
            rows = 2 ** i
            cols = 2 ** (i + 1)
            # GridLevel(level_idx, cols, rows, analysis_w, analysis_h)
            gl = GridLevel(level_idx=i, cols=cols, rows=rows,
                           analysis_w=float(cols), analysis_h=float(rows))
            items.append(CPULevelResult(
                level=gl,
                filled_count=cnt,
                empty_count=(rows * cols) - cnt,
                execution_time_ms=0.1,
                filled_cells_indices=[],
            ))
        return items

    def test_constant_counts_give_nan_r2(self):
        from src.backend.fractal_analyzer import compute_fractal_dimension
        fa = compute_fractal_dimension(self._results([100, 100, 100, 100, 100]))
        self.assertTrue(math.isnan(fa.r2_score),
                        f"Expected NaN R2 on zero-variance data, got {fa.r2_score}")

    def test_varying_counts_give_finite_r2(self):
        from src.backend.fractal_analyzer import compute_fractal_dimension
        fa = compute_fractal_dimension(self._results([10, 40, 160, 640, 2560]))
        self.assertFalse(math.isnan(fa.r2_score),
                         "Expected finite R2 on varying data, got NaN")
        self.assertGreaterEqual(fa.r2_score, -1.0)
        self.assertLessEqual(fa.r2_score, 1.0)


if __name__ == "__main__":
    unittest.main()
