"""Cronometer adapter.

The only module in this package that knows Cronometer exists. Everything else
works in canonical nutrient ids and units; adding another tracker means adding
a sibling module here and changing nothing else.

Two things have to happen at this boundary, and doing them here is why the core
can stay ignorant of both:

  * **id remap** -- Cronometer invents ids for nutrients with no USDA number
    (net carbs is -1205, oxalate is 10012), recorded per nutrient in the
    registry's `external_ids`.
  * **unit conversion** -- Cronometer stores vitamin D in IU while the
    canonical unit is ug. The registry knows the factor is exactly 40, so the
    conversion is mechanical rather than a special case someone forgets.

Currently pure shaping -- no network. When it grows a client (to pull base
foods or write recipes back), that dependency belongs behind a `cronometer`
optional extra so the core stays installable without it.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..nutrients import NutrientVector, Registry, UnitConversionError, load_registry
from ..recipe_deformulation import Solution


def to_cronometer_nutrients(
    profile: Mapping[int, float], registry: Registry | None = None
) -> tuple[dict[int, float], list[str]]:
    """Remap a canonical profile onto Cronometer nutrient ids and units.

    Returns (amounts by Cronometer id, notes). Nutrients the registry doesn't
    describe are passed through under their own id -- Cronometer may know a
    nutrient we haven't registered yet, and dropping it would lose real data.
    Nutrients whose unit conversion is ambiguous (vitamins A and E in IU) are
    skipped with a note rather than converted by guesswork.
    """
    registry = registry or load_registry()
    out: dict[int, float] = {}
    notes: list[str] = []

    for nid, amount in profile.items():
        nutrient = registry.get(nid)
        if nutrient is None:
            out[nid] = amount
            notes.append(f"passed through unregistered nutrient id {nid}")
            continue

        external = nutrient.external_ids.get("cronometer") or {}
        target_id = int(external.get("id", nutrient.id))
        target_unit = str(external.get("unit", nutrient.unit))

        if target_unit != nutrient.unit:
            try:
                amount = nutrient.from_canonical(amount, target_unit)
            except UnitConversionError as exc:
                notes.append(f"skipped {nutrient.name}: {exc}")
                continue
            notes.append(
                f"converted {nutrient.name} from {nutrient.unit} to {target_unit}"
            )
        out[target_id] = amount

    return out, notes


def to_cronometer_custom_food(
    name: str,
    solution: Solution,
    serving_g: float | None = None,
    registry: Registry | None = None,
) -> dict:
    """Shape a Solution into a custom-food dict for the Cronometer MCP.

    `nutrients` is keyed by Cronometer nutrient id and ready to hand to
    add_custom_food's `extra_nutrients`. Amounts are the reconstructed totals
    for the whole basis; set `serving_g` to also emit a per-serving factor.
    """
    registry = registry or load_registry()
    nutrients, notes = to_cronometer_nutrients(solution.reconstructed, registry)

    payload = {
        "name": name,
        "basis_grams": round(sum(solution.weights_g.values()), 2),
        "nutrients": {k: round(v, 4) for k, v in sorted(nutrients.items())},
        "ingredients_g": {k: round(v, 2) for k, v in solution.weights_g.items()},
    }
    if notes:
        payload["notes"] = notes
    if serving_g:
        payload["serving_grams"] = serving_g
        payload["servings_in_basis"] = round(payload["basis_grams"] / serving_g, 3)
    return payload


def from_cronometer_food(
    food: Mapping[str, object], registry: Registry | None = None
) -> NutrientVector:
    """Build a canonical per-100 g profile from a Cronometer food object.

    Accepts the shape `get_food`/`get_food_details` returns: a `nutrients` list
    of `{"id": ..., "amount": ...}`. Converts ids and units inward, so callers
    never see IU.
    """
    registry = registry or load_registry()
    by_cronometer_id = {
        n.id: n for n in registry if "cronometer" in n.external_ids
    }
    external_lookup = {
        int(n.external_ids["cronometer"]["id"]): n  # type: ignore[index]
        for n in by_cronometer_id.values()
    }

    amounts: dict[int, float] = {}
    for row in food.get("nutrients", []):  # type: ignore[union-attr]
        if not isinstance(row, Mapping):
            continue
        cid, amount = row.get("id"), row.get("amount")
        if cid is None or not isinstance(amount, (int, float)):
            continue
        nutrient = external_lookup.get(int(cid)) or registry.get(int(cid))
        if nutrient is None:
            amounts[int(cid)] = float(amount)  # unregistered: carry as-is
            continue
        external = nutrient.external_ids.get("cronometer") or {}
        source_unit = str(external.get("unit", nutrient.unit))
        try:
            amounts[nutrient.id] = nutrient.to_canonical(float(amount), source_unit)
        except UnitConversionError:
            # Ambiguous conversions (A/E in IU) are dropped rather than guessed.
            continue
    return NutrientVector(amounts, basis_g=100.0)
