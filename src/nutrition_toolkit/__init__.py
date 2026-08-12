"""nutrition_toolkit -- tools for building nutrient profiles for foods that
aren't in any database.

Subpackages:
    labels                 printed panel -> true-value intervals, per jurisdiction
    recipe_deformulation   intervals + ingredient profiles -> gram weights
    adapters               per-app I/O shaping (Cronometer today)

The subpackages don't import each other; `solve_label` below is the wiring.
"""

from __future__ import annotations

from .adapters.cronometer import to_cronometer_custom_food
from .labels import DEFAULT_REGIME, Label, PanelReading, Regime, read_panel
from .recipe_deformulation import Ingredient, Solution, solve

__all__ = [
    "DEFAULT_REGIME",
    "Ingredient",
    "Label",
    "PanelReading",
    "Regime",
    "Solution",
    "read_panel",
    "solve",
    "solve_label",
    "to_cronometer_custom_food",
]
__version__ = "0.2.0"


def solve_label(
    ingredients: list[Ingredient],
    label: Label,
    *,
    regime: Regime = DEFAULT_REGIME,
    respect_order: bool = True,
    total_mode: str = "eq",
    use_energy: bool = False,
) -> Solution:
    """Read a printed panel and solve for ingredient weights in one step.

    Convenience over `read_panel` + `solve`. Energy is excluded from the fit by
    default (it's derived from the macros and fights its own rounding) but is
    still reported in `Solution.residuals` as a cross-check.
    """
    reading = read_panel(label, regime)
    return solve(
        ingredients,
        reading.intervals,
        basis_g=reading.basis_g,
        respect_order=respect_order,
        total_mode=total_mode,
        exclude=() if use_energy else reading.derived_keys,
    )
