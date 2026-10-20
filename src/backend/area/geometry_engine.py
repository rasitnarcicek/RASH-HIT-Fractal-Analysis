# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek

"""
geometry_engine.py — SVG Geometry Parser, Curve Flattening & 2D Matrix Transform Engine.
Parses path data (M, L, H, V, C, S, Q, T, A, Z), rect, circle, ellipse, line, polyline, polygon.
Applies 2D affine transformation matrices and builds Shapely geometries for exact analysis.
"""

from __future__ import annotations
import math
import re
from typing import List, Tuple, Optional, Any
import numpy as np
from shapely.geometry import LineString
from shapely.ops import unary_union

from .fill_rule_semantics import (
    RingClassificationResult,
    build_fill_geometry_with_semantics,
    compute_signed_ring_area,
)
from .svg_loader import SVGNode
from .vector_geometry import (
    FlatteningPolicy,
    StrokeStyle,
    expand_stroke_to_polygon,
    flatten_cubic_bezier,
    flatten_elliptical_arc,
    flatten_quadratic_bezier,
)


# ============================================================================
# 2D Affine Transform Matrix Helper
# ============================================================================

def parse_transform_string(transform_str: str) -> np.ndarray:
    """
    Parses SVG transform attribute string into a 3x3 homogeneous transformation matrix.
    Supports matrix, translate, scale, rotate, skewX, skewY.
    """
    M = np.eye(3, dtype=np.float64)
    if not transform_str:
        return M

    commands = re.findall(r'([a-zA-Z]+)\s*\(([^)]+)\)', transform_str)
    for cmd, args_str in commands:
        cmd = cmd.strip().lower()
        try:
            args = [float(p) for p in re.split(r'[\s,]+', args_str.strip()) if p]
            if not all(math.isfinite(a) for a in args):
                continue
        except Exception:
            continue

        T = np.eye(3, dtype=np.float64)
        try:
            if cmd == 'matrix' and len(args) == 6:
                a, b, c, d, e, f = args
                T = np.array([[a, c, e],
                              [b, d, f],
                              [0, 0, 1]], dtype=np.float64)
            elif cmd == 'translate' and len(args) >= 1:
                tx = args[0]
                ty = args[1] if len(args) > 1 else 0.0
                T = np.array([[1, 0, tx],
                              [0, 1, ty],
                              [0, 0, 1]], dtype=np.float64)
            elif cmd == 'scale' and len(args) >= 1:
                sx = args[0]
                sy = args[1] if len(args) > 1 else sx
                T = np.array([[sx, 0, 0],
                              [0, sy, 0],
                              [0, 0, 1]], dtype=np.float64)
            elif cmd == 'rotate' and len(args) >= 1:
                angle = math.radians(args[0])
                cos_a, sin_a = math.cos(angle), math.sin(angle)
                if len(args) >= 3:
                    cx, cy = args[1], args[2]
                    T_trans1 = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1]], dtype=np.float64)
                    T_rot = np.array([[cos_a, -sin_a, 0], [sin_a, cos_a, 0], [0, 0, 1]], dtype=np.float64)
                    T_trans2 = np.array([[1, 0, cx], [0, 1, cy], [0, 0, 1]], dtype=np.float64)
                    T = T_trans2 @ T_rot @ T_trans1
                else:
                    T = np.array([[cos_a, -sin_a, 0], [sin_a, cos_a, 0], [0, 0, 1]], dtype=np.float64)
            elif cmd == 'skewx' and len(args) >= 1:
                tan_a = math.tan(math.radians(args[0]))
                T = np.array([[1, tan_a, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
            elif cmd == 'skewy' and len(args) >= 1:
                tan_a = math.tan(math.radians(args[0]))
                T = np.array([[1, 0, 0], [tan_a, 1, 0], [0, 0, 1]], dtype=np.float64)

            M = M @ T
        except Exception:
            continue

    return M


def transform_points(points: List[Tuple[float, float]], M: np.ndarray) -> List[Tuple[float, float]]:
    """Applies 3x3 transformation matrix M to a list of (x, y) coordinates."""
    if len(points) == 0:
        return []
    if not np.all(np.isfinite(M)):
        return []
    pts_arr = np.column_stack([np.array(points), np.ones(len(points))])  # (N, 3)
    transformed = (M @ pts_arr.T).T  # (N, 3)
    out = []
    for row in transformed:
        if math.isfinite(row[0]) and math.isfinite(row[1]):
            out.append((float(row[0]), float(row[1])))
    return out


# ============================================================================
# Path Parser
# ============================================================================

def parse_svg_path(
    d_str: str,
    tolerance_steps: int = 16,
    policy: Optional[FlatteningPolicy] = None,
) -> List[List[Tuple[float, float]]]:
    """
    Parses SVG path d attribute string into subpaths (lists of 2D points).
    Handles M, L, H, V, C, S, Q, T, A, Z (both uppercase absolute and lowercase relative).
    Uses adaptive FlatteningPolicy for De Casteljau subdivision of Bézier curves and elliptical arcs.
    """
    if not d_str:
        return []

    # If policy is not given, instantiate with sensible tolerance
    flattener_policy = policy or FlatteningPolicy(
        max_segments_per_curve=max(16, tolerance_steps * 2),
        absolute_tolerance=0.05,
    )

    # Tokenize path commands and numbers
    tokens = re.findall(r'([a-zA-Z])|([-+]?(?:\d+\.\d+|\d+\.|\.\d+|\d+)(?:[eE][-+]?\d+)?)', d_str)
    raw_list = []
    for cmd, num in tokens:
        if cmd:
            raw_list.append(cmd)
        elif num:
            raw_list.append(float(num))

    subpaths: List[List[Tuple[float, float]]] = []
    current_path: List[Tuple[float, float]] = []

    curr_x, curr_y = 0.0, 0.0
    start_x, start_y = 0.0, 0.0
    last_cubic_cp: Optional[Tuple[float, float]] = None
    last_quad_cp: Optional[Tuple[float, float]] = None

    valid_commands = {'M', 'L', 'H', 'V', 'C', 'S', 'Q', 'T', 'A', 'Z'}
    if not raw_list:
        return []

    if not isinstance(raw_list[0], str) or raw_list[0].upper() not in valid_commands:
        raise ValueError(f"Malformed SVG path: must start with valid command (got '{raw_list[0]}')")

    idx = 0
    num_tokens = len(raw_list)

    cmd = ''
    while idx < num_tokens:
        tok = raw_list[idx]
        if isinstance(tok, str):
            if tok.upper() not in valid_commands:
                raise ValueError(f"Unknown or unsupported SVG path command: '{tok}'")
            cmd = tok
            idx += 1

        is_rel = cmd.islower()
        c = cmd.upper()

        def get_args(count: int) -> List[float]:
            nonlocal idx
            if idx + count > num_tokens:
                raise ValueError(f"Malformed SVG path: command '{cmd}' expects {count} parameters, but only {num_tokens - idx} remain")
            args = []
            for k in range(count):
                val = raw_list[idx + k]
                if not isinstance(val, (int, float)):
                    raise ValueError(f"Malformed SVG path: command '{cmd}' expects numeric parameter, got '{val}'")
                args.append(float(val))
            idx += count
            return args

        if c == 'M':
            a = get_args(2)
            x = a[0] + (curr_x if is_rel else 0.0)
            y = a[1] + (curr_y if is_rel else 0.0)
            curr_x, curr_y = x, y
            start_x, start_y = x, y

            if current_path:
                subpaths.append(current_path)
            current_path = [(curr_x, curr_y)]
            cmd = 'l' if is_rel else 'L'

        elif c == 'L':
            a = get_args(2)
            x = a[0] + (curr_x if is_rel else 0.0)
            y = a[1] + (curr_y if is_rel else 0.0)
            curr_x, curr_y = x, y
            current_path.append((curr_x, curr_y))

        elif c == 'H':
            a = get_args(1)
            x = a[0] + (curr_x if is_rel else 0.0)
            curr_x = x
            current_path.append((curr_x, curr_y))

        elif c == 'V':
            a = get_args(1)
            y = a[0] + (curr_y if is_rel else 0.0)
            curr_y = y
            current_path.append((curr_x, curr_y))

        elif c == 'C':
            a = get_args(6)
            x1 = a[0] + (curr_x if is_rel else 0.0)
            y1 = a[1] + (curr_y if is_rel else 0.0)
            x2 = a[2] + (curr_x if is_rel else 0.0)
            y2 = a[3] + (curr_y if is_rel else 0.0)
            x = a[4] + (curr_x if is_rel else 0.0)
            y = a[5] + (curr_y if is_rel else 0.0)

            pts = flatten_cubic_bezier((curr_x, curr_y), (x1, y1), (x2, y2), (x, y), policy=flattener_policy)
            current_path.extend(pts)
            last_cubic_cp = (x2, y2)
            curr_x, curr_y = x, y

        elif c == 'S':
            if last_cubic_cp:
                x1 = 2 * curr_x - last_cubic_cp[0]
                y1 = 2 * curr_y - last_cubic_cp[1]
            else:
                x1, y1 = curr_x, curr_y

            a = get_args(4)
            x2 = a[0] + (curr_x if is_rel else 0.0)
            y2 = a[1] + (curr_y if is_rel else 0.0)
            x = a[2] + (curr_x if is_rel else 0.0)
            y = a[3] + (curr_y if is_rel else 0.0)

            pts = flatten_cubic_bezier((curr_x, curr_y), (x1, y1), (x2, y2), (x, y), policy=flattener_policy)
            current_path.extend(pts)
            last_cubic_cp = (x2, y2)
            curr_x, curr_y = x, y

        elif c == 'Q':
            a = get_args(4)
            x1 = a[0] + (curr_x if is_rel else 0.0)
            y1 = a[1] + (curr_y if is_rel else 0.0)
            x = a[2] + (curr_x if is_rel else 0.0)
            y = a[3] + (curr_y if is_rel else 0.0)

            pts = flatten_quadratic_bezier((curr_x, curr_y), (x1, y1), (x, y), policy=flattener_policy)
            current_path.extend(pts)
            last_quad_cp = (x1, y1)
            curr_x, curr_y = x, y

        elif c == 'T':
            if last_quad_cp:
                x1 = 2 * curr_x - last_quad_cp[0]
                y1 = 2 * curr_y - last_quad_cp[1]
            else:
                x1, y1 = curr_x, curr_y

            a = get_args(2)
            x = a[0] + (curr_x if is_rel else 0.0)
            y = a[1] + (curr_y if is_rel else 0.0)

            pts = flatten_quadratic_bezier((curr_x, curr_y), (x1, y1), (x, y), policy=flattener_policy)
            current_path.extend(pts)
            last_quad_cp = (x1, y1)
            curr_x, curr_y = x, y

        elif c == 'A':
            a = get_args(7)
            rx, ry, phi = a[0], a[1], a[2]
            large_arc = bool(a[3])
            sweep = bool(a[4])
            x = a[5] + (curr_x if is_rel else 0.0)
            y = a[6] + (curr_y if is_rel else 0.0)

            pts = flatten_elliptical_arc((curr_x, curr_y), rx, ry, phi, large_arc, sweep, (x, y), policy=flattener_policy)
            current_path.extend(pts)
            curr_x, curr_y = x, y

        elif c == 'Z':
            curr_x, curr_y = start_x, start_y
            if current_path and current_path[0] != current_path[-1]:
                current_path.append((start_x, start_y))

        if c not in ('C', 'S'):
            last_cubic_cp = None
        if c not in ('Q', 'T'):
            last_quad_cp = None

    if current_path:
        subpaths.append(current_path)

    return subpaths


def _ring_signed_area(pts: List[Tuple[float, float]]) -> float:
    """Signed shoelace area of a closed ring (original point order)."""
    return compute_signed_ring_area(pts)


# ============================================================================
# Element Shape Parser & Geometry Factory
# ============================================================================

class ParsedGeometry:
    """Container for a resolved Shapely geometry object (Fill area or Stroke line/polygon)."""
    def __init__(
        self,
        geom_type: str,  # 'fill' or 'stroke'
        shapely_obj: Any,
        stroke_width: float = 0.0,
        tag: str = 'path',
        fill_rule: str = 'nonzero',
        classification_result: Optional[RingClassificationResult] = None,
        diagnostics: Optional[Any] = None,
        stroke_style: Optional[StrokeStyle] = None,
    ):
        self.geom_type = geom_type
        self.shapely_obj = shapely_obj
        self.stroke_width = stroke_width
        self.tag = tag
        self.fill_rule = fill_rule
        self.classification_result = classification_result
        self.diagnostics = diagnostics
        self.stroke_style = stroke_style
        self.bounds = shapely_obj.bounds if shapely_obj and not shapely_obj.is_empty else (0, 0, 0, 0)

    @property
    def is_fill(self) -> bool:
        """Returns True if geometry represents a filled area."""
        return self.geom_type == 'fill'

    @property
    def is_stroke(self) -> bool:
        """Returns True if geometry represents a stroked line/boundary."""
        return self.geom_type == 'stroke'


def extract_node_geometries(
    node: SVGNode,
    transform_stack: List[str],
    tolerance: str = 'high',
    policy: Optional[FlatteningPolicy] = None,
    extract_white_fill: bool = False,
) -> List[ParsedGeometry]:
    """
    Parses an SVGNode into one or more transformed ParsedGeometry objects (fill & stroke).
    """
    num_steps = 24 if tolerance == 'high' else (12 if tolerance == 'medium' else 6)
    flattener_policy = policy or FlatteningPolicy(
        absolute_tolerance=0.02 if tolerance == 'high' else (0.05 if tolerance == 'medium' else 0.1)
    )

    # Build cumulative transform matrix
    M = np.eye(3, dtype=np.float64)
    for tf_str in transform_stack:
        M = M @ parse_transform_string(tf_str)

    subpaths: List[List[Tuple[float, float]]] = []

    tag = node.tag
    attr = node.attribs

    if tag == 'path':
        d = attr.get('d', '')
        subpaths = parse_svg_path(d, tolerance_steps=num_steps, policy=flattener_policy)

    elif tag == 'rect':
        x = float(attr.get('x', 0))
        y = float(attr.get('y', 0))
        w = float(attr.get('width', 0))
        h = float(attr.get('height', 0))
        if w > 0 and h > 0:
            subpaths = [[(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]]

    elif tag == 'circle':
        cx = float(attr.get('cx', 0))
        cy = float(attr.get('cy', 0))
        r = float(attr.get('r', 0))
        if r > 0:
            pts = []
            for i in range(num_steps + 1):
                ang = (i / num_steps) * 2 * math.pi
                pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
            subpaths = [pts]

    elif tag == 'ellipse':
        cx = float(attr.get('cx', 0))
        cy = float(attr.get('cy', 0))
        rx = float(attr.get('rx', 0))
        ry = float(attr.get('ry', 0))
        if rx > 0 and ry > 0:
            pts = []
            for i in range(num_steps + 1):
                ang = (i / num_steps) * 2 * math.pi
                pts.append((cx + rx * math.cos(ang), cy + ry * math.sin(ang)))
            subpaths = [pts]

    elif tag == 'line':
        x1 = float(attr.get('x1', 0))
        y1 = float(attr.get('y1', 0))
        x2 = float(attr.get('x2', 0))
        y2 = float(attr.get('y2', 0))
        subpaths = [[(x1, y1), (x2, y2)]]

    elif tag in ('polyline', 'polygon'):
        pts_str = attr.get('points', '')
        raw_num = [float(p) for p in re.split(r'[\s,]+', pts_str.strip()) if p]
        pts = [(raw_num[i], raw_num[i+1]) for i in range(0, len(raw_num)-1, 2)]
        if tag == 'polygon' and pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        if len(pts) >= 1:
            subpaths = [pts]

    geoms: List[ParsedGeometry] = []
    if not subpaths:
        return geoms

    # Transform all subpaths to world coordinates
    transformed_subpaths = [transform_points(pts, M) for pts in subpaths if len(pts) >= 2]

    # Calculate effective stroke width transformed scale factor
    det_m = abs(M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0])
    scale_factor = math.sqrt(det_m) if det_m > 0 else 1.0
    effective_stroke_width = node.stroke_width * scale_factor

    if extract_white_fill:
        if getattr(node, "is_white_fill", False):
            fill_rule = getattr(node, "fill_rule", "nonzero")
            fill_obj, class_res = build_fill_geometry_with_semantics(transformed_subpaths, fill_rule=fill_rule)
            if fill_obj is not None and not fill_obj.is_empty:
                geoms.append(ParsedGeometry(
                    geom_type='white_knockout',
                    shapely_obj=fill_obj,
                    tag=tag,
                    fill_rule=fill_rule,
                    classification_result=class_res,
                    diagnostics=getattr(node, "fill_rule_diagnostics", None),
                ))
        return geoms

    # Build Fill Geometry (winding-aware evenodd/nonzero compound-path fill).
    if node.has_fill:
        fill_rule = getattr(node, "fill_rule", "nonzero")
        fill_obj, class_res = build_fill_geometry_with_semantics(transformed_subpaths, fill_rule=fill_rule)
        if fill_obj is not None and not fill_obj.is_empty:
            geoms.append(ParsedGeometry(
                geom_type='fill',
                shapely_obj=fill_obj,
                tag=tag,
                fill_rule=fill_rule,
                classification_result=class_res,
                diagnostics=getattr(node, "fill_rule_diagnostics", None),
            ))

    # Build Stroke Geometry
    if node.has_stroke:
        stroke_st = getattr(node, "stroke_style", None)
        stroke_poly = None
        if stroke_st:
            stroke_poly = expand_stroke_to_polygon(subpaths, stroke_st, transform_matrix=M)

        if stroke_poly is not None and not stroke_poly.is_empty:
            geoms.append(ParsedGeometry(
                geom_type='stroke',
                shapely_obj=stroke_poly,
                stroke_width=effective_stroke_width,
                tag=tag,
                stroke_style=stroke_st,
            ))
        else:
            lines = []
            for pts in transformed_subpaths:
                if len(pts) >= 2:
                    line = LineString(pts)
                    if not line.is_empty:
                        lines.append(line)
            if lines:
                stroke_obj = unary_union(lines)
                geoms.append(ParsedGeometry(
                    geom_type='stroke',
                    shapely_obj=stroke_obj,
                    stroke_width=effective_stroke_width,
                    tag=tag,
                    stroke_style=stroke_st,
                ))

    return geoms
