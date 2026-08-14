# nutrition-toolkit

Back out the **gram weight of each ingredient** in a packaged food from two things every label already gives you: the **ordered ingredient list** and the **nutrition panel**. Rebuild the item in Cronometer as a recipe of real database foods, and you inherit the full micronutrient and fatty-acid profile the label never prints.

Example: a tin of *sardines, olive oil, salt* with a panel showing protein / fat / sodium → solved weights of each component → a Cronometer recipe that now also carries calcium, vitamin D, EPA, DHA, vitamin E, and the rest.

## What's here

| Package | Does |
|---|---|
| `nutrients/` | Canonical nutrient registry: ids, units, solubility, mass/energy roles, and how nutrients aggregate into one another |
| `labels/` | Turns a printed panel into true-value intervals, per jurisdiction (`regimes/us_fda.py` today; EU/Canada/AU-NZ are the natural next ones) |
| `recipe_deformulation/` | Takes intervals + per-100 g ingredient profiles, returns gram weights with honest ranges, plus the reconstructed profile as a `NutrientVector` |
| `adapters/` | Per-app I/O shaping. The only place any nutrition tracker is named |

The subpackages don't import each other. `labels` produces `nutrient id -> (low, high)`;
`recipe_deformulation` consumes it and has no notion of a label, so intervals can
equally come from another regime, a lab assay, or a hand-written tolerance.
`nutrition_toolkit.solve_label` is the wiring.

Nutrient identity is integer ids, not names -- specs and Python calls accept
friendly names (`protein`, `epa`, `vitamin_d`) and resolve them through the
registry, raising with a suggestion on a typo rather than silently carrying it. Ids below 1000 follow USDA SR/FDC
numbering (which Cronometer adopted); ids from 900001 are toolkit-assigned for
nutrients with no settled USDA number. A `NutrientVector` is **always** in each
nutrient's canonical unit -- conversion happens at the edges, so IU/mass mix-ups
can't propagate inward. Vitamin D converts cleanly (40 IU/ug); vitamins A and E
*refuse* to convert, because their IU factor depends on the chemical form.

Planned: `derive/` -- retention/yield transforms, per-nutrient overrides, and
re-deriving a food when its base changes.

## Why it's not just "solve Ax = b"

Three realities make a naive linear solve either false-precise or spuriously unsolvable, and this tool handles all three:

- **Labels are rounded.** Under FDA rules (21 CFR 101.9) a printed "22 g protein" means the true value is somewhere in `[21.5, 22.5)`. Every printed number is really an interval. The solver inverts the rounding and treats each nutrient as `low ≤ amount ≤ high` instead of an equality.
- **The ingredient list is ordered.** Regulations require descending weight, so `w₁ ≥ w₂ ≥ … ≥ wₙ` is free information that often makes an otherwise ambiguous system identifiable.
- **The total mass is usually known** (net or drained weight), giving a strong `Σw = basis` constraint.

Together these define a **polytope** of feasible weight vectors. The tool tests feasibility, returns one representative point, **and reports the min/max of every weight over that polytope** — so when two ingredients are hard to distinguish, you see the honest range instead of trusting a made-up number. Calories are excluded from the fit by default (they're derived from the macros) and reported as a cross-check.

If the polytope is empty, that's a signal — usually an unlisted component (water, brine, glaze) or a mismatched base food — and the tool falls back to a best-fit and tells you which nutrient it couldn't satisfy.

## Install

```bash
pip install -e ".[cli]"     # from a clone
```

Requires Python ≥ 3.10, numpy, scipy (pyyaml for the CLI).

## Use it — CLI

```bash
recipe-deformulate examples/sardines.yaml
recipe-deformulate spec.json --json      # emit only the Cronometer payload
```

A spec is YAML or JSON:

```yaml
name: Sardines in olive oil (tin)
basis_g: 113            # known net/drained weight (optional but strong)
serving_g: 113
respect_order: true     # ingredients listed heaviest-first
total_mode: eq          # eq | max | free
regime: us_fda          # labelling jurisdiction
ingredients:
  - name: sardines (raw)
    per_100g: {protein: 24.6, fat: 11.5, sodium: 90, calcium: 46, epa: 0.47, dha: 0.51}
  - name: olive oil
    per_100g: {fat: 100.0, sodium: 2, vitamin_e: 14.35}
  - name: salt
    per_100g: {sodium: 38758}
label:                  # the printed panel, for the basis mass
  protein: 22
  fat: 32
  sodium: 550
```

Output includes the solved weights with feasible ranges, any nutrient that lands outside its rounding band, the reconstructed full profile, and a payload ready for the Cronometer MCP.

## Use it — library

```python
from nutrition_toolkit import Ingredient, Label, solve_label, to_cronometer_custom_food

sol = solve_label(ingredients, Label(panel, basis_g=113))
print(sol.weights_g, sol.ranges_g)
payload = to_cronometer_custom_food("Sardines in olive oil", sol, serving_g=113)
```

## Wiring it to Cronometer

Get the ingredient profiles and push the result through the community Cronometer MCP server ([`rwestergren/cronometer-api-mcp`](https://github.com/rwestergren/cronometer-api-mcp)):

1. **Pull each base ingredient** from Cronometer's database with `get_food_details`, so the micros/fatty acids carried through are exactly the ones Cronometer will display. Put those per-100 g numbers in the spec.
2. **Solve** to get gram weights.
3. **Log it**, either way:
   - *As a recipe* — add each base food at its solved gram weight in Cronometer; Cronometer computes every nutrient. Best fidelity.
   - *As one custom food* — hand `to_cronometer_custom_food(...)` to the MCP's `add_custom_food`; the reconstructed profile already contains the micros/FA. Fully scriptable.

## The self-validating example

`examples/sardines.py` picks true weights, forward-computes the panel, rounds it FDA-style, then recovers the weights from the rounded panel alone — recovering 90 / 22 / 1.2 g to within a fraction of a gram, each inside a tight feasible range. Run it:

```bash
python examples/sardines.py
```

## Caveats worth reading

- **Base foods must be the ingredient "as added"** — plain raw sardine, not the canned+salted product — or you double-count salt and oil.
- **Drained vs total.** For packed-in-oil items, decide whether you're modelling the drained contents or the whole tin, and set `basis_g` to match; `total_mode: max` allows an unmodelled liquid.
- **Collinear ingredients** (e.g. two similar oils) widen the feasible ranges — that's the tool being honest, not failing.
- Estimates are only as good as the base-food profiles and the label's precision.

## License

MIT. Contributions welcome — more label-rounding classes, a USDA/Cronometer profile fetcher, and a recipe-import writer are all natural next steps.
