# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mehmet Raşit Narçiçek
"""Grid policy model for the RASH-HIT Engine (Stage 3.2).

Scientific requirement (Stage 3 audit):
    A common grid level L must produce the SAME rows/columns/cell size/origin
    and occupied count regardless of the user's requested maximum level.

Two policies are defined:

* ``FIXED_ORIGIN`` (default, scientific):
    All levels start at one canonical origin.  By default the origin is the
    SVG viewBox minimum corner ``(viewBox.min_x, viewBox.min_y)``.  No offset
    search is performed, so a level's result never depends on the requested
    maximum level and the measurement is the classical fixed-grid
    box-counting count for that grid alignment.

* ``PER_LEVEL_OPTIMIZED_ORIGIN`` (experimental):
    Each level independently chooses the offset (from a FIXED candidate set)
    that minimises the occupied count for its own cell size and the geometry.
    The candidate set is a named constant policy (``2x2``, ``3x3`` or ``4x4``),
    so L2's offset selection never depends on the finest requested level's
    cell size.  This preserves the old "adaptive grid offset" idea while
    removing the level-count dependence that made results non-reproducible.

The policy is recorded in every manifest / reference / engine contract so that
two analyses with different policies are never silently compared as if they
used the same method.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


#: Version of the grid-policy model itself.  Bump when the semantics change.
GRID_POLICY_VERSION = "1"

#: Offset candidate policies for PER_LEVEL_OPTIMIZED_ORIGIN.  Each entry maps a
#: name to the number of samples along one axis (n x n offsets in [0, 1)).
OFFSET_CANDIDATE_POLICIES = {
    "2x2": 2,
    "3x3": 3,
    "4x4": 4,
}
DEFAULT_OFFSET_CANDIDATE_POLICY = "3x3"


class GridPolicy(str, Enum):
    """Enumeration of supported grid-origin policies."""

    FIXED_ORIGIN = "fixed_origin"
    PER_LEVEL_OPTIMIZED_ORIGIN = "per_level_optimized_origin"


@dataclass(frozen=True)
class GridPolicyConfig:
    """Immutable configuration of the grid-origin policy for one analysis."""

    policy: GridPolicy = GridPolicy.FIXED_ORIGIN
    origin_x: float = 0.0
    origin_y: float = 0.0
    offset_candidate_policy: str = DEFAULT_OFFSET_CANDIDATE_POLICY
    policy_version: str = GRID_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.policy not in GridPolicy:
            raise ValueError(f"unknown grid policy: {self.policy!r}")
        if self.offset_candidate_policy not in OFFSET_CANDIDATE_POLICIES:
            raise ValueError(
                f"unknown offset candidate policy {self.offset_candidate_policy!r}; "
                f"expected one of {sorted(OFFSET_CANDIDATE_POLICIES)}"
            )

    def to_dict(self) -> dict:
        """Dictionary form recorded in manifests / references / engine output."""
        return {
            "grid_policy": self.policy.value,
            "origin_x": float(self.origin_x),
            "origin_y": float(self.origin_y),
            "offset_candidate_policy": self.offset_candidate_policy,
            "policy_version": self.policy_version,
        }


def resolve_grid_policy(value: Any) -> GridPolicyConfig:
    """Normalise a user-supplied policy into a ``GridPolicyConfig``.

    Accepts:
    * a ``GridPolicyConfig`` (returned unchanged),
    * a ``GridPolicy`` enum member,
    * a string matching a ``GridPolicy`` value (e.g. ``"fixed_origin"``).
    """
    if isinstance(value, GridPolicyConfig):
        return value
    if isinstance(value, GridPolicy):
        return GridPolicyConfig(policy=value)
    if isinstance(value, str):
        try:
            return GridPolicyConfig(policy=GridPolicy(value))
        except ValueError:
            raise ValueError(
                f"unknown grid policy {value!r}; expected one of "
                f"{[p.value for p in GridPolicy]}"
            ) from None
    raise TypeError(f"cannot interpret {value!r} as a GridPolicyConfig")

