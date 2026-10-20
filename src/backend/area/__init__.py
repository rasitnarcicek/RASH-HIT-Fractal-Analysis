# SPDX-License-Identifier: Apache-2.0
"""Exact vector-geometry AREA box-counting engine (vendored from RASH-HIT Fraktal Studio v2.0.0).

This subpackage provides the visual-fill measure mode (fill + stroke-expanded
polygons + polygon interiors via Shapely/GEOS), matching the Studio pipeline
bit-for-bit: svg_health -> svg_loader -> geometry_engine -> grid_planner ->
intersection_hierarchical -> regression. Default measure mode of the CLI.
"""
