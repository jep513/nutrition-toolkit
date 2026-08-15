"""The interface a labelling regime has to satisfy.

A regime knows one jurisdiction's rules for reading a nutrition panel: which
declared quantities map onto which canonical nutrients, how a printed number
relates to the range of true values it could have come from, and which declared
nutrients are derived from others.

Regimes differ in more than arithmetic. A US panel declares sodium in mg and
carbohydrate inclusive of fibre; an EU panel declares salt in g (sodium x 2.5)
and carbohydrate *exclusive* of fibre. Those are definition differences, so
reading an EU panel with US rules yields confidently wrong weights rather than
an error -- which is exactly why `normalize_declared` is part of this interface
and not a shared helper.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from ...nutrients import Nutrient, Registry


@runtime_checkable
class Regime(Protocol):
    """One jurisdiction's rules for reading a nutrition panel."""

    name: str

    def normalize_declared(
        self, values: Mapping[int | str, float], registry: Registry
    ) -> tuple[dict[int, float], list[str]]:
        """Map declared quantities onto canonical nutrients.

        Returns (amounts by canonical id, notes describing each conversion
        applied) so a misread regime is visible rather than silent.
        """
        ...

    def classify(self, nutrient: Nutrient | None) -> str:
        """Return the rounding/tolerance class this nutrient falls into."""
        ...

    def interval(self, nutrient: Nutrient | None, printed: float) -> tuple[float, float]:
        """Return (low, high) true-value bounds for one printed number."""
        ...

    def percent_dv_interval(
        self, nutrient: Nutrient | None, printed_pct: float
    ) -> tuple[float, float] | None:
        """Absolute (low, high) bounds implied by a percent-Daily-Value figure.

        %DV is rounded to coarser increments than absolute amounts, and the
        reference values are jurisdiction-specific (US Daily Values vs EU
        Nutrient Reference Values), so both live with the regime.

        Returns None when this regime has no reference value for the nutrient.
        """
        ...

    def is_derived(self, nutrient: Nutrient | None) -> bool:
        """True if this nutrient is computed from other declared nutrients.

        Energy is the usual case: it follows from the macros, so fitting it
        alongside them over-constrains the system with its own rounding error.
        """
        ...
