"""Cronometer adapter.

The only module in this package that knows Cronometer exists. Everything else
works in app-neutral nutrient profiles; adding another tracker means adding a
sibling module here and changing nothing else.

Currently pure shaping -- no network, no dependency on a Cronometer client.
When it grows one (to pull base foods or write recipes back), that dependency
belongs behind the `cronometer` optional extra so the core stays installable
without it.
"""

from __future__ import annotations

from ..recipe_deformulation import Solution


def to_cronometer_custom_food(
    name: str, solution: Solution, serving_g: float | None = None
) -> dict:
    """Shape a Solution into a custom-food dict for the Cronometer MCP's
    add_custom_food tool. Nutrients are the reconstructed totals for the whole
    basis; set `serving_g` to also emit a per-serving scale factor.
    """
    payload = {
        "name": name,
        "basis_grams": round(sum(solution.weights_g.values()), 2),
        "nutrients": {k: round(v, 4) for k, v in solution.reconstructed.items()},
        "ingredients_g": {k: round(v, 2) for k, v in solution.weights_g.items()},
    }
    if serving_g:
        payload["serving_grams"] = serving_g
        payload["servings_in_basis"] = round(payload["basis_grams"] / serving_g, 3)
    return payload
