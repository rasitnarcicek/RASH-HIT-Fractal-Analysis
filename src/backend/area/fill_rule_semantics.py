# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""Stage 7A — SVG Fill Rule Semantics, Ring Orientation & Topological Classification.

Provides deterministic, scientific semantics for:
1. EVENODD: Parity-based ray casting from point to infinity. Orientation independent.
2. NONZERO: Winding number accumulation along nested subpaths. Orientation sensitive.
3. Subpath and ring decomposition (signed shoelace area, orientation, depth, hole status).
4. Explicit geometry repair logging (make_valid / buffer(0)).
5. Dual-reference topological classification vs Shapely geometry evaluation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.validation import make_valid


class FillRule(str, Enum):
    """SVG fill rule enumeration."""
    EVENODD = "evenodd"
    NONZERO = "nonzero"

    @classmethod
    def from_str(cls, val: Optional[str | FillRule], default: Optional[FillRule] = None) -> Tuple[FillRule, Optional[str]]:
        """Normalize string or enum to FillRule. Returns (rule, warning_message_if_invalid)."""
        if default is None:
            default = cls.NONZERO
        if val is None:
            return default, None
        if isinstance(val, cls):
            return val, None
        v_clean = str(val).strip().lower()
        if v_clean in ("evenodd", "fillrule.evenodd"):
            return cls.EVENODD, None
        if v_clean in ("nonzero", "fillrule.nonzero"):
            return cls.NONZERO, None
        warning = f"Invalid fill-rule '{val}' encountered; defaulted to '{default.value}' per SVG specification."
        return default, warning


class RingOrientation(str, Enum):
    """Geometric 2D ring orientation."""
    CLOCKWISE = "clockwise"
    COUNTERCLOCKWISE = "counterclockwise"
    DEGENERATE = "degenerate"


class BoundaryPolicy(str, Enum):
    """Cell occupancy boundary inclusion policy."""
    AREA_POSITIVE_INTERSECTION = "AREA_POSITIVE_INTERSECTION"
    GEOMETRIC_TOUCH_COUNTS = "GEOMETRIC_TOUCH_COUNTS"


DEFAULT_SVG_FILL_RULE = FillRule.NONZERO


def compute_signed_ring_area(pts: Sequence[Tuple[float, float]]) -> float:
    """Signed Shoelace area of a 2D closed polygon ring.

    Convention:
    - Positive signed area (> 0): Counter-Clockwise (CCW) in standard Cartesian (x-right, y-up),
      or Clockwise (CW) in screen coordinates (x-right, y-down).
    - We adopt the standard SVG / screen coordinate Shoelace convention:
      S = 0.5 * sum(x_i * y_{i+1} - x_{i+1} * y_i)
      If S > 0: Clockwise in screen coordinates (x-right, y-down).
      If S < 0: Counter-Clockwise in screen coordinates.
      If |S| < 1e-12 or len < 3: 0.0 (Degenerate).
    """
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    area = 0.5 * s
    if abs(area) < 1e-12 or not math.isfinite(area):
        return 0.0
    return float(area)


def determine_ring_orientation(signed_area: float) -> RingOrientation:
    """Classify ring orientation based on signed area in SVG screen coordinates."""
    if abs(signed_area) < 1e-12:
        return RingOrientation.DEGENERATE
    if signed_area > 0.0:
        return RingOrientation.CLOCKWISE
    return RingOrientation.COUNTERCLOCKWISE


@dataclass
class SubpathRing:
    """Detailed structural representation of a single subpath ring."""
    index: int
    start_point: Tuple[float, float]
    is_closed: bool
    path_explicitly_closed: bool
    implicit_fill_closure: bool
    vertices: List[Tuple[float, float]]
    signed_area: float
    abs_area: float
    orientation: RingOrientation
    is_degenerate: bool
    nesting_depth: int = 0
    parent_index: Optional[int] = None
    is_hole: bool = False
    winding_contribution: int = 0  # +1 for CW, -1 for CCW, 0 for degenerate
    fill_rule: FillRule = FillRule.NONZERO
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "start_point": list(self.start_point),
            "is_closed": self.is_closed,
            "path_explicitly_closed": self.path_explicitly_closed,
            "implicit_fill_closure": self.implicit_fill_closure,
            "vertex_count": len(self.vertices),
            "signed_area": round(self.signed_area, 6),
            "abs_area": round(self.abs_area, 6),
            "orientation": self.orientation.value,
            "is_degenerate": self.is_degenerate,
            "nesting_depth": self.nesting_depth,
            "parent_index": self.parent_index,
            "is_hole": self.is_hole,
            "winding_contribution": self.winding_contribution,
            "fill_rule": self.fill_rule.value,
            "warnings": list(self.warnings),
        }


