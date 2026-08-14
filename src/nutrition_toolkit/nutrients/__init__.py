"""Canonical nutrient identity: ids, units, physical behaviour, aggregation.

    from nutrition_toolkit.nutrients import load_registry, NutrientVector

    reg = load_registry()
    reg["beta_carotene"].id          # 321
    reg["vitamin_d"].unit            # "ug"  (Cronometer stores IU; adapters convert)
    reg.ids_where(solubility="fat")  # what leaves with rendered fat

Ids below 1000 follow USDA SR/FDC nutrient numbering; ids from 900001 are
toolkit-assigned for nutrients with no settled USDA number.
"""

from __future__ import annotations

from .models import (
    Contribution,
    Nutrient,
    NutrientVector,
    UnitConversion,
    UnitConversionError,
)
from .registry import EnergyTerm, Registry, load_registry

__all__ = [
    "Contribution",
    "EnergyTerm",
    "Nutrient",
    "NutrientVector",
    "Registry",
    "UnitConversion",
    "UnitConversionError",
    "load_registry",
]
