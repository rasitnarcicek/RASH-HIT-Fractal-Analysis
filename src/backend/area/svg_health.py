# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""
svg_health.py - Pre-analysis diagnostic inspector for SVG files.
Evaluates file integrity, XML structure, viewBox, geometry elements, invisible elements,
base64 images, transforms, and coordinate bounds.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SVGHealthResult:
    is_valid_xml: bool = False
    file_size_bytes: int = 0
    viewbox: Optional[Tuple[float, float, float, float]] = None
    viewbox_str: str = "Missing"
    width: Optional[float] = None
    height: Optional[float] = None
    element_counts: Dict[str, int] = field(default_factory=dict)
    total_shape_elements: int = 0
    has_invisible_elements: bool = False
    invisible_count: int = 0
    has_bitmap_images: bool = False
    bitmap_count: int = 0
    has_transforms: bool = False
    transform_count: int = 0
    is_empty: bool = False
    suitability: str = "Unsuitable"  # "High", "Moderate", "Unsuitable"
    suitability_score: float = 0.0  # 0.0 to 100.0
    # RASH-HIT Fractal Analiz Engine (Realtime Metrics): full inspection duration in milliseconds.
    health_ms: float = 0.0
    diagnostic_messages: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid_xml": self.is_valid_xml,
            "file_size_bytes": self.file_size_bytes,
            "viewbox": self.viewbox_str,
            "width": self.width,
            "height": self.height,
            "element_counts": self.element_counts,
            "total_shape_elements": self.total_shape_elements,
            "has_invisible_elements": self.has_invisible_elements,
            "invisible_count": self.invisible_count,
            "has_bitmap_images": self.has_bitmap_images,
            "bitmap_count": self.bitmap_count,
            "has_transforms": self.has_transforms,
            "transform_count": self.transform_count,
            "is_empty": self.is_empty,
            "suitability": self.suitability,
            "suitability_score": round(self.suitability_score, 1),
            "health_ms": round(self.health_ms, 3),
            "diagnostic_messages": self.diagnostic_messages,
            "warnings": self.warnings,
            "errors": self.errors,
        }


def inspect_svg_health(file_path: Path) -> SVGHealthResult:
    """Inspects an SVG file for fractal analysis readiness and health metrics.

    RASH-HIT Fractal Analiz Engine (Realtime Metrics): the full inspection duration is measured and
    reported as ``health_ms`` on the result (and in ``to_dict()``) so the SVG
    health step's cost is visible end-to-end in the pipeline.
    """
    _t0 = time.perf_counter()
    result = _inspect_svg_health_inner(file_path)
    result.health_ms = round((time.perf_counter() - _t0) * 1000.0, 3)
    return result


