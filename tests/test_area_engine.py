# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""v1.3.0 AREA engine parity tests.

The vendored ``src/backend/area`` subpackage is a 1:1 port of the RASH-HIT
Fraktal Studio v2.0.0 exact vector-geometry AREA pipeline (svg_health ->
svg_loader -> geometry_engine -> grid_planner -> intersection_hierarchical ->
regression).  These tests pin the engine's cell counts and Db/R2 on a
deterministic fixture so any accidental drift in the vendored chain is
caught immediately.  Reference values were produced by that vendored code
(itself bit-for-bit verified against the Studio CLI output).
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import skipIf

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_SVG = ROOT / "input_svgs" / "test.svg"


@skipIf(not SAMPLE_SVG.exists(), "sample SVG missing")
class TestAreaEngineParity(unittest.TestCase):
    """Deterministic AREA (default mode) regression snapshot."""

    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(ROOT))
        from run_analysis import analyze_svg_data
        cls.result = analyze_svg_data(str(SAMPLE_SVG), levels=4, measure_mode="area")

    def test_no_error(self):
        self.assertIsNone(self.result.get("error"))

    def test_mode_and_meta(self):
        self.assertEqual(self.result["measure_mode"], "area")
        self.assertIn("AREA Mode Shapely GEOS", self.result["engine_name"])

    def test_level_counts_match_studio_reference(self):
        self.assertEqual(
            [row["filled_count"] for row in self.result["levels"]],
            [32, 128, 420, 1680],
        )
        totals = [row["total_cells"] for row in self.result["levels"]]
        self.assertEqual(totals, [32, 128, 512, 2048])

    def test_db_r2_match_studio_reference(self):
        # Studio-parity reference (L4, canvas_aspect doubling grids,
        # FIXED_ORIGIN): Db = 1.8857..., R2 = 0.9991...
        self.assertAlmostEqual(self.result["fractal_db"], 1.8857, places=4)
        self.assertAlmostEqual(self.result["r2_score"], 0.9991, places=4)

    def test_manifest_schema_ascii_compatible(self):
        # The ASCII exporter consumes exactly these manifest keys.
        manifest = self.result["manifest"]
        self.assertEqual(str(manifest["measure_mode"]), "area")
        self.assertIn("viewBox", manifest)
        self.assertIn("segment_count", manifest)
        self.assertIn("total_compute_seconds", manifest)
        for key in ("cols", "rows", "total_cells", "occupied_cells",
                    "empty_cells", "occupancy_ratio"):
            self.assertIn(key, manifest["per_level"]["1"])

    def test_invalid_measure_mode_rejected(self):
        from run_analysis import analyze_svg_data
        res = analyze_svg_data(str(SAMPLE_SVG), levels=3, measure_mode="nonsense")
        self.assertIn("Invalid measure_mode", res.get("error", ""))


if __name__ == "__main__":
    unittest.main()
