"""Find which constraints are jointly impossible.

When a solve comes back infeasible, the residuals say which nutrients missed
but not which *combination* is at fault -- and dropping any single one often
doesn't help, because the conflict involves several at once. Both real labels
we've run behaved that way.

This isolates an irreducible infeasible subset: a set of constraints that
cannot hold together, and from which removing any one makes the rest
satisfiable. That's the smallest honest answer to "what's wrong", and it points
straight at either a bad base profile or a label that contradicts itself.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .models import Ingredient
from .solver import is_feasible


@dataclass(frozen=True)
class Conflict:
    """Constraints that cannot hold together.

    `nutrient_ids` is irreducible: drop any one and the remainder is
    satisfiable. Constraints outside this set are innocent.
    """

    nutrient_ids: tuple[int, ...]

    def __bool__(self) -> bool:
        return bool(self.nutrient_ids)


def find_conflict(
    ingredients: list[Ingredient],
    intervals: Mapping[int, tuple[float, float]],
    *,
    basis_g: float | None = None,
    respect_order: bool = True,
    total_mode: str = "eq",
    exclude: Iterable[int] = (),
    keep: Iterable[int] = (),
) -> Conflict | None:
    """Return an irreducible infeasible subset, or None if the solve is feasible.

    Uses the deletion filter: try removing each constraint in turn, and keep it
    out permanently whenever the rest stay infeasible without it. What survives
    is irreducible. Costs one feasibility test per constraint, which is cheap --
    the underlying problem has one variable per ingredient.

    The basis mass and ingredient order are settings rather than removable
    constraints, so they are always in force and can be part of the conflict
    without appearing in the result. A two-nutrient answer often means "these
    two can't both hold *at this basis*" -- widening `total_mode` to "max" or
    "free" is then worth trying before doubting the profiles.

    Args:
        keep: nutrient ids never considered for removal, for constraints you
            trust and want named in the result if they're implicated.
    """
    exclude = frozenset(exclude)
    keep = frozenset(keep)
    kwargs = {
        "basis_g": basis_g,
        "respect_order": respect_order,
        "total_mode": total_mode,
        "exclude": exclude,
    }

    if is_feasible(ingredients, intervals, **kwargs):
        return None

    # Only constraints that actually bind can be part of the conflict; one no
    # ingredient supplies has an all-zero column and is already inert.
    candidates = [
        nid
        for nid in intervals
        if nid not in exclude and any(nid in ing.per_100g for ing in ingredients)
    ]
    surviving = list(candidates)

    for nid in candidates:
        if nid in keep:
            continue
        trial = {k: v for k, v in intervals.items() if k in surviving and k != nid}
        if not is_feasible(ingredients, trial, **kwargs):
            # Still impossible without it, so it wasn't needed for the conflict.
            surviving.remove(nid)

    if not surviving:
        # Infeasible even with no nutrient constraints: the mass or order
        # constraints alone can't be met.
        return Conflict(())
    return Conflict(tuple(surviving))
