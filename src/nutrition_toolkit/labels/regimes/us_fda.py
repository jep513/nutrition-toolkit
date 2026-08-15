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

import json
from collections.abc import Mapping
from functools import lru_cache
from importlib import resources

from ...nutrients import Nutrient, Registry, UnitConversionError

ENERGY_ID = 208

_DV_PACKAGE = "nutrition_toolkit.labels.regimes.data"
_DV_FILE = "us_fda_daily_values.json"


@lru_cache(maxsize=1)
def daily_values() -> dict[int, tuple[float, str]]:
    """Canonical nutrient id -> (Daily Value, unit), per 21 CFR 101.9.

    Loaded lazily: a regime instance is built at import time and most callers
    never touch %DV.
    """
    text = resources.files(_DV_PACKAGE).joinpath(_DV_FILE).read_text("utf-8")
    doc = json.loads(text)
    return {
        int(row["id"]): (float(row["value"]), str(row["unit"]))
        for row in doc["daily_values"]
    }


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

    # -- percent Daily Value ------------------------------------------------

    @staticmethod
    def percent_dv_step(printed_pct: float) -> float:
        """The increment a %DV figure was rounded to.

        21 CFR 101.9(c)(8)(iii): to the nearest 2% up to and including 10%,
        the nearest 5% above 10% and up to and including 50%, and the nearest
        10% above 50%. Coarser than the absolute-amount rules, which is the
        whole reason a %DV-only declaration is a weak constraint.
        """
        v = float(printed_pct)
        if v <= 10:
            return 2.0
        if v <= 50:
            return 5.0
        return 10.0

    def percent_dv_interval(
        self, nutrient: Nutrient | None, printed_pct: float
    ) -> tuple[float, float] | None:
        """Absolute (low, high) bounds implied by a %DV figure.

        Returns None when the nutrient has no Daily Value or the DV is stated
        in a unit that can't be converted to canonical -- better to drop the
        constraint than to invent one.

        Usually looser than a printed amount: "Calcium 2%" against a 1300 mg DV
        means anywhere from 13 to 39 mg. Not always, though -- the absolute
        rule for a nutrient under 5 mg collapses to [0, 5], so "Iron 3%" pins
        iron to 0.36-0.72 mg while "Iron 1mg" pins it only to 0-5 mg. That's
        why read_panel intersects the two rather than preferring either.
        """
        if nutrient is None:
            return None
        entry = daily_values().get(nutrient.id)
        if entry is None:
            return None
        dv_value, dv_unit = entry

        if dv_unit != nutrient.unit:
            try:
                dv_value = nutrient.to_canonical(dv_value, dv_unit)
            except UnitConversionError:
                return None

        v = float(printed_pct)
        step = self.percent_dv_step(v)
        lo_pct = max(0.0, v - step / 2)
        hi_pct = v + step / 2
        return (lo_pct / 100.0 * dv_value, hi_pct / 100.0 * dv_value)


US_FDA = USFDARegime()
