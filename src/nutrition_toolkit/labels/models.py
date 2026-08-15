"""Data structures for printed nutrition panels and how they're read.

A `Label` is what's printed. A `PanelReading` is what that printing *means*:
the true-value interval each number stands for, plus a record of any
conversion applied to get there.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Label:
    """The printed nutrition panel for a known basis mass.

    `values`  : nutrient -> printed amount, in the units the panel uses
                (kcal, g, mg). Keys may be canonical nutrient ids, registry
                names, or aliases -- the regime resolves them when the panel is
                read, since that mapping is jurisdiction-specific.
    `basis_g` : the mass the panel describes. For a US panel this is the
                serving or container weight; EU panels are always per 100 g.
                For a can, usually the net or drained weight (whichever the
                ingredients actually sum to). If None, total mass is left free.
    """

    values: dict[int | str, float] = field(default_factory=dict)
    basis_g: float | None = None
    percent_dv: dict[int | str, float] = field(default_factory=dict)
    """Nutrients declared only as a percent of Daily Value.

    Many panels give vitamin D, calcium, iron and potassium as a bare
    percentage, and older-format labels do the same for vitamins A and C.
    %DV is rounded to much coarser increments than absolute amounts, so these
    are weak constraints -- "Calcium 2%" pins calcium only to somewhere in
    13-39 mg. Declare a nutrient in both places when the panel prints both;
    the reading intersects them and the tighter one wins."""


@dataclass
class PanelReading:
    """A panel translated into solver constraints.

    `intervals`    : canonical nutrient id -> (low, high) true-value bounds.
    `basis_g`      : the basis mass, carried through from the label.
    `derived_keys` : nutrients computed from other declared nutrients (energy
                     from the macros). Fitting these fights their own rounding,
                     so callers usually exclude them and use them as a check.
    `notes`        : every conversion applied while reading the panel, so a
                     misread regime is visible rather than silent.
    """

    intervals: dict[int, tuple[float, float]]
    basis_g: float | None = None
    derived_keys: frozenset[int] = frozenset()
    notes: list[str] = field(default_factory=list)
