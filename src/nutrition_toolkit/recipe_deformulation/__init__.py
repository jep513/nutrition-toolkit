"""Recover per-ingredient gram weights from nutrient bounds.

Takes constraints (nutrient -> interval) plus per-100 g ingredient profiles and
returns the feasible weights, with an honest range on each. Deliberately has no
notion of a nutrition label; see `nutrition_toolkit.labels`.
"""

from __future__ import annotations

from .models import Ingredient, Solution
from .solver import solve

__all__ = ["Ingredient", "Solution", "solve"]
