"""MCP server exposing the nutrition toolkit.

One tool for now: `deformulate`. It resolves Cronometer food ids to nutrient
profiles *server-side* rather than making the caller pass them, because a
profile is ~90 numbers and the workflow this exists for is iterative -- swap an
ingredient, add salt, drop fibre, solve again. Shipping 360 floats through the
model on every iteration would dominate the conversation; ids are four
integers.

Food *search* deliberately lives elsewhere (the Cronometer MCP): choosing
between "Peanuts, Dry Roasted, Salted" and the unsalted entry is a judgement
call that needs the model to see candidates. Expose the decisions, hide the
plumbing.

This module imports Cronometer only through `adapters`, so the layering the
rest of the package maintains is unaffected.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..adapters.cronometer import CronometerUnavailableError, fetch_profile, food_name
from ..labels import Label, get_regime, read_panel
from ..nutrients import load_registry
from ..recipe_deformulation import Ingredient, find_conflict, solve

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "nutrition-toolkit",
    instructions=(
        "Tools for building nutrient profiles for foods that aren't in any "
        "database. `deformulate` backs out each ingredient's gram weight in a "
        "packaged food from its nutrition panel plus its ordered ingredient "
        "list, then reconstructs the full micronutrient profile the label "
        "never prints. Find ingredient food ids with the Cronometer server's "
        "search first, then pass them here."
    ),
)


def _err(exc: Exception) -> str:
    return json.dumps({"status": "error", "message": f"{type(exc).__name__}: {exc}"})


def _round(value: object, digits: int) -> float:
    """Coerce to a native float before rounding.

    Amounts come back from the solver as numpy scalars, which json.dumps
    refuses. Casting here keeps the conversion in one place rather than
    sprinkling float() through the response construction.
    """
    return round(float(value), digits)  # type: ignore[arg-type]


def _build_ingredient(spec: dict, registry) -> Ingredient:
    """One entry of the `ingredients` argument -> an Ingredient.

    Accepts either a Cronometer food id (fetched and converted server-side) or
    a literal per-100 g profile, so the tool stays usable without a tracker.
    """
    overrides = spec.get("overrides") or {}
    if "food_id" in spec and spec["food_id"] is not None:
        food_id = int(spec["food_id"])
        profile = dict(fetch_profile(food_id))
        name = spec.get("name") or food_name(food_id)
    elif "per_100g" in spec:
        profile = registry.resolve_mapping(spec["per_100g"])
        name = spec.get("name") or "unnamed"
    else:
        raise ValueError(
            f"each ingredient needs 'food_id' or 'per_100g'; got {sorted(spec)}"
        )
    if overrides:
        profile.update(registry.resolve_mapping(overrides))
    return Ingredient(name, profile)


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    }
)
def deformulate(
    label: dict[str, float],
    ingredients: list[dict],
    basis_g: float | None = None,
    percent_dv: dict[str, float] | None = None,
    exclude: list[str] | None = None,
    respect_order: bool = True,
    total_mode: str = "eq",
    regime: str = "us_fda",
) -> str:
    """Back out each ingredient's gram weight from a nutrition label.

    Reads the printed panel as intervals (a printed "22 g protein" means
    21.5-22.5, not exactly 22), then finds the ingredient weights consistent
    with all of them. Returns the reconstructed full nutrient profile,
    including micronutrients and fatty acids the label never lists.

    The response echoes back how the label was understood -- check it against
    the panel, especially when the values came from a photo.

    When no solution exists the response names an irreducible conflicting set:
    constraints that cannot hold together, from which removing any one makes
    the rest satisfiable. Common fixes, in order of likelihood:
      * an ingredient carrying something the declared list omits (salt is the
        usual one) -- add it to `ingredients`
      * a base food that's the wrong variant (salted vs unsalted, refined vs
        crude oil) -- try a different food_id, or use `overrides`
      * a label whose sub-fractions disagree with the database entry (fibre vs
        total carbohydrate for legumes) -- drop it via `exclude`

    Args:
        label: Printed amounts, keyed by nutrient name or canonical id, in the
            units the panel uses (kcal, g, mg). E.g.
            {"calories": 210, "fat": 18, "protein": 7, "sodium": 25}.
        ingredients: In the order declared on the package, heaviest first. Each
            entry is {"food_id": 451654} to fetch a Cronometer food, or
            {"name": ..., "per_100g": {...}} to supply a profile directly.
            Add "overrides": {"saturated_fat": 40} to adjust a fetched profile,
            and "name" to relabel it.
        basis_g: Grams the panel describes -- the serving or container weight.
            Convert from ounces if the panel gives only those (1 oz = 28.35 g).
        percent_dv: Nutrients declared only as a percent of Daily Value, e.g.
            {"calcium": 2}. Much weaker constraints than printed amounts. Omit
            protein here: its %DV is quality-corrected and can't be inverted.
        exclude: Nutrients to leave out of the fit but still report, by name or
            id. Energy is always excluded and used as a cross-check.
        respect_order: Enforce that each ingredient weighs at least as much as
            the next, as declaration rules require. Turn off when the list
            groups components together, e.g. "Cocoa Beans (Mass + Butter)".
        total_mode: "eq" if the ingredients account for the whole basis mass,
            "max" if something unmodelled is present (brine, glaze), "free" to
            leave mass unconstrained.
        regime: Labelling jurisdiction. "us_fda" today.
    """
    try:
        registry = load_registry()
        parsed = [_build_ingredient(spec, registry) for spec in ingredients]
        reading = read_panel(
            Label(dict(label), basis_g=basis_g, percent_dv=dict(percent_dv or {})),
            get_regime(regime),
            registry,
        )

        excluded = set(reading.derived_keys)
        for key in exclude or []:
            nid = registry.resolve_id(key)
            if nid is None:
                raise KeyError(f"unknown nutrient in exclude: {key!r}")
            excluded.add(nid)

        solution = solve(
            parsed,
            reading.intervals,
            basis_g=reading.basis_g,
            respect_order=respect_order,
            total_mode=total_mode,
            exclude=excluded,
        )

        def named(nid: int) -> str:
            return registry.name_for(nid)

        understood = {
            named(nid): {"low": _round(lo, 4), "high": _round(hi, 4)}
            for nid, (lo, hi) in sorted(reading.intervals.items())
        }
        checks = {
            named(nid): {
                "residual": _round(r, 4),
                "inside_band": bool(abs(r) < 1e-6),
                "supplied_by_an_ingredient": any(
                    nid in ing.per_100g for ing in parsed
                ),
            }
            for nid, r in sorted(solution.residuals.items())
        }

        result: dict[str, Any] = {
            "status": "success",
            "feasible": bool(solution.feasible),
            "label_as_understood": understood,
            "basis_g": reading.basis_g,
            "weights_g": {
                name: {
                    "grams": _round(w, 3),
                    "percent": _round(100 * w / sum(solution.weights_g.values()), 2),
                    # NaN when the polytope was empty and we fell back to
                    # best-fit: there's no feasible range to report.
                    "range_g": [
                        None if math.isnan(lo) else _round(lo, 3),
                        None if math.isnan(hi) else _round(hi, 3),
                    ],
                }
                for (name, w), (lo, hi) in zip(
                    solution.weights_g.items(), solution.ranges_g.values()
                )
            },
            "label_check": checks,
            "notes": [*reading.notes, *solution.notes],
        }

        # The reconstructed profile is the deliverable, but it's ~40% of the
        # response and it is meaningless when the solve failed -- those weights
        # are a best fit to constraints that cannot all hold. Withholding it on
        # failure keeps the iterate-until-it-closes loop cheap and stops a
        # number that shouldn't be trusted from being copied onward.
        if solution.feasible:
            result["reconstructed_per_100g"] = {
                named(nid): _round(v, 4)
                for nid, v in sorted(solution.reconstructed.rebased(100.0).items())
            }
        else:
            result["reconstructed_per_100g"] = None
            result["reconstruction_withheld"] = (
                "no solution exists, so the fitted weights are a best fit rather "
                "than an answer; resolve the conflict and call again"
            )

        if not solution.feasible:
            conflict = find_conflict(
                parsed,
                reading.intervals,
                basis_g=reading.basis_g,
                respect_order=respect_order,
                total_mode=total_mode,
                exclude=excluded,
            )
            if conflict is not None:
                result["conflict"] = {
                    "nutrients": [named(nid) for nid in conflict.nutrient_ids],
                    "explanation": (
                        "These constraints cannot hold together at this basis "
                        "mass; removing any one makes the rest satisfiable. The "
                        "basis mass and ingredient order are always in force and "
                        "may be part of the conflict without being listed."
                    ),
                }
        return json.dumps(result, indent=2)
    except CronometerUnavailableError as exc:
        return _err(exc)
    except Exception as exc:  # noqa: BLE001 - tools return errors, never raise
        return _err(exc)


def main() -> None:
    """Run over stdio. HTTP exposure belongs behind an authenticating proxy."""
    from dotenv import find_dotenv, load_dotenv

    dotenv_path = find_dotenv(usecwd=True)
    if dotenv_path:
        load_dotenv(dotenv_path, override=False)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
