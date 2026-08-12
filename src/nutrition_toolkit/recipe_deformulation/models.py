"""Core data structures for deformulation.

All ingredient nutrition is expressed *per 100 g of that ingredient as added*
(e.g. plain raw sardine flesh, not the canned+salted product).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Ingredient:
    """One recipe component and its full nutrient profile per 100 g.

    `per_100g` may carry as many nutrients as you like -- macros drive the
    solve, but every key here (micros, fatty acids) is carried through to the
    reconstructed profile, which is the whole point.
    """

    name: str
    per_100g: dict[str, float] = field(default_factory=dict)


@dataclass
class Solution:
    feasible: bool
    weights_g: dict[str, float]  # representative point estimate
    ranges_g: dict[str, tuple[float, float]]  # min/max each weight over the feasible set
    reconstructed: dict[str, float]  # full nutrient totals at the point estimate
    residuals: dict[str, float]  # signed miss vs nearest interval edge (0 = inside)
    notes: list[str] = field(default_factory=list)
