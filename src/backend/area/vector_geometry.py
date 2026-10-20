"""RASH-HIT Vector Geometry & Adaptive Flattening Engine (1.0 Core).

Implements:
1. W3C SVG Stroke Semantics:
   - stroke-width, stroke-linecap (butt, round, square), stroke-linejoin (miter, round, bevel), stroke-miterlimit.
   - Zero-length segment behavior (butt -> empty, round -> circle, square -> square box).
   - Local-space stroke outline expansion & affine transform propagation.
2. W3C SVG Curve & Arc Adaptive Flattening:
   - Adaptive De Casteljau subdivision for Cubic (C, c, S, s) and Quadratic (Q, q, T, t) Bézier curves.
   - Adaptive Arc (A, a) subdivision via W3C F.6 endpoint-to-center parameterization.
   - Grid-aware FlatteningPolicy bound to finest cell dimensions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from shapely.geometry import (
    LineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely.ops import unary_union


# ============================================================================
# Stroke Styles & Enums
# ============================================================================

class StrokeLineCap(str, Enum):
    BUTT = "butt"
    ROUND = "round"
    SQUARE = "square"

    @classmethod
    def from_str(cls, val: Optional[str]) -> Tuple[StrokeLineCap, Optional[str]]:
        if not val:
            return cls.BUTT, None
        v = str(val).strip().lower()
        if v == "round":
            return cls.ROUND, None
        elif v == "square":
            return cls.SQUARE, None
        elif v == "butt":
            return cls.BUTT, None
        else:
            return cls.BUTT, f"Invalid stroke-linecap '{val}' defaulted to 'butt'."


class StrokeLineJoin(str, Enum):
    MITER = "miter"
    ROUND = "round"
    BEVEL = "bevel"

    @classmethod
    def from_str(cls, val: Optional[str]) -> Tuple[StrokeLineJoin, Optional[str]]:
        if not val:
            return cls.MITER, None
        v = str(val).strip().lower()
        if v == "round":
            return cls.ROUND, None
        elif v == "bevel":
            return cls.BEVEL, None
        elif v == "miter":
            return cls.MITER, None
        else:
            return cls.MITER, f"Invalid stroke-linejoin '{val}' defaulted to 'miter'."


@dataclass
class StrokeResolutionDiagnostics:
    """Audit diagnostics for resolved stroke properties."""
    winning_source: str                 # 'inline_style', 'author_stylesheet', 'presentation_attribute', 'inherited', 'initial_default'
    specificity: Tuple[int, int, int, int] = (0, 0, 0, 0)
    is_important: bool = False
    warning_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "winning_source": self.winning_source,
            "specificity": list(self.specificity),
            "is_important": self.is_important,
            "warning_codes": list(self.warning_codes),
        }


@dataclass
class StrokeStyle:
    """Complete representation of SVG stroke properties."""
    color: str = "none"
    width: float = 1.0
    linecap: StrokeLineCap = StrokeLineCap.BUTT
    linejoin: StrokeLineJoin = StrokeLineJoin.MITER
    miterlimit: float = 4.0
    dasharray: Optional[List[float]] = None
    dashoffset: float = 0.0
    vector_effect: str = "none"         # 'none' or 'non-scaling-stroke'
    diagnostics: Optional[StrokeResolutionDiagnostics] = None
    warnings: List[str] = field(default_factory=list)

    @property
    def has_stroke(self) -> bool:
        return self.color not in ("none", "transparent", "") and self.width > 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "color": self.color,
            "width": self.width,
            "linecap": self.linecap.value,
            "linejoin": self.linejoin.value,
            "miterlimit": self.miterlimit,
            "dasharray": self.dasharray,
            "dashoffset": self.dashoffset,
            "vector_effect": self.vector_effect,
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics else None,
            "warnings": list(self.warnings),
        }


# ============================================================================
# Adaptive Flattening Policy
# ============================================================================

@dataclass
class FlatteningPolicy:
    """Central policy contract for adaptive curve and arc segmentation."""
    policy_version: str = "1.0"
    tolerance_mode: str = "adaptive_grid"  # 'adaptive_grid' or 'fixed_absolute'
    absolute_tolerance: float = 0.05
    relative_tolerance: float = 1e-4
    max_recursion_depth: int = 12
    max_segments_per_curve: int = 512
    transform_scale_factor: float = 1.0
    requested_max_level: int = 10
    finest_cell_width: float = 0.0
    finest_cell_height: float = 0.0

    def effective_tolerance(self) -> float:
        """Computes effective geometric tolerance."""
        if self.tolerance_mode == "adaptive_grid" and (self.finest_cell_width > 0 or self.finest_cell_height > 0):
            min_dim = min(
                self.finest_cell_width if self.finest_cell_width > 0 else 1.0,
                self.finest_cell_height if self.finest_cell_height > 0 else 1.0,
            )
            # Safe fraction: 1/4th of finest grid cell width/height
            grid_tol = min_dim * 0.25
            return max(1e-5, min(self.absolute_tolerance, grid_tol))
        return max(1e-5, self.absolute_tolerance)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "tolerance_mode": self.tolerance_mode,
            "absolute_tolerance": self.absolute_tolerance,
            "effective_tolerance": self.effective_tolerance(),
            "relative_tolerance": self.relative_tolerance,
            "max_recursion_depth": self.max_recursion_depth,
            "max_segments_per_curve": self.max_segments_per_curve,
            "transform_scale_factor": self.transform_scale_factor,
            "requested_max_level": self.requested_max_level,
            "finest_cell_width": self.finest_cell_width,
            "finest_cell_height": self.finest_cell_height,
        }


# ============================================================================
# Adaptive Curve Flattening Algorithms
# ============================================================================

def _point_to_segment_distance(
    pt: Tuple[float, float],
    p0: Tuple[float, float],
    p1: Tuple[float, float],
) -> float:
    """Perpendicular distance from pt to line segment p0-p1."""
    x0, y0 = pt
    x1, y1 = p0
    x2, y2 = p1
    dx = x2 - x1
    dy = y2 - y1
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1e-15:
        return math.hypot(x0 - x1, y0 - y1)
    # Area of triangle * 2 / base
    return abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / math.sqrt(seg_len_sq)


def flatten_cubic_bezier(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    policy: Optional[FlatteningPolicy] = None,
) -> List[Tuple[float, float]]:
    """Adaptive recursive De Casteljau subdivision for cubic Bézier curves.

    Guarantees:
    - Distance of control points to chord line <= tolerance.
    - Bounded by max_recursion_depth and max_segments_per_curve.
    - Returns end points list (excluding p0, ending with p3).
    """
    pol = policy or FlatteningPolicy()
    tol = pol.effective_tolerance()
    max_depth = pol.max_recursion_depth
    out_points: List[Tuple[float, float]] = []

    def _subdivide(
        a: Tuple[float, float],
        b: Tuple[float, float],
        c: Tuple[float, float],
        d: Tuple[float, float],
        depth: int,
    ):
        if len(out_points) >= pol.max_segments_per_curve:
            out_points.append(d)
            return

        # Flatness test: check distances of control points b and c from chord a-d
        d1 = _point_to_segment_distance(b, a, d)
        d2 = _point_to_segment_distance(c, a, d)

        if (d1 <= tol and d2 <= tol) or depth >= max_depth:
            out_points.append(d)
            return

        # De Casteljau split at t=0.5
        ab = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
        bc = ((b[0] + c[0]) * 0.5, (b[1] + c[1]) * 0.5)
        cd = ((c[0] + d[0]) * 0.5, (c[1] + d[1]) * 0.5)

        abbc = ((ab[0] + bc[0]) * 0.5, (ab[1] + bc[1]) * 0.5)
        bccd = ((bc[0] + cd[0]) * 0.5, (bc[1] + cd[1]) * 0.5)

        mid = ((abbc[0] + bccd[0]) * 0.5, (abbc[1] + bccd[1]) * 0.5)

        _subdivide(a, ab, abbc, mid, depth + 1)
        _subdivide(mid, bccd, cd, d, depth + 1)

    _subdivide(p0, p1, p2, p3, 0)
    return out_points


def flatten_quadratic_bezier(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    policy: Optional[FlatteningPolicy] = None,
) -> List[Tuple[float, float]]:
    """Adaptive recursive De Casteljau subdivision for quadratic Bézier curves."""
    pol = policy or FlatteningPolicy()
    tol = pol.effective_tolerance()
    max_depth = pol.max_recursion_depth
    out_points: List[Tuple[float, float]] = []

    def _subdivide(
        a: Tuple[float, float],
        b: Tuple[float, float],
        c: Tuple[float, float],
        depth: int,
    ):
        if len(out_points) >= pol.max_segments_per_curve:
            out_points.append(c)
            return

        # Flatness test: distance of control point b from chord a-c
        d1 = _point_to_segment_distance(b, a, c)

        if d1 <= tol or depth >= max_depth:
            out_points.append(c)
            return

        # De Casteljau split at t=0.5
        ab = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)
        bc = ((b[0] + c[0]) * 0.5, (b[1] + c[1]) * 0.5)
        mid = ((ab[0] + bc[0]) * 0.5, (ab[1] + bc[1]) * 0.5)

        _subdivide(a, ab, mid, depth + 1)
        _subdivide(mid, bc, c, depth + 1)

    _subdivide(p0, p1, p2, 0)
    return out_points


def flatten_elliptical_arc(
    p0: Tuple[float, float],
    rx: float,
    ry: float,
    phi_deg: float,
    large_arc: bool,
    sweep: bool,
    p1: Tuple[float, float],
    policy: Optional[FlatteningPolicy] = None,
) -> List[Tuple[float, float]]:
    """Adaptive chord-error-bounded elliptical arc flattening (W3C SVG Appendix F.6)."""
    pol = policy or FlatteningPolicy()
    tol = pol.effective_tolerance()

    x1, y1 = p0
    x2, y2 = p1

    if abs(x1 - x2) < 1e-12 and abs(y1 - y2) < 1e-12:
        return []

    rx = abs(rx)
    ry = abs(ry)
    if rx < 1e-12 or ry < 1e-12:
        return [(x2, y2)]

    phi = math.radians(phi_deg % 360.0)
    cos_phi = math.cos(phi)
    sin_phi = math.sin(phi)

    # Step 1: Compute (x1', y1')
    dx = (x1 - x2) / 2.0
    dy = (y1 - y2) / 2.0
    x1p = cos_phi * dx + sin_phi * dy
    y1p = -sin_phi * dx + cos_phi * dy

    # Step 2: Radius check & correction (F.6.2)
    prx = rx * rx
    pry = ry * ry
    px1p = x1p * x1p
    py1p = y1p * y1p

    radii_check = px1p / prx + py1p / pry
    if radii_check > 1.0:
        scale_r = math.sqrt(radii_check)
        rx *= scale_r
        ry *= scale_r
        prx = rx * rx
        pry = ry * ry

    # Step 3: Compute center (cx', cy') (F.6.5)
    sign = -1.0 if large_arc == sweep else 1.0
    num = max(0.0, prx * pry - prx * py1p - pry * px1p)
    den = prx * py1p + pry * px1p
    coef = sign * math.sqrt(num / den) if den > 0 else 0.0

    cxp = coef * ((rx * y1p) / ry)
    cyp = coef * (-(ry * x1p) / rx)

    cx = cos_phi * cxp - sin_phi * cyp + (x1 + x2) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (y1 + y2) / 2.0

    # Step 4: Compute theta1 and delta_theta (F.6.5)
    def vector_angle(u: Tuple[float, float], v: Tuple[float, float]) -> float:
        dot = u[0] * v[0] + u[1] * v[1]
        len_uv = math.hypot(u[0], u[1]) * math.hypot(v[0], v[1])
        if len_uv == 0:
            return 0.0
        val = max(-1.0, min(1.0, dot / len_uv))
        ang = math.acos(val)
        if (u[0] * v[1] - u[1] * v[0]) < 0:
            ang = -ang
        return ang

    v1 = ((x1p - cxp) / rx, (y1p - cyp) / ry)
    v2 = ((-x1p - cxp) / rx, (-y1p - cyp) / ry)

    theta1 = vector_angle((1.0, 0.0), v1)
    d_theta = vector_angle(v1, v2)

    if not sweep and d_theta > 0:
        d_theta -= 2 * math.pi
    elif sweep and d_theta < 0:
        d_theta += 2 * math.pi

    # Adaptive Step Count: chord error e = r * (1 - cos(d_th / 2)) <= tol
    max_r = max(rx, ry)
    if max_r > 0:
        # 1 - cos(d_th/2) <= tol / max_r => cos(d_th/2) >= 1 - tol/max_r
        arg = max(-1.0, min(1.0, 1.0 - tol / max_r))
        max_d_theta_step = 2.0 * math.acos(arg)
        max_d_theta_step = max(math.radians(1.0), max_d_theta_step)  # at least 1 degree
        num_steps = max(4, int(math.ceil(abs(d_theta) / max_d_theta_step)))
    else:
        num_steps = 4

    num_steps = min(pol.max_segments_per_curve, max(4, num_steps))

    pts: List[Tuple[float, float]] = []
    for i in range(1, num_steps):
        th = theta1 + (i / num_steps) * d_theta
        cos_th = math.cos(th)
        sin_th = math.sin(th)
        x = cos_phi * (rx * cos_th) - sin_phi * (ry * sin_th) + cx
        y = sin_phi * (rx * cos_th) + cos_phi * (ry * sin_th) + cy
        pts.append((x, y))

    # Exact final endpoint
    pts.append((x2, y2))
    return pts


# ============================================================================
# Stroke Outline Expansion & Geometry Builder
# ============================================================================

def expand_stroke_to_polygon(
    subpaths: Sequence[Sequence[Tuple[float, float]]],
    style: StrokeStyle,
    transform_matrix: Optional[np.ndarray] = None,
) -> Optional[Union[Polygon, MultiPolygon]]:
    """Expands subpath stroke centerlines into 2D polygon representations conforming to SVG stroke semantics.

    Cap Styles (W3C SVG):
    - BUTT: Line ends strictly at end vertices with no extension.
    - ROUND: Semicircle of radius width/2 at each open subpath endpoint.
    - SQUARE: Square extension of width/2 past each endpoint.
    - Closed subpaths: Endpoints connect continuously; no start/end caps generated.

    Join Styles (W3C SVG):
    - MITER: Extends outer edges until intersection. If miter length exceeds miterlimit, falls back to bevel.
    - ROUND: Circular arc of radius width/2 at corners.
    - BEVEL: Flat edge connecting offset corner points.

    Zero-Length Subpaths (W3C SVG §11.4):
    - BUTT: Produces no geometry (0 area).
    - ROUND: Produces a circle with diameter equal to stroke-width.
    - SQUARE: Produces a square with side length equal to stroke-width.

    Transform Propagation:
    - Stroke expansion is performed in object local coordinates, and the resulting 2D
      polygonal envelope is transformed via transform_matrix, correctly yielding
      elliptical stroke widths under non-uniform scaling.
    """
    if not style.has_stroke or not subpaths:
        return None

    w = float(style.width)
    half_w = w * 0.5

    # Shapely cap styles: 1 = round, 2 = flat (butt), 3 = square
    cap_style_code = 2  # Butt
    if style.linecap == StrokeLineCap.ROUND:
        cap_style_code = 1
    elif style.linecap == StrokeLineCap.SQUARE:
        cap_style_code = 3

    # Shapely join styles: 1 = round, 2 = mitre, 3 = bevel
    join_style_code = 2  # Miter
    if style.linejoin == StrokeLineJoin.ROUND:
        join_style_code = 1
    elif style.linejoin == StrokeLineJoin.BEVEL:
        join_style_code = 3

    mitre_lim = max(1.0, float(style.miterlimit))

    expanded_parts: List[Polygon] = []

    for raw_pts in subpaths:
        pts = list(raw_pts)
        if not pts:
            continue

        # Check for zero-length subpath (single point or all identical vertices)
        is_zero_length = len(pts) == 1 or all(
            abs(p[0] - pts[0][0]) < 1e-12 and abs(p[1] - pts[0][1]) < 1e-12 for p in pts
        )

        if is_zero_length:
            x0, y0 = pts[0]
            if style.linecap == StrokeLineCap.ROUND:
                # Circle of radius half_w centered at (x0, y0)
                circle_poly = Point(x0, y0).buffer(half_w, quad_segs=16)
                if not circle_poly.is_empty:
                    expanded_parts.append(circle_poly)
            elif style.linecap == StrokeLineCap.SQUARE:
                # Square of side w centered at (x0, y0)
                square_poly = box(x0 - half_w, y0 - half_w, x0 + half_w, y0 + half_w)
                if not square_poly.is_empty:
                    expanded_parts.append(square_poly)
            # BUTT cap on zero-length segment produces no geometry
            continue

        # Non-zero length line/polyline
        is_closed = len(pts) >= 4 and abs(pts[0][0] - pts[-1][0]) < 1e-12 and abs(pts[0][1] - pts[-1][1]) < 1e-12

        line = LineString(pts)
        if line.is_empty or line.length < 1e-12:
            continue

        # Expand line with buffer
        # For closed path, use flat cap to let the loop close seamlessly
        actual_cap = 2 if is_closed else cap_style_code
        buf = line.buffer(
            half_w,
            cap_style=actual_cap,
            join_style=join_style_code,
            mitre_limit=mitre_lim,
            quad_segs=16,
        )

        if not buf.is_empty:
            if buf.geom_type == "Polygon":
                expanded_parts.append(buf)
            elif buf.geom_type == "MultiPolygon":
                expanded_parts.extend(buf.geoms)

    if not expanded_parts:
        return None

    # Union all stroke parts in local coordinate space
    stroke_union = unary_union(expanded_parts)
    if stroke_union.is_empty:
        return None

    # Apply 2D affine transform matrix if provided
    if transform_matrix is not None and not np.allclose(transform_matrix, np.eye(3)):
        # Transform Shapely geometry
        from shapely.affinity import affine_transform
        # 3x3 Matrix:
        # [m00 m01 m02]
        # [m10 m11 m12]
        # [ 0   0   1 ]
        # Shapely affine_transform takes [a, b, d, e, xoff, yoff] where x' = ax + by + xoff, y' = dx + ey + yoff
        a = transform_matrix[0, 0]
        b = transform_matrix[0, 1]
        xoff = transform_matrix[0, 2]
        d = transform_matrix[1, 0]
        e = transform_matrix[1, 1]
        yoff = transform_matrix[1, 2]
        stroke_union = affine_transform(stroke_union, [a, b, d, e, xoff, yoff])

    if stroke_union.is_empty:
        return None

    return stroke_union