@dataclass
class GeometryRepairLog:
    """Audit record for any geometry repair performed on invalid topologies."""
    repair_type: str            # e.g., "make_valid", "buffer(0)"
    reason: str                 # e.g., "Self-intersecting ring exterior"
    area_before: float
    area_after: float
    delta_area: float
    scientific_warning: str
    is_valid_before: bool = False
    is_valid_after: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repair_type": self.repair_type,
            "reason": self.reason,
            "area_before": round(self.area_before, 6),
            "area_after": round(self.area_after, 6),
            "delta_area": round(self.delta_area, 6),
            "is_valid_before": self.is_valid_before,
            "is_valid_after": self.is_valid_after,
            "scientific_warning": self.scientific_warning,
        }


def repair_invalid_polygon(
    poly: Polygon,
    reason: str,
    ring_index: Optional[int] = None,
) -> Tuple[Any, Optional[GeometryRepairLog]]:
    """Repairs invalid or self-intersecting polygon geometries with strict preference order.

    Topological Repair Order & Strategy:
    1. Primary Method: GEOS `make_valid(poly)`
       - Preserves orientation and decomposes self-intersecting bowties/figure-eights into
         valid multi-polygonal lobes without eroding or dilating boundaries.
    2. Fallback Method: GEOS `poly.buffer(0)`
       - Used strictly as a controlled fallback if `make_valid` fails, is unavailable,
         or returns a non-polygonal collection.
    3. Failure / Degenerate Handling:
       - If both fail, an empty geometry and scientific warning are logged.

    Returns:
        (repaired_geom, GeometryRepairLog or None)
    """
    if poly.is_valid:
        return poly, None

    area_before = float(poly.area)
    idx_str = f"Ring {ring_index}" if ring_index is not None else "Polygon"
    repaired = None
    repair_type = "make_valid"

    # 1. Primary Method: make_valid
    try:
        candidate = make_valid(poly)
        if candidate.is_valid and not candidate.is_empty:
            if candidate.geom_type in ("Polygon", "MultiPolygon"):
                repaired = candidate
            elif hasattr(candidate, "geoms"):
                # Extract valid polygon components from GeometryCollection
                poly_parts = [g for g in candidate.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
                if poly_parts:
                    repaired = unary_union(poly_parts)
    except Exception:
        repaired = None

    # 2. Fallback Method: buffer(0)
    if repaired is None or not repaired.is_valid or repaired.is_empty:
        try:
            candidate = poly.buffer(0)
            if candidate.is_valid and not candidate.is_empty:
                if candidate.geom_type in ("Polygon", "MultiPolygon"):
                    repaired = candidate
                    repair_type = "buffer(0)"
                elif hasattr(candidate, "geoms"):
                    poly_parts = [g for g in candidate.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
                    if poly_parts:
                        repaired = unary_union(poly_parts)
                        repair_type = "buffer(0)"
        except Exception:
            repaired = None

    # 3. Handle final repaired result or failure
    if repaired is not None and repaired.is_valid and not repaired.is_empty:
        area_after = float(repaired.area)
        delta_area = area_after - area_before
        log = GeometryRepairLog(
            repair_type=repair_type,
            reason=reason,
            area_before=area_before,
            area_after=area_after,
            delta_area=delta_area,
            is_valid_before=False,
            is_valid_after=True,
            scientific_warning=(
                f"{idx_str} invalid topology repaired via {repair_type} "
                f"(area before: {area_before:.4f}, after: {area_after:.4f}, delta: {delta_area:.4f})"
            ),
        )
        return repaired, log

    # Complete failure: return empty geometry with error log
    log = GeometryRepairLog(
        repair_type="failed",
        reason=reason,
        area_before=area_before,
        area_after=0.0,
        delta_area=-area_before,
        is_valid_before=False,
        is_valid_after=False,
        scientific_warning=f"{idx_str} could not be repaired into a valid polygon via make_valid or buffer(0); marked empty.",
    )
    return Polygon(), log


@dataclass
class RingClassificationResult:
    """Complete topological and winding classification report for subpaths."""
    fill_rule: FillRule
    rings: List[SubpathRing]
    outer_rings_count: int
    hole_rings_count: int
    degenerate_rings_count: int
    total_analytic_area: float
    bounds: Tuple[float, float, float, float]
    has_implicit_fill_closure: bool = False
    warnings: List[str] = field(default_factory=list)
    repairs: List[GeometryRepairLog] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fill_rule": self.fill_rule.value,
            "ring_count": len(self.rings),
            "outer_rings_count": self.outer_rings_count,
            "hole_rings_count": self.hole_rings_count,
            "degenerate_rings_count": self.degenerate_rings_count,
            "total_analytic_area": round(self.total_analytic_area, 6),
            "bounds": [round(b, 6) for b in self.bounds],
            "has_implicit_fill_closure": self.has_implicit_fill_closure,
            "warnings": list(self.warnings),
            "repairs": [r.to_dict() for r in self.repairs],
            "rings": [r.to_dict() for r in self.rings],
        }


def _point_in_polygon_ray_casting(point: Tuple[float, float], polygon_pts: Sequence[Tuple[float, float]]) -> bool:
    """Ray casting algorithm to test if point is inside a 2D polygon."""
    x, y = point
    n = len(polygon_pts)
    inside = False
    for i in range(n):
        x1, y1 = polygon_pts[i]
        x2, y2 = polygon_pts[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-15) + x1:
                inside = not inside
    return inside


def classify_subpath_rings(
    subpaths: Sequence[Sequence[Tuple[float, float]]],
    fill_rule: FillRule | str = FillRule.NONZERO,
) -> RingClassificationResult:
    """Topological classification of subpaths under the specified fill rule.

    Performs pure geometric containment, nesting depth calculation, and winding number
    accumulation without relying on external CAD libraries.
    """
    f_rule, f_warn = FillRule.from_str(fill_rule) if isinstance(fill_rule, str) else (fill_rule, None)
    global_warnings: List[str] = []
    if f_warn:
        global_warnings.append(f_warn)

    rings: List[SubpathRing] = []

    # 1. Parse each subpath into initial SubpathRing
    for idx, raw_pts in enumerate(subpaths):
        pts = list(raw_pts)
        path_explicitly_closed = len(pts) >= 4 and pts[0] == pts[-1]
        implicit_fill_closure = False
        if len(pts) >= 3 and pts[0] != pts[-1]:
            # SVG Fill Rule standard: Open subpaths are implicitly closed by adding
            # a straight line connecting the last point to the initial point for fill evaluation.
            pts = list(pts) + [pts[0]]
            implicit_fill_closure = True

        is_closed = path_explicitly_closed or implicit_fill_closure

        signed_area = compute_signed_ring_area(pts)
        abs_area = abs(signed_area)
        orientation = determine_ring_orientation(signed_area)
        is_degenerate = abs_area < 1e-12 or len(pts) < 4

        w_contrib = 0
        ring_warnings = []
        if is_degenerate:
            # Check if this is a self-intersecting polygon whose lobes cancel out in simple Shoelace
            if len(pts) >= 4:
                try:
                    p_test = Polygon(pts)
                    if not p_test.is_valid:
                        p_fixed, rep_log = repair_invalid_polygon(
                            p_test,
                            reason=f"Self-intersecting subpath {idx} exterior",
                            ring_index=idx,
                        )
                        if p_fixed is not None and not p_fixed.is_empty and p_fixed.area > 1e-12:
                            is_degenerate = False
                            abs_area = float(p_fixed.area)
                            orientation = RingOrientation.CLOCKWISE
                            w_contrib = 1
                            if rep_log is not None:
                                ring_warnings.append(rep_log.scientific_warning)
                except Exception:
                    pass

        if is_degenerate:
            if len(raw_pts) < 3:
                ring_warnings.append(f"Subpath {idx} has fewer than 3 vertices ({len(raw_pts)}); marked degenerate.")
            elif abs_area < 1e-12:
                ring_warnings.append(f"Subpath {idx} has near-zero area ({signed_area:.2e}); marked degenerate.")
        elif w_contrib == 0:
            w_contrib = 1 if orientation == RingOrientation.CLOCKWISE else -1

        if implicit_fill_closure and not is_degenerate:
            ring_warnings.append(f"Subpath {idx} was implicitly closed for fill evaluation (SVG standard §11.4/§13.4.2).")

        start_pt = pts[0] if pts else (0.0, 0.0)
        rings.append(SubpathRing(
            index=idx,
            start_point=start_pt,
            is_closed=is_closed,
            path_explicitly_closed=path_explicitly_closed,
            implicit_fill_closure=implicit_fill_closure,
            vertices=pts,
            signed_area=signed_area,
            abs_area=abs_area,
            orientation=orientation,
            is_degenerate=is_degenerate,
            nesting_depth=0,
            parent_index=None,
            is_hole=False,
            winding_contribution=w_contrib,
            fill_rule=f_rule,
            warnings=ring_warnings,
        ))

    non_degen = [r for r in rings if not r.is_degenerate and r.is_closed]
    n = len(non_degen)

    # 2. Build containment matrix: contains[i][j] is True if non_degen[i] contains non_degen[j]
    if n > 1:
        contains = [[False] * n for _ in range(n)]
        for i in range(n):
            poly_i = non_degen[i].vertices
            for j in range(n):
                if i == j:
                    continue
                # Ring j must have smaller area to be inside ring i
                if non_degen[i].abs_area <= non_degen[j].abs_area:
                    continue
                # Test interior representative point of j against polygon i
                # Representative point: centroid or first vertex
                test_pt = non_degen[j].vertices[0]
                if _point_in_polygon_ray_casting(test_pt, poly_i):
                    contains[i][j] = True

        # Assign nesting depths and direct parents
        for j in range(n):
            parent_candidates = [i for i in range(n) if contains[i][j]]
            non_degen[j].nesting_depth = len(parent_candidates)
            if parent_candidates:
                # Direct parent is the candidate with the smallest area among all enclosing parents
                direct_parent_idx = min(parent_candidates, key=lambda k: non_degen[k].abs_area)
                non_degen[j].parent_index = non_degen[direct_parent_idx].index

    # 3. Classify Holes vs Solids according to FillRule
    outer_count = 0
    hole_count = 0
    degen_count = sum(1 for r in rings if r.is_degenerate)

    if f_rule == FillRule.EVENODD:
        # EVENODD: Parity rule based on nesting depth.
        # Depth % 2 == 0 -> Solid / Outer / Island
        # Depth % 2 == 1 -> Hole
        for r in non_degen:
            if r.nesting_depth % 2 == 1:
                r.is_hole = True
                hole_count += 1
            else:
                r.is_hole = False
                outer_count += 1
    else:
        # NONZERO: Winding number accumulation along ancestry tree.
        for r in non_degen:
            if r.nesting_depth == 0:
                r.is_hole = False
                outer_count += 1
            else:
                # Trace winding sum from root to this ring
                # Collect ancestry path from root to r
                ancestry = []
                curr = r
                while curr.parent_index is not None:
                    ancestry.append(curr)
                    p_obj = next((x for x in non_degen if x.index == curr.parent_index), None)
                    if not p_obj or p_obj in ancestry:
                        break
                    curr = p_obj
                ancestry.append(curr)
                ancestry.reverse()  # Root is ancestry[0], r is ancestry[-1]

                winding_sum = 0
                for a in ancestry:
                    winding_sum += a.winding_contribution

                # If winding_sum reaches 0 at this ring, it cancels the parent and is a HOLE
                if winding_sum == 0:
                    r.is_hole = True
                    hole_count += 1
                else:
                    # Nonzero winding: region is filled
                    r.is_hole = False
                    outer_count += 1

    # 4. Compute bounding box and total analytic area
    all_pts = [p for r in non_degen for p in r.vertices]
    if all_pts:
        xs = [p[0] for p in all_pts]
        ys = [p[1] for p in all_pts]
        bounds = (min(xs), min(ys), max(xs), max(ys))
    else:
        bounds = (0.0, 0.0, 0.0, 0.0)

    # Analytic area calculation
    # A solid ring at depth > 0 only adds new area if its immediate enclosing parent is a hole
    solid_area = sum(r.abs_area for r in non_degen if not r.is_hole and r.nesting_depth == 0)
    holes_area = sum(r.abs_area for r in non_degen if r.is_hole)
    islands_area = sum(
        r.abs_area for r in non_degen
        if not r.is_hole and r.nesting_depth > 0 and any(p.index == r.parent_index and p.is_hole for p in non_degen)
    )
    total_area = max(0.0, solid_area - holes_area + islands_area)
    has_implicit = any(r.implicit_fill_closure for r in rings)

    return RingClassificationResult(
        fill_rule=f_rule,
        rings=rings,
        outer_rings_count=outer_count,
        hole_rings_count=hole_count,
        degenerate_rings_count=degen_count,
        total_analytic_area=total_area,
        bounds=bounds,
        has_implicit_fill_closure=has_implicit,
        warnings=global_warnings,
    )


def build_fill_geometry_with_semantics(
    subpaths: Sequence[Sequence[Tuple[float, float]]],
    fill_rule: FillRule | str = FillRule.NONZERO,
) -> Tuple[Optional[Any], RingClassificationResult]:
    """Constructs exact Shapely Polygon/MultiPolygon geometry conforming to fill-rule semantics.

    Guarantees:
    - Never modifies geometry silently: all repairs (make_valid, buffer(0)) are logged.
    - Handles evenodd (XOR / parity symmetric difference) and nonzero (winding tree).
    - Returns (shapely_geometry_or_None, RingClassificationResult).
    """
    f_rule, f_warn = FillRule.from_str(fill_rule) if isinstance(fill_rule, str) else (fill_rule, None)
    class_res = classify_subpath_rings(subpaths, fill_rule=f_rule)

    non_degen = [r for r in class_res.rings if not r.is_degenerate and r.is_closed and len(r.vertices) >= 4]
    if not non_degen:
        return None, class_res

    # Build initial Shapely polygons for each non-degenerate ring
    poly_list: List[Polygon] = []
    for r in non_degen:
        p = Polygon(r.vertices)
        if not p.is_valid:
            p_fixed, rep_log = repair_invalid_polygon(
                p,
                reason=f"Ring {r.index} had invalid topology (self-intersection or duplicate boundary)",
                ring_index=r.index,
            )
            if rep_log is not None:
                class_res.repairs.append(rep_log)
            p = p_fixed
        if p is not None and not p.is_empty:
            poly_list.append(p)

    if not poly_list:
        return None, class_res

    # Single polygon case
    if len(poly_list) == 1:
        out_geom = poly_list[0]
        if out_geom.is_empty:
            return None, class_res
        return out_geom, class_res

    # Multi-subpath compound path
    if f_rule == FillRule.EVENODD:
        # Parity XOR across all subpaths
        fill_geom = poly_list[0]
        for p in poly_list[1:]:
            fill_geom = fill_geom.symmetric_difference(p)
        if not fill_geom.is_valid:
            fill_geom, rep_log = repair_invalid_polygon(
                fill_geom,
                reason="Evenodd symmetric difference produced self-touching boundaries",
            )
            if rep_log is not None:
                class_res.repairs.append(rep_log)
        if fill_geom.is_empty:
            return None, class_res
        return fill_geom, class_res

    else:
        # NONZERO Winding Rule Construction:
        # Group by outer roots (depth 0) and hierarchically punch holes / union same-oriented rings
        roots = [r for r in non_degen if r.nesting_depth == 0]
        if not roots:
            # Fallback if circular containment occurred
            roots = [min(non_degen, key=lambda r: -r.abs_area)]

        outer_parts = []
        for root in roots:
            root_poly = poly_list[non_degen.index(root)]
            direct_children = [r for r in non_degen if r.parent_index == root.index]

            holes = []
            same_direction_fillers = []

            for child in direct_children:
                child_poly = poly_list[non_degen.index(child)]
                if child.is_hole:
                    # Subtract hole
                    holes.append(child_poly)
                    # Check for islands inside this hole
                    islands = [r for r in non_degen if r.parent_index == child.index and not r.is_hole]
                    for isl in islands:
                        same_direction_fillers.append(poly_list[non_degen.index(isl)])
                else:
                    # Same orientation as parent: adds to winding, stays filled
                    same_direction_fillers.append(child_poly)

            # Punch holes
            if holes:
                holes_union = unary_union(holes)
                part = root_poly.difference(holes_union)
            else:
                part = root_poly

            # Re-add islands / fillers
            if same_direction_fillers:
                part = unary_union([part] + same_direction_fillers)

            if not part.is_empty:
                outer_parts.append(part)

        if not outer_parts:
            return None, class_res

        fill_geom = unary_union(outer_parts)
        if not fill_geom.is_valid:
            area_b = fill_geom.area
            fill_geom = make_valid(fill_geom)
            area_a = fill_geom.area
            class_res.repairs.append(GeometryRepairLog(
                repair_type="make_valid_nonzero",
                reason="Nonzero winding union produced multi-polygon contact edges",
                area_before=area_b,
                area_after=area_a,
                delta_area=area_a - area_b,
                scientific_warning=f"Nonzero geometry validated with make_valid (area delta: {area_a - area_b:.6f})",
            ))

        if fill_geom.is_empty:
            return None, class_res
        return fill_geom, class_res


@dataclass
class DualReferenceVerificationReport:
    """Comparison report between pure topological classifier and exact Shapely geometry."""
    fill_rule: FillRule
    topological_area: float
    shapely_area: float
    area_delta_abs: float
    area_delta_rel: float
    topological_holes_count: int
    shapely_holes_count: int
    topological_polygons_count: int
    shapely_polygons_count: int
    is_verified: bool
    repairs_count: int
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fill_rule": self.fill_rule.value,
            "topological_area": round(self.topological_area, 6),
            "shapely_area": round(self.shapely_area, 6),
            "area_delta_abs": round(self.area_delta_abs, 8),
            "area_delta_rel": round(self.area_delta_rel, 8),
            "topological_holes_count": self.topological_holes_count,
            "shapely_holes_count": self.shapely_holes_count,
            "topological_polygons_count": self.topological_polygons_count,
            "shapely_polygons_count": self.shapely_polygons_count,
            "is_verified": self.is_verified,
            "repairs_count": self.repairs_count,
            "warnings": list(self.warnings),
        }


