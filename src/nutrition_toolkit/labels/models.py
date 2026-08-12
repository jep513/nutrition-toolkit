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
                (kcal, g, mg). Keys must match the ingredient nutrient keys.
    `basis_g` : the mass the panel describes. For a US panel this is the
                serving or container weight; EU panels are always per 100 g.
                For a can, usually the net or drained weight (whichever the
                ingredients actually sum to). If None, total mass is left free.
    """

    values: dict[str, float]
    basis_g: float | None = None


@dataclass
class PanelReading:
    """A panel translated into solver constraints.

    `intervals`    : nutrient -> (low, high) true-value bounds.
    `basis_g`      : the basis mass, carried through from the label.
    `derived_keys` : nutrients computed from other declared nutrients (energy
                     from the macros). Fitting these fights their own rounding,
                     so callers usually exclude them and use them as a check.
    `notes`        : every conversion applied while reading the panel, so a
                     misread regime is visible rather than silent.
    """

    intervals: dict[str, tuple[float, float]]
    basis_g: float | None = None
    derived_keys: frozenset[str] = frozenset()
    notes: list[str] = field(default_factory=list)
