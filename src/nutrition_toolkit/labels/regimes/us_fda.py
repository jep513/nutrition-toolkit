"""United States: 21 CFR 101.9 label rounding, inverted.

A printed label value is a rounded figure. Given the printed number we recover
the interval of true amounts that would round to it, so a solver can treat the
panel as constraints of the form  low <= amount <= high  rather than brittle
equalities.

US panels declare per serving (and per container), carbohydrate *inclusive* of
fibre, and sodium as sodium in mg. All three differ under other regimes, which
is why this lives behind `Regime`.

Rounding class comes from the nutrient's canonical unit rather than its name --
the registry already knows that sodium is mg and folate is ug, so there's no
need to pattern-match strings and no way for an unrecognised name to fall
through to a default without anyone noticing.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...nutrients import Nutrient, Registry

ENERGY_ID = 208


class USFDARegime:
    """21 CFR 101.9 rounding rules."""

    name = "us_fda"

    def __init__(self, rel_tol: float = 0.02) -> None:
        # Fallback tolerance for nutrients with no explicit rule below.
        self.rel_tol = rel_tol

    def normalize_declared(
        self, values: Mapping[int | str, float], registry: Registry
    ) -> tuple[dict[int, float], list[str]]:
        """US declarations map straight onto canonical nutrients.

        Sodium is already sodium, and carbohydrate is already fibre-inclusive
        like the registry, so nothing needs converting. EU will not be this
        lucky.
        """
        return registry.resolve_mapping(values), []

    def classify(self, nutrient: Nutrient | None) -> str:
        if nutrient is None:
            return "generic"
        if nutrient.id == ENERGY_ID:
            return "energy"
        if nutrient.unit == "g":
            return "gram_macro"
        if nutrient.unit == "mg":
            return "mg_mineral"
        # ug and IU nutrients (folate, vitamin K, D) have their own increments
        # under 101.9 that aren't encoded here yet; they take the generic band.
        return "generic"

    def is_derived(self, nutrient: Nutrient | None) -> bool:
        return nutrient is not None and nutrient.id == ENERGY_ID

    def interval(self, nutrient: Nutrient | None, printed: float) -> tuple[float, float]:
        cls = self.classify(nutrient)
        v = float(printed)

        if cls == "energy":
            if v < 5:
                return (0.0, 5.0)
            step = 5.0 if v <= 50 else 10.0
            return (v - step / 2, v + step / 2)

        if cls == "gram_macro":
            if v < 0.5:
                return (0.0, 0.5)
            step = 0.5 if v <= 5 else 1.0
            return (max(0.0, v - step / 2), v + step / 2)

        if cls == "mg_mineral":
            if v < 5:
                return (0.0, 5.0)
            step = 5.0 if v <= 140 else 10.0
            return (max(0.0, v - step / 2), v + step / 2)

        # generic: symmetric relative tolerance, min 1 unit absolute
        pad = max(abs(v) * self.rel_tol, 1.0)
        return (max(0.0, v - pad), v + pad)


US_FDA = USFDARegime()
