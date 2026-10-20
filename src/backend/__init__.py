# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek

# backend/__init__.py
"""RASH-HIT Fractal Analysis Engine backend.

v1.3.0: two measure modes.
  * ``area`` (default): exact vector-geometry visual-fill box counting
    (fill + stroke-expanded polygons + polygon interiors, Shapely/GEOS) —
    vendored 1:1 from RASH-HIT Fraktal Studio v2.0.0 (# backend.area).
  * ``supercover``: legacy pure NumPy geometric-contact engine (v1.2.2).

Version history
  1.2.2: pure NumPy supercover engine only (no Shapely/GEOS).
  1.3.0: Studio-parity AREA engine as default mode.
"""

__version__ = "1.3.0"
__engine_name__ = "RASH-HIT Fractal Analysis Engine"
__engine_area_label__ = "RASH-HIT Exact Vector Geometry Engine ( AREA Mode Shapely GEOS )"
__engine_supercover_label__ = "Pure NumPy Supercover Engine ( Geometric-Contact CPU )"
