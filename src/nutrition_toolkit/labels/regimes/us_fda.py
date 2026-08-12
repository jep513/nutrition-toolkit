"""United States: 21 CFR 101.9 label rounding, inverted.

A printed label value is a rounded figure. Given the printed number we recover
the half-open interval of true amounts that would round to it, so a solver can
treat the panel as constraints of the form  low <= amount <= high  rather than
brittle equalities.

US panels are declared per serving (and per container), carbohydrate is
*inclusive* of fibre, and sodium is declared as sodium in mg -- all three
differ under other regimes, which is why this lives behind `Regime`.

Nutrient class is currently inferred from the key name. That is a stopgap:
once nutrients are keyed by canonical ID, class comes from the nutrient
registry instead and the substring matching goes away.
"""

from __future__ import annotations

# Substrings -> rounding class. First match wins; extend freely.
_ENERGY = ("calorie", "energy", "kcal")
_GRAM_MACRO = (
    "protein",
    "fat",
    "carb",
    "fiber",
    "fibre",
    "sugar",
    "starch",
    "saturated",
    "trans",
    "monounsat",
    "polyunsat",
    "omega",
    "epa",
    "dha",
    "ala",
    "linoleic",
    "oleic",
)
_MG_MINERAL = (
    "sodium",
    "potassium",
    "calcium",
    "cholesterol",
    "magnesium",
    "phosphorus",
    "iron",
    "zinc",
)


class USFDARegime:
    """21 CFR 101.9 rounding rules."""

    name = "us_fda"

    def __init__(self, rel_tol: float = 0.02) -> None:
        # Fallback tolerance for nutrients with no explicit rule below.
        self.rel_tol = rel_tol

    def classify(self, nutrient: str) -> str:
        n = nutrient.lower()
        if any(k in n for k in _ENERGY):
            return "energy"
        if any(k in n for k in _MG_MINERAL):
            return "mg_mineral"
        if any(k in n for k in _GRAM_MACRO):
            return "gram_macro"
        return "generic"

    def is_derived(self, nutrient: str) -> bool:
        return self.classify(nutrient) == "energy"

    def interval(self, nutrient: str, printed: float) -> tuple[float, float]:
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
