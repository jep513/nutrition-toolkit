"""The interface a labelling regime has to satisfy.

A regime knows one jurisdiction's rules for turning a printed number back into
the range of true values it could have come from, and which declared nutrients
are derived from others. Regimes differ in more than arithmetic -- see the
module docstring in `eu_1169` when that lands -- so `read_panel` always goes
through this interface rather than calling a rounding function directly.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Regime(Protocol):
    """One jurisdiction's rules for reading a nutrition panel."""

    name: str

    def classify(self, nutrient: str) -> str:
        """Return the rounding/tolerance class this nutrient falls into."""
        ...

    def interval(self, nutrient: str, printed: float) -> tuple[float, float]:
        """Return (low, high) true-value bounds for one printed number."""
        ...

    def is_derived(self, nutrient: str) -> bool:
        """True if this nutrient is computed from other declared nutrients.

        Energy is the usual case: it follows from the macros, so fitting it
        alongside them over-constrains the system with its own rounding error.
        """
        ...