def _inspect_svg_health_inner(file_path: Path) -> SVGHealthResult:
    """Core SVG inspection logic (no timing); timed by ``inspect_svg_health``."""
    result = SVGHealthResult()

    if not file_path.exists() or not file_path.is_file():
        result.errors.append(f"File not found or unreadable: {file_path}")
        result.diagnostic_messages.append("File not found or unreadable.")
        result.suitability = "Unsuitable"
        return result

    result.file_size_bytes = file_path.stat().st_size
    if result.file_size_bytes == 0:
        result.errors.append("File is empty (0 bytes).")
        result.diagnostic_messages.append("File is empty (0 bytes).")
        result.is_empty = True
        result.suitability = "Unsuitable"
        return result

    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        result.errors.append(f"Failed to read text: {e}")
        result.diagnostic_messages.append(f"Read error: {e}")
        result.suitability = "Unsuitable"
        return result

    # Check basic XML structure
    try:
        root = ET.fromstring(content)
        result.is_valid_xml = True
    except ET.ParseError as pe:
        result.errors.append(f"XML parse error: {pe}")
        result.diagnostic_messages.append(f"Invalid XML format: {pe}")
        result.suitability = "Unsuitable"
        return result

    # Check root SVG tag
    tag_clean = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if tag_clean.lower() != "svg":
        result.errors.append(f"Root tag is not <svg> (found <{tag_clean}>).")
        result.diagnostic_messages.append(f"Root tag is not <svg>: <{tag_clean}>")
        result.suitability = "Unsuitable"
        return result

    # Extract viewBox
    vb_attr = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if vb_attr:
        parts = [p.strip() for p in re.split(r"[\s,]+", vb_attr.strip()) if p.strip()]
        if len(parts) == 4:
            try:
                min_x, min_y, w, h = (float(p) for p in parts)
                result.viewbox = (min_x, min_y, w, h)
                result.viewbox_str = f"{min_x} {min_y} {w} {h}"
            except ValueError:
                result.warnings.append("viewBox attribute exists but has invalid numbers.")
                result.diagnostic_messages.append("viewBox numbers are invalid.")

    # Extract width/height
    w_attr = root.attrib.get("width")
    h_attr = root.attrib.get("height")
    if w_attr:
        try:
            result.width = float(re.sub(r"[^\d.]", "", w_attr))
        except ValueError:
            pass
    if h_attr:
        try:
            result.height = float(re.sub(r"[^\d.]", "", h_attr))
        except ValueError:
            pass

    if not result.viewbox and (not result.width or not result.height):
        result.warnings.append("No valid viewBox or width/height provided.")
        result.diagnostic_messages.append("Warning: viewBox or width/height not found.")

    # Element counts and shape discovery
    target_shapes = {"path", "polygon", "polyline", "line", "rect", "circle", "ellipse"}
    counts: Dict[str, int] = {}
    invisible_cnt = 0
    bitmap_cnt = 0
    transform_cnt = 0

    from .svg_loader import is_white_color

    for elem in root.iter():
        elem_tag = elem.tag.split("}")[-1].lower() if "}" in elem.tag else elem.tag.lower()

        if elem_tag == "image":
            bitmap_cnt += 1

        # Check invisible style attributes
        style = elem.attrib.get("style", "")
        display = elem.attrib.get("display") or ""
        visibility = elem.attrib.get("visibility") or ""
        opacity = elem.attrib.get("opacity") or ""

        is_inv = False
        if "display:none" in style.replace(" ", "") or display == "none":
            is_inv = True
        if "visibility:hidden" in style.replace(" ", "") or visibility == "hidden":
            is_inv = True
        if opacity == "0" or "opacity:0" in style.replace(" ", ""):
            is_inv = True

        if is_inv:
            invisible_cnt += 1

        fill_attr = elem.attrib.get("fill")
        stroke_attr = elem.attrib.get("stroke")
        is_bg_white = (
            elem_tag in target_shapes
            and is_white_color(fill_attr)
            and (not stroke_attr or stroke_attr.strip().lower() in ("none", "transparent") or is_white_color(stroke_attr))
        )

        if elem_tag in target_shapes and not is_bg_white:
            counts[elem_tag] = counts.get(elem_tag, 0) + 1

        # Check transform attribute
        if "transform" in elem.attrib or "transform" in style:
            transform_cnt += 1

    # Check embedded base64 images
    base64_imgs = len(re.findall(r"data:image/[^;]+;base64", content))
    bitmap_cnt = max(bitmap_cnt, base64_imgs)

    result.element_counts = counts
    result.total_shape_elements = sum(counts.values())
    result.invisible_count = invisible_cnt
    result.has_invisible_elements = invisible_cnt > 0
    result.bitmap_count = bitmap_cnt
    result.has_bitmap_images = bitmap_cnt > 0
    result.transform_count = transform_cnt
    result.has_transforms = transform_cnt > 0

    if result.total_shape_elements == 0:
        result.is_empty = True
        result.errors.append("No processable vector shape elements found (path, polygon, rect, etc.).")
        result.diagnostic_messages.append("Error: no processable vector elements found (empty graphic).")
        result.suitability = "Unsuitable"
        return result

    # Calculate Suitability Score
    score = 100.0

    if result.total_shape_elements < 5:
        score -= 25.0
        result.warnings.append("Very low element count (<5 shapes); fractal dimension may be low.")
        result.diagnostic_messages.append("Very low element count (<5 shapes); fractal degree may be low.")
    elif result.total_shape_elements > 10000:
        result.diagnostic_messages.append("High-detail vector graphic (10,000+ elements).")

    if not result.viewbox:
        score -= 15.0

    if result.has_bitmap_images:
        score -= 20.0
        result.warnings.append("Contains bitmap/image elements which are ignored in vector grid analysis.")
        result.diagnostic_messages.append("Contains bitmap/image objects (ignored in vector grid analysis).")

    if result.has_invisible_elements:
        score -= 5.0
        result.diagnostic_messages.append(f"{invisible_cnt} hidden/invisible element(s) detected.")

    if result.has_transforms:
        result.diagnostic_messages.append(f"{transform_cnt} transform(s) normalized and processed.")

    result.suitability_score = max(0.0, score)

    if result.suitability_score >= 80.0:
        result.suitability = "High"
        result.diagnostic_messages.append("Suitability: High (meets academic standards)")
    elif result.suitability_score >= 50.0:
        result.suitability = "Moderate"
        result.diagnostic_messages.append("Suitability: Moderate (processable despite some warnings)")
    else:
        result.suitability = "Unsuitable"
        result.diagnostic_messages.append("Suitability: Low / Insufficient")

    return result
