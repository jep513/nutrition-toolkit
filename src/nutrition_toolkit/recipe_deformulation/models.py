"""Core data structures for deformulation.

All ingredient nutrition is expressed *per 100 g of that ingredient as added*
(e.g. plain raw sardine flesh, not the canned+salted product), keyed by
canonical nutrient id and in each nutrient's canonical unit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ..nutrients import NutrientVector, Registry, load_registry


@dataclass
class Ingredient:
    """One recipe component and its full nutrient profile per 100 g.

    `per_100g` may carry as many nutrients as you like -- the ones the label
    constrains drive the solve, but every nutrient here is carried through to
    the reconstructed profile, which is the whole point.

    Keys may be canonical ids, registry names, or aliases; names are resolved
    on construction, so an `Ingredient` always holds canonical ids. An
    unrecognised name raises rather than being carried, since in a
    hand-written profile it's a typo or an unsupported nutrient.
    """

    name: str
    per_100g: dict[int, float] = field(default_factory=dict)
    registry: Registry | None = None

    def __post_init__(self) -> None:
        registry = self.registry or load_registry()
        self.per_100g = registry.resolve_mapping(self.per_100g)

    def amount(self, nutrient_id: int, grams: float) -> float:
        """This ingredient's contribution of `nutrient_id` at `grams` grams."""
        return self.per_100g.get(nutrient_id, 0.0) * grams / 100.0


@dataclass
class Solution:
    feasible: bool
    weights_g: dict[str, float]  # ingredient name -> representative point estimate
    ranges_g: dict[str, tuple[float, float]]  # min/max over the feasible set
    reconstructed: NutrientVector  # full profile for the whole basis
    residuals: dict[int, float]  # signed miss vs nearest interval edge (0 = inside)
    notes: list[str] = field(default_factory=list)

    def reconstructed_named(self, registry: Registry | None = None) -> dict[str, float]:
        """The reconstructed profile keyed by display name, for humans."""
        registry = registry or load_registry()
        return {
            registry.name_for(nid): amount
            for nid, amount in sorted(self.reconstructed.items())
        }

    def residuals_named(
        self, registry: Registry | None = None
    ) -> Mapping[str, float]:
        """Residuals keyed by display name, for humans."""
        registry = registry or load_registry()
        return {registry.name_for(nid): r for nid, r in sorted(self.residuals.items())}
