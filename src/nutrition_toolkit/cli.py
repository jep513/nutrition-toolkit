"""Command line: deformulate a recipe from its label.

    python -m nutrition_toolkit examples/sardines.yaml
    python -m nutrition_toolkit spec.json --json    # emit only the payload

Spec format (YAML or JSON):

    name: Sardines in olive oil (tin)
    basis_g: 113            # optional known net/drained weight
    serving_g: 113          # optional
    respect_order: true     # ingredients are listed heaviest-first
    total_mode: eq          # eq | max | free
    regime: us_fda          # labelling jurisdiction
    ingredients:
      - name: sardines (raw)
        per_100g: {protein: 24.6, fat: 11.5, sodium: 90, calcium: 46, epa: 0.47}
      - name: olive oil
        per_100g: {fat: 100.0, sodium: 2, vitamin_e: 14.35}
      - name: salt
        per_100g: {sodium: 38758}
    label:                  # printed panel for the basis
      protein: 22
      fat: 32
      sodium: 550
"""

from __future__ import annotations

import argparse
import json
import math
import sys

from . import Ingredient, Label, solve_label
from .adapters import ADAPTERS, DEFAULT_ADAPTER, get_adapter
from .labels import get_regime


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith((".yaml", ".yml")):
        import yaml

        return yaml.safe_load(text)
    return json.loads(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Back out ingredient weights from a nutrition label."
    )
    ap.add_argument("spec", help="YAML or JSON recipe spec")
    ap.add_argument("--json", action="store_true", help="print only the payload")
    ap.add_argument(
        "--adapter",
        default=DEFAULT_ADAPTER,
        choices=sorted(ADAPTERS),
        help="which tracker to shape the output for",
    )
    args = ap.parse_args(argv)

    d = _load(args.spec)
    ingredients = [
        Ingredient(i["name"], {k: float(v) for k, v in i["per_100g"].items()})
        for i in d["ingredients"]
    ]
    label = Label(
        values={k: float(v) for k, v in d["label"].items()}, basis_g=d.get("basis_g")
    )
    sol = solve_label(
        ingredients,
        label,
        regime=get_regime(d.get("regime", "us_fda")),
        respect_order=d.get("respect_order", True),
        total_mode=d.get("total_mode", "eq" if d.get("basis_g") else "free"),
        use_energy=d.get("use_energy", False),
    )

    payload = get_adapter(args.adapter)(
        d.get("name", "Custom recipe"), sol, d.get("serving_g")
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"# {d.get('name', 'Custom recipe')}")
    print(f"feasible: {sol.feasible}")
    for n in sol.notes:
        print(f"note: {n}")
    print("\nweights (g):")
    for name, w in sol.weights_g.items():
        lo, hi = sol.ranges_g[name]
        # Ranges are NaN when the polytope was empty and we fell back to best-fit.
        rng = "" if math.isnan(lo) else f"   range [{lo:.2f}, {hi:.2f}]"
        print(f"  {name:24s} {w:8.2f}{rng}")
    off = {k: round(v, 3) for k, v in sol.residuals.items() if abs(v) > 1e-6}
    # ASCII only: this lands on a cp1252 console under Windows.
    print(f"\nlabel misses (outside band): {off or 'none - all nutrients inside rounding'}")
    print(f"\n{args.adapter} payload:")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