def verify_fill_rule_dual_reference(
    subpaths: Sequence[Sequence[Tuple[float, float]]],
    fill_rule: FillRule | str = FillRule.NONZERO,
    area_tolerance_rel: float = 1e-5,
) -> Tuple[DualReferenceVerificationReport, RingClassificationResult, Optional[Any]]:
    """Compares independent topological ring/winding classifier with Shapely GEOS evaluation."""
    f_rule, _ = FillRule.from_str(fill_rule) if isinstance(fill_rule, str) else (fill_rule, None)
    shapely_geom, class_res = build_fill_geometry_with_semantics(subpaths, fill_rule=f_rule)

    top_area = class_res.total_analytic_area
    shp_area = float(shapely_geom.area) if shapely_geom is not None else 0.0

    area_delta_abs = abs(top_area - shp_area)
    ref_scale = max(abs(top_area), abs(shp_area), 1.0)
    area_delta_rel = area_delta_abs / ref_scale

    # Count Shapely outer polygons and interior holes
    shp_polys = 0
    shp_holes = 0
    if shapely_geom is not None and not shapely_geom.is_empty:
        if shapely_geom.geom_type == "Polygon":
            shp_polys = 1
            shp_holes = len(shapely_geom.interiors)
        elif shapely_geom.geom_type == "MultiPolygon":
            shp_polys = len(shapely_geom.geoms)
            shp_holes = sum(len(p.interiors) for p in shapely_geom.geoms)

    top_holes = class_res.hole_rings_count
    top_polys = class_res.outer_rings_count

    is_verified = (area_delta_rel <= area_tolerance_rel)

    report = DualReferenceVerificationReport(
        fill_rule=f_rule,
        topological_area=top_area,
        shapely_area=shp_area,
        area_delta_abs=area_delta_abs,
        area_delta_rel=area_delta_rel,
        topological_holes_count=top_holes,
        shapely_holes_count=shp_holes,
        topological_polygons_count=top_polys,
        shapely_polygons_count=shp_polys,
        is_verified=is_verified,
        repairs_count=len(class_res.repairs),
        warnings=list(class_res.warnings),
    )
    return report, class_res, shapely_geom
