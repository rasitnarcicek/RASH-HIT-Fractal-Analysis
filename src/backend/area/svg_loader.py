# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek

"""
svg_loader.py — SVG Loader & CSS Style Resolver module.
Parses SVG XML structure, resolves CSS style blocks (using tinycss2 with regex fallback), class definitions, inline styles,
and presentation attributes according to SVG priority rules. Filters out hidden/invisible elements.
Detects advanced features (clipPath, mask, fill-rule) and records warnings for report outputs.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from pathlib import Path
# Use defusedxml for safe XML parsing; fall back to stdlib with a warning.
try:
    import defusedxml.ElementTree as ET  # type: ignore[import]
except ImportError:  # pragma: no cover
    import warnings as _warnings
    _warnings.warn(
        "defusedxml not installed. Falling back to stdlib xml.etree.ElementTree. "
        "Install defusedxml>=0.7.1 for XML attack protection.",
        ImportWarning, stacklevel=2,
    )
    import xml.etree.ElementTree as ET  # type: ignore[assignment]
from typing import Any, Dict, List, Tuple, Optional, Set

from .vector_geometry import (
    StrokeLineCap,
    StrokeLineJoin,
    StrokeResolutionDiagnostics,
    StrokeStyle,
)

try:
    import tinycss2
    HAS_TINYCSS2 = True
except ImportError:
    HAS_TINYCSS2 = False


@dataclass
class CSSSelector:
    """Represents a parsed CSS selector with specificity scoring."""
    raw_selector: str
    tag_filter: Optional[str]
    id_filter: Optional[str]
    class_filters: List[str]
    id_count: int
    class_count: int
    type_count: int

    @classmethod
    def parse(cls, sel_str: str) -> CSSSelector:
        s = sel_str.strip()
        # Parse ID: #id
        id_match = re.search(r'#([a-zA-Z0-9_\-]+)', s)
        id_filter = id_match.group(1) if id_match else None
        id_count = 1 if id_filter else 0

        # Parse classes: .cls-1
        class_filters = re.findall(r'\.([a-zA-Z0-9_\-]+)', s)
        class_count = len(class_filters)

        # Parse tag/element: leading identifier before # or .
        tag_match = re.match(r'^([a-zA-Z0-9_\*]+)', s)
        tag_filter = None
        type_count = 0
        if tag_match:
            t = tag_match.group(1).lower()
            if t != '*':
                tag_filter = t
                type_count = 1

        return cls(
            raw_selector=s,
            tag_filter=tag_filter,
            id_filter=id_filter,
            class_filters=class_filters,
            id_count=id_count,
            class_count=class_count,
            type_count=type_count,
        )

    def matches(self, tag: str, elem_id: Optional[str], elem_classes: Set[str]) -> bool:
        """Determines if this selector matches an SVG element."""
        if self.tag_filter and self.tag_filter != '*' and self.tag_filter.lower() != tag.lower():
            return False
        if self.id_filter and self.id_filter != elem_id:
            return False
        for c in self.class_filters:
            if c not in elem_classes:
                return False
        return True


@dataclass
class CSSDeclaration:
    """A single property declaration with !important tracking."""
    name: str
    value: str
    is_important: bool = False


@dataclass
class CSSRule:
    """A CSS qualified rule with selector, declarations, and source order."""
    selector: CSSSelector
    declarations: Dict[str, CSSDeclaration]
    source_order: int

    @property
    def specificity_tuple(self) -> Tuple[int, int, int]:
        """Returns standard CSS specificity (a: IDs, b: Classes/attributes, c: Types/elements)."""
        return (self.selector.id_count, self.selector.class_count, self.selector.type_count)


@dataclass
class FillRuleResolutionDiagnostics:
    """Detailed diagnostic audit of how fill-rule was resolved for an SVG element."""
    resolved_fill_rule: str
    winning_source: str           # "inline_style", "author_stylesheet", "presentation_attribute", "inherited", "default"
    winning_selector: Optional[str] = None
    specificity: Tuple[int, int, int, int] = (0, 0, 0, 0)  # (inline, id, class, type)
    source_order: int = 0
    is_important: bool = False
    inherited: bool = False
    default_used: bool = False
    invalid_value_seen: bool = False
    warning_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resolved_fill_rule": self.resolved_fill_rule,
            "winning_source": self.winning_source,
            "winning_selector": self.winning_selector,
            "specificity": list(self.specificity),
            "source_order": self.source_order,
            "is_important": self.is_important,
            "inherited": self.inherited,
            "default_used": self.default_used,
            "invalid_value_seen": self.invalid_value_seen,
            "warning_codes": list(self.warning_codes),
        }


def parse_css_style_rules(style_content: str, start_order: int = 0) -> Tuple[List[CSSRule], int]:
    """Parses CSS <style> block into CSSRule objects with selector specificity and source order."""
    rules: List[CSSRule] = []
    curr_order = start_order
    if not style_content:
        return rules, curr_order

    if HAS_TINYCSS2:
        try:
            rulesets = tinycss2.parse_stylesheet(style_content, skip_comments=True, skip_whitespace=True)
            for rule in rulesets:
                if rule.type == 'qualified-rule':
                    selector_str = "".join([token.serialize() for token in rule.prelude]).strip()
                    declarations = tinycss2.parse_declaration_list(rule.content, skip_comments=True, skip_whitespace=True)
                    props: Dict[str, CSSDeclaration] = {}
                    for decl in declarations:
                        if decl.type == 'declaration':
                            prop_name = decl.name.lower()
                            raw_val = "".join([token.serialize() for token in decl.value]).strip()
                            is_imp = False
                            if decl.important:
                                is_imp = True
                                prop_val = raw_val.lower()
                            else:
                                if raw_val.lower().endswith("!important"):
                                    is_imp = True
                                    prop_val = raw_val[:-10].strip().lower()
                                else:
                                    prop_val = raw_val.lower()
                            props[prop_name] = CSSDeclaration(name=prop_name, value=prop_val, is_important=is_imp)

                    for sel in selector_str.split(','):
                        sel_clean = sel.strip()
                        if sel_clean:
                            curr_order += 1
                            parsed_sel = CSSSelector.parse(sel_clean)
                            rules.append(CSSRule(selector=parsed_sel, declarations=props, source_order=curr_order))
            if rules:
                return rules, curr_order
        except Exception:
            pass  # Fall back to regex parser

    # Fallback Regex CSS Parser
    clean_css = re.sub(r'/\*.*?\*/', '', style_content, flags=re.DOTALL)
    blocks = re.findall(r'([^{]+)\{([^}]+)\}', clean_css)

    for selectors, props_raw in blocks:
        props: Dict[str, CSSDeclaration] = {}
        for line in props_raw.split(';'):
            line_str = line.strip()
            if ':' in line_str:
                key, val_raw = line_str.split(':', 1)
                k = key.strip().lower()
                v_str = val_raw.strip()
                is_imp = False
                if v_str.lower().endswith("!important"):
                    is_imp = True
                    v_clean = v_str[:-10].strip().lower()
                else:
                    v_clean = v_str.lower()
                props[k] = CSSDeclaration(name=k, value=v_clean, is_important=is_imp)

        for sel in selectors.split(','):
            sel_clean = sel.strip()
            if sel_clean:
                curr_order += 1
                parsed_sel = CSSSelector.parse(sel_clean)
                rules.append(CSSRule(selector=parsed_sel, declarations=props, source_order=curr_order))

    return rules, curr_order


def parse_css_style_block(style_content: str) -> Dict[str, Dict[str, str]]:
    """Legacy helper: extracts class rules dictionary from CSS string."""
    rules, _ = parse_css_style_rules(style_content)
    out: Dict[str, Dict[str, str]] = {}
    for r in rules:
        for c in r.selector.class_filters:
            if c not in out:
                out[c] = {}
            for k, d in r.declarations.items():
                out[c][k] = d.value
    return out


def parse_style_attribute(style_str: str) -> Dict[str, CSSDeclaration]:
    """Parses inline style="..." attribute string into CSSDeclaration items."""
    props: Dict[str, CSSDeclaration] = {}
    if not style_str:
        return props
    for item in style_str.split(';'):
        item_str = item.strip()
        if ':' in item_str:
            k, v_raw = item_str.split(':', 1)
            key = k.strip().lower()
            v_clean = v_raw.strip()
            is_imp = False
            if v_clean.lower().endswith("!important"):
                is_imp = True
                val = v_clean[:-10].strip().lower()
            else:
                val = v_clean.lower()
            props[key] = CSSDeclaration(name=key, value=val, is_important=is_imp)
    return props


def parse_length(val_str: str, default: float = 0.0) -> float:
    """Parses length values like '.24px', '100', '10.5mm', '12pt' to float pixels."""
    if not val_str:
        return default
    val_str = str(val_str).strip().lower()
    if val_str.endswith('px'):
        val_str = val_str[:-2]
    elif val_str.endswith('pt'):
        try:
            return float(val_str[:-2]) * 1.33333
        except ValueError:
            return default
    elif val_str.endswith('em') or val_str.endswith('rem'):
        try:
            return float(val_str[:-2]) * 16.0
        except ValueError:
            return default
    try:
        return float(val_str)
    except ValueError:
        return default


def is_white_color(val_str: Optional[str]) -> bool:
    """Returns True if the CSS/SVG color string represents pure white (canvas background / negative space)."""
    if not val_str:
        return False
    s = str(val_str).strip().lower().replace(" ", "")
    if s in ("white", "#fff", "#ffff", "#ffffff", "#ffffffff"):
        return True
    if s.startswith("rgb(") and s.endswith(")"):
        inner = s[4:-1]
        if inner in ("255,255,255", "100%,100%,100%"):
            return True
    if s.startswith("rgba(") and s.endswith(")"):
        parts = s[5:-1].split(",")
        if len(parts) == 4 and parts[:3] in (["255", "255", "255"], ["100%", "100%", "100%"]):
            return True
    if s.startswith("hsl(") and s.endswith(")"):
        parts = s[4:-1].split(",")
        if len(parts) == 3 and parts[2] == "100%":
            return True
    if s.startswith("hsla(") and s.endswith(")"):
        parts = s[5:-1].split(",")
        if len(parts) == 4 and parts[2] == "100%":
            return True
    return False


class SVGNode:
    """Represents a resolved SVG element with effective styles, diagnostics, and geometry attributes."""
    def __init__(
        self,
        tag: str,
        attribs: Dict[str, str],
        styles: Dict[str, str],
        transform_str: str,
        fill_rule_diagnostics: Optional[FillRuleResolutionDiagnostics] = None,
        fill_rule_warning: Optional[str] = None,
        stroke_diagnostics: Optional[StrokeResolutionDiagnostics] = None,
    ):
        self.tag = tag.split('}')[-1]  # Strip XML namespace if present
        self.attribs = attribs
        self.styles = styles
        self.transform_str = transform_str
        self.fill_rule_diagnostics = fill_rule_diagnostics
        self.fill_rule_warning = fill_rule_warning
        self.stroke_diagnostics = stroke_diagnostics
        self.stroke_warnings: List[str] = []

        # Resolved fill properties
        self.fill = styles.get('fill', 'black')
        self.fill_rule = styles.get('fill-rule', 'nonzero')
        if self.fill_rule not in ('nonzero', 'evenodd'):
            if self.fill_rule_warning is None:
                self.fill_rule_warning = f"Invalid fill-rule '{self.fill_rule}' defaulted to 'nonzero' per SVG specification."
            self.fill_rule = 'nonzero'

        # Resolved stroke properties
        self.stroke = styles.get('stroke', 'none')
        raw_sw = styles.get('stroke-width', '1')
        self.stroke_width = parse_length(raw_sw, default=1.0)
        if self.stroke_width < 0.0:
            self.stroke_warnings.append(f"Negative stroke-width '{raw_sw}' defaulted to 0.0.")
            self.stroke_width = 0.0

        # stroke-linecap
        raw_cap = styles.get('stroke-linecap', 'butt')
        self.stroke_linecap, cap_warn = StrokeLineCap.from_str(raw_cap)
        if cap_warn:
            self.stroke_warnings.append(cap_warn)

        # stroke-linejoin
        raw_join = styles.get('stroke-linejoin', 'miter')
        self.stroke_linejoin, join_warn = StrokeLineJoin.from_str(raw_join)
        if join_warn:
            self.stroke_warnings.append(join_warn)

        # stroke-miterlimit
        raw_ml = styles.get('stroke-miterlimit', '4')
        try:
            ml_val = float(raw_ml)
            if ml_val < 1.0:
                self.stroke_miterlimit = 4.0
                self.stroke_warnings.append(f"Invalid stroke-miterlimit '{raw_ml}' (< 1.0) defaulted to 4.0.")
            else:
                self.stroke_miterlimit = ml_val
        except ValueError:
            self.stroke_miterlimit = 4.0
            self.stroke_warnings.append(f"Invalid stroke-miterlimit '{raw_ml}' defaulted to 4.0.")

        # stroke-dasharray
        raw_da = styles.get('stroke-dasharray', 'none')
        if raw_da and raw_da.lower() != 'none':
            try:
                self.stroke_dasharray = [float(p) for p in re.split(r'[\s,]+', raw_da.strip()) if p]
            except ValueError:
                self.stroke_dasharray = None
        else:
            self.stroke_dasharray = None

        # stroke-dashoffset
        raw_do = styles.get('stroke-dashoffset', '0')
        try:
            self.stroke_dashoffset = float(raw_do)
        except ValueError:
            self.stroke_dashoffset = 0.0

        # vector-effect
        self.vector_effect = styles.get('vector-effect', 'none').strip().lower()
        if self.vector_effect == 'non-scaling-stroke':
            self.stroke_warnings.append("vector-effect='non-scaling-stroke' detected. Local stroke envelope transformed.")

        # General opacity & visibility
        self.opacity = float(styles.get('opacity', '1.0'))
        self.display = styles.get('display', 'inline')
        self.visibility = styles.get('visibility', 'visible')

        # Per-channel alpha: effective alpha = opacity * channel_opacity (SVG spec)
        _fill_opacity = float(styles.get('fill-opacity', '1.0'))
        _stroke_opacity = float(styles.get('stroke-opacity', '1.0'))
        self.effective_fill_alpha = self.opacity * _fill_opacity
        self.effective_stroke_alpha = self.opacity * _stroke_opacity

        # White color detection (background canvas or negative-space knockout)
        self.is_white_fill = is_white_color(self.fill) and self.effective_fill_alpha > 0
        self.is_white_stroke = is_white_color(self.stroke) and self.stroke_width > 0 and self.effective_stroke_alpha > 0

        # Flags
        self.has_fill = (
            self.fill not in ('none', 'transparent', '')
            and not self.is_white_fill
            and self.effective_fill_alpha > 0
        )
        self.has_stroke = (
            self.stroke not in ('none', 'transparent', '')
            and not self.is_white_stroke
            and self.stroke_width > 0
            and self.effective_stroke_alpha > 0
        )
        self.is_visible = (
            self.display != 'none'
            and self.visibility != 'hidden'
            and (self.has_fill or self.has_stroke)
        )
        self.is_knockout_candidate = (
            self.display != 'none'
            and self.visibility != 'hidden'
            and self.is_white_fill
        )

        # Unified StrokeStyle object
        self.stroke_style = StrokeStyle(
            color=self.stroke if not self.is_white_stroke else 'none',
            width=self.stroke_width,
            linecap=self.stroke_linecap,
            linejoin=self.stroke_linejoin,
            miterlimit=self.stroke_miterlimit,
            dasharray=self.stroke_dasharray,
            dashoffset=self.stroke_dashoffset,
            vector_effect=self.vector_effect,
            diagnostics=self.stroke_diagnostics,
            warnings=list(self.stroke_warnings),
        )


class SVGLoader:
    """Loads and parses SVG files into structured nodes with fully resolved styles and warning detection."""
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.tree = ET.parse(filepath)
        self.root = self.tree.getroot()
        self.css_rules: Dict[str, Dict[str, str]] = {}
        self.css_rules_list: List[CSSRule] = []
        self.viewbox: Optional[Tuple[float, float, float, float]] = None
        self.width: float = 0.0
        self.height: float = 0.0
        self.warnings: List[str] = []

        self._parse_metadata()
        self._collect_css_styles()

    def _parse_metadata(self):
        """Extracts viewBox, width, and height from root <svg> tag."""
        root_attribs = self.root.attrib

        # Case-insensitive attribute lookup
        attr_map = {k.lower(): v for k, v in root_attribs.items()}

        # viewBox: "minX minY width height"
        if 'viewbox' in attr_map:
            parts = [float(p) for p in re.split(r'[\s,]+', attr_map['viewbox'].strip()) if p]
            if len(parts) == 4:
                self.viewbox = (parts[0], parts[1], parts[2], parts[3])

        w_str = attr_map.get('width', '')
        h_str = attr_map.get('height', '')
        self.width = parse_length(w_str, default=0.0)
        self.height = parse_length(h_str, default=0.0)

        if not self.viewbox and self.width > 0 and self.height > 0:
            self.viewbox = (0.0, 0.0, self.width, self.height)
            self.warnings.append(f"viewBox attribute missing. Defaulted to (0, 0, {self.width}, {self.height}) from width/height.")
        elif self.viewbox and (self.width == 0 or self.height == 0):
            self.width = self.viewbox[2]
            self.height = self.viewbox[3]

    def _collect_css_styles(self):
        """Extracts all <style> tag contents from SVG into rules list and legacy dictionary."""
        curr_order = 0
        for elem in self.root.iter():
            tag = elem.tag.split('}')[-1]
            if tag == 'style' and elem.text:
                rules, curr_order = parse_css_style_rules(elem.text, start_order=curr_order)
                self.css_rules_list.extend(rules)
                parsed_legacy = parse_css_style_block(elem.text)
                for cls_name, props in parsed_legacy.items():
                    if cls_name not in self.css_rules:
                        self.css_rules[cls_name] = {}
                    self.css_rules[cls_name].update(props)

    def _resolve_element_styles(
        self,
        elem: ET.Element,
        parent_styles: Dict[str, str],
        parent_explicit_props: Optional[Set[str]] = None,
    ) -> Tuple[Dict[str, str], Optional[FillRuleResolutionDiagnostics], Optional[str], Optional[StrokeResolutionDiagnostics], Set[str]]:
        """Resolves effective styles for an element according to W3C SVG/CSS cascade rules:

        Priority order:
        1. Inline style="..." with !important (highest)
        2. Author stylesheet rules with !important (specificity + source order)
        3. Inline style="..." (normal declarations)
        4. Author stylesheet rules (specificity: id > class > type + source order)
        5. Presentation attributes (e.g. fill-rule="evenodd", fill="red")
        6. Inherited values from parent container (<g>)
        7. Initial / default value (e.g. fill-rule: nonzero)
        """
        tag = elem.tag.split('}')[-1]
        elem_id = elem.attrib.get('id')
        elem_classes = set(elem.attrib.get('class', '').split())
        inline_declarations = parse_style_attribute(elem.attrib.get('style', ''))
        parent_explicit = parent_explicit_props if parent_explicit_props is not None else set()

        CSS_PROPERTIES = (
            'fill', 'stroke', 'stroke-width', 'fill-rule', 'opacity',
            'display', 'visibility', 'fill-opacity', 'stroke-opacity',
            'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit',
            'stroke-dasharray', 'stroke-dashoffset', 'vector-effect'
        )
        DEFAULT_VALUES = {
            'fill': 'black',
            'stroke': 'none',
            'stroke-width': '1',
            'fill-rule': 'nonzero',
            'opacity': '1.0',
            'display': 'inline',
            'visibility': 'visible',
            'fill-opacity': '1.0',
            'stroke-opacity': '1.0',
            'stroke-linecap': 'butt',
            'stroke-linejoin': 'miter',
            'stroke-miterlimit': '4',
            'stroke-dasharray': 'none',
            'stroke-dashoffset': '0',
            'vector-effect': 'none',
        }

        matching_rules = [r for r in self.css_rules_list if r.selector.matches(tag, elem_id, elem_classes)]

        effective_styles: Dict[str, str] = {}
        explicit_props: Set[str] = set()
        fill_rule_diag: Optional[FillRuleResolutionDiagnostics] = None
        fill_rule_warning: Optional[str] = None
        stroke_diag: Optional[StrokeResolutionDiagnostics] = None

        for prop in CSS_PROPERTIES:
            candidates = []

            # 1. Presentation attribute
            if prop in elem.attrib:
                val = elem.attrib[prop].strip().lower()
                candidates.append((
                    False,      # is_important
                    False,      # is_inline
                    0, 0, 0,    # id, class, type specificity = (0,0,0)
                    0,          # source_order
                    val,
                    "presentation_attribute",
                    None,
                ))

            # 2. Author stylesheet rules
            for rule in matching_rules:
                if prop in rule.declarations:
                    decl = rule.declarations[prop]
                    candidates.append((
                        decl.is_important,
                        False,  # is_inline
                        rule.selector.id_count,
                        rule.selector.class_count,
                        rule.selector.type_count,
                        rule.source_order,
                        decl.value,
                        "author_stylesheet",
                        rule.selector.raw_selector,
                    ))

            # 3. Inline style
            if prop in inline_declarations:
                decl = inline_declarations[prop]
                candidates.append((
                    decl.is_important,
                    True,   # is_inline
                    0, 0, 0,
                    999999, # inline wins over normal stylesheet rules
                    decl.value,
                    "inline_style",
                    None,
                ))

            if candidates:
                # Sort by priority key
                candidates.sort(key=lambda c: (c[0], c[1], c[2], c[3], c[4], c[5]))
                winner = candidates[-1]
                is_imp, is_inl, id_c, cls_c, typ_c, s_ord, win_val, win_src, win_sel = winner
                effective_styles[prop] = win_val
                explicit_props.add(prop)

                if prop == 'fill-rule':
                    spec_tuple = (1 if is_inl else 0, id_c, cls_c, typ_c)
                    clean_fr = win_val
                    warn = None
                    inv_seen = False
                    warn_codes = []
                    if clean_fr not in ('nonzero', 'evenodd'):
                        inv_seen = True
                        warn_codes.append("WARN_INVALID_FILL_RULE")
                        warn = f"Invalid fill-rule '{win_val}' on <{tag}>; defaulted to 'nonzero' per SVG specification."
                        effective_styles['fill-rule'] = 'nonzero'
                        clean_fr = 'nonzero'

                    fill_rule_diag = FillRuleResolutionDiagnostics(
                        resolved_fill_rule=clean_fr,
                        winning_source=win_src,
                        winning_selector=win_sel,
                        specificity=spec_tuple,
                        source_order=s_ord,
                        is_important=is_imp,
                        inherited=False,
                        default_used=False,
                        invalid_value_seen=inv_seen,
                        warning_codes=warn_codes,
                    )
                    fill_rule_warning = warn

                if prop == 'stroke':
                    stroke_diag = StrokeResolutionDiagnostics(
                        winning_source=win_src,
                        specificity=(1 if is_inl else 0, id_c, cls_c, typ_c),
                        is_important=is_imp,
                        warning_codes=[],
                    )
            else:
                # Check inherited value from parent if explicitly set on ancestor
                if prop in parent_styles and prop in parent_explicit:
                    effective_styles[prop] = parent_styles[prop]
                    explicit_props.add(prop)
                    if prop == 'fill-rule':
                        fill_rule_diag = FillRuleResolutionDiagnostics(
                            resolved_fill_rule=parent_styles[prop],
                            winning_source="inherited",
                            inherited=True,
                            default_used=False,
                        )
                    if prop == 'stroke' and stroke_diag is None:
                        stroke_diag = StrokeResolutionDiagnostics(
                            winning_source="inherited",
                            specificity=(0, 0, 0, 0),
                            is_important=False,
                            warning_codes=[],
                        )
                else:
                    effective_styles[prop] = DEFAULT_VALUES[prop]
                    if prop == 'fill-rule':
                        fill_rule_diag = FillRuleResolutionDiagnostics(
                            resolved_fill_rule=DEFAULT_VALUES['fill-rule'],
                            winning_source="initial_default",
                            inherited=False,
                            default_used=True,
                        )
                    if prop == 'stroke' and stroke_diag is None:
                        stroke_diag = StrokeResolutionDiagnostics(
                            winning_source="initial_default",
                            specificity=(0, 0, 0, 0),
                            is_important=False,
                            warning_codes=[],
                        )

        return effective_styles, fill_rule_diag, fill_rule_warning, stroke_diag, explicit_props

    def get_elements(self, include_white_knockouts: bool = False) -> List[Tuple[SVGNode, List[str]]]:
        """
        Traverses SVG tree and returns a list of (SVGNode, transform_stack).
        Applies style priority: Inline style > Author Stylesheet > Presentation Attrs > Inherited.
        Detects clipPath, mask, and fill-rule features for warnings.
        """
        elements: List[Tuple[SVGNode, List[str]]] = []
        self._traverse_node(
            self.root,
            parent_styles={},
            parent_explicit_props=set(),
            transform_stack=[],
            results=elements,
            include_white_knockouts=include_white_knockouts,
        )
        return elements

    def _traverse_node(
        self,
        elem: ET.Element,
        parent_styles: Dict[str, str],
        parent_explicit_props: Set[str],
        transform_stack: List[str],
        results: List[Tuple[SVGNode, List[str]]],
        include_white_knockouts: bool = False,
    ):
        tag = elem.tag.split('}')[-1]

        # Feature detection warnings
        if tag == 'clipPath':
            self.warnings.append("clipPath element detected. Clipping geometry bounds are ignored in core v1.0.")
            return
        if tag == 'mask' or 'mask' in elem.attrib:
            self.warnings.append("mask attribute/element detected. Alpha masking is ignored in core v1.0.")
            return

        if tag in ('defs', 'symbol'):
            return  # Skip definitions and non-rendered templates

        # Resolve styles according to cascade
        effective_styles, fill_rule_diag, fill_rule_warn, stroke_diag, explicit_props = self._resolve_element_styles(
            elem, parent_styles, parent_explicit_props
        )

        # Transform attribute handling
        node_transform = elem.attrib.get('transform', '')
        current_transform_stack = list(transform_stack)
        if node_transform:
            current_transform_stack.append(node_transform)

        # Check if rendering element
        render_tags = {'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon'}
        if tag in render_tags:
            node = SVGNode(
                tag=tag,
                attribs=elem.attrib,
                styles=effective_styles,
                transform_str=node_transform,
                fill_rule_diagnostics=fill_rule_diag,
                fill_rule_warning=fill_rule_warn,
                stroke_diagnostics=stroke_diag,
            )
            if fill_rule_warn:
                self.warnings.append(fill_rule_warn)
            if node.fill_rule == 'evenodd':
                self.warnings.append("fill-rule='evenodd' detected. Winding-aware compound-path fill applied (Stage 3).")
            if node.stroke_warnings:
                self.warnings.extend(node.stroke_warnings)
            if node.is_visible or (include_white_knockouts and node.is_knockout_candidate):
                results.append((node, current_transform_stack))

        # Recurse into children (e.g. <g> groups)
        child_explicit = set(parent_explicit_props) | explicit_props
        for child in elem:
            self._traverse_node(
                child,
                effective_styles,
                child_explicit,
                current_transform_stack,
                results,
                include_white_knockouts=include_white_knockouts,
            )


def load_svg_geometries(filepath: str | Path):
    """Convenience helper to load an SVG file and extract all transformed ParsedGeometry items.

    White-filled shapes on an empty canvas (such as full-canvas background <rect fill="#ffffff">)
    are ignored as negative space. White-filled shapes painted on top of existing foreground
    geometries subtract (knock out) their interior from underlying geometries per SVG Painter's Model.
    """
    from .geometry_engine import extract_node_geometries
    loader = SVGLoader(str(filepath))
    vw = loader.viewbox[2] if loader.viewbox else (loader.width or 100.0)
    vh = loader.viewbox[3] if loader.viewbox else (loader.height or 100.0)
    canvas_area = max(1e-9, float(vw) * float(vh))

    elements = loader.get_elements(include_white_knockouts=True)
    geoms = []
    for node, transform_stack in elements:
        if getattr(node, "is_knockout_candidate", False) and len(geoms) > 0:
            ko_list = extract_node_geometries(node, transform_stack, extract_white_fill=True)
            for ko in ko_list:
                if ko.shapely_obj is not None and not ko.shapely_obj.is_empty:
                    # Only apply knockout if it is an interior shape, not a full-canvas background rect
                    if float(ko.shapely_obj.area) < 0.98 * canvas_area:
                        updated_geoms = []
                        for g in geoms:
                            if g.shapely_obj is not None and not g.shapely_obj.is_empty:
                                try:
                                    diff_obj = g.shapely_obj.difference(ko.shapely_obj)
                                    if diff_obj is not None and not diff_obj.is_empty:
                                        g.shapely_obj = diff_obj
                                        g.bounds = diff_obj.bounds
                                        updated_geoms.append(g)
                                except Exception:
                                    updated_geoms.append(g)
                        geoms = updated_geoms
        if node.is_visible:
            parsed_list = extract_node_geometries(node, transform_stack)
            geoms.extend(parsed_list)

    return geoms, vw, vh

