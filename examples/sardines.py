"""Worked example: a tin of sardines (sardines, olive oil, salt).

This example is *self-validating*. We pick real per-100 g profiles and a set of
true weights, forward-compute the panel, round it with the same FDA rules the
solver inverts, then let the solver recover the weights from the rounded panel
only. That proves the method without needing a real tin in hand — swap in a real
label and real Cronometer/USDA ingredient profiles to use it for real.

Profiles below are illustrative (approx. USDA FDC values per 100 g). For actual
use, pull each ingredient from Cronometer via the MCP's get_food_details so the
carried micros/fatty acids are the same ones Cronometer will show.
"""
from nutrition_toolkit import Ingredient, Label, solve_label, to_cronometer_custom_food
from nutrition_toolkit.labels import US_FDA

# --- per-100 g profiles (illustrative) --------------------------------------
sardine = Ingredient("sardines (raw)", {
    "calories": 208, "protein": 24.6, "fat": 11.5, "carbs": 0.0, "sodium": 90,
    # micros / fatty acids the label never prints but Cronometer tracks:
    "calcium": 46, "vitamin_d_iu": 193, "epa": 0.47, "dha": 0.51,
})
olive_oil = Ingredient("olive oil", {
    "calories": 884, "protein": 0.0, "fat": 100.0, "carbs": 0.0, "sodium": 2,
    "vitamin_e": 14.35, "oleic": 71.0,
})
salt = Ingredient("salt", {
    "calories": 0, "protein": 0.0, "fat": 0.0, "carbs": 0.0, "sodium": 38758,
})

ingredients = [sardine, olive_oil, salt]

# --- ground truth we pretend not to know ------------------------------------
true_w = {"sardines (raw)": 90.0, "olive oil": 22.0, "salt": 1.2}
basis = sum(true_w.values())

# forward-compute the true panel, then round it FDA-style to make the label
raw_panel = {}
for nut in ["calories", "protein", "fat", "carbs", "sodium"]:
    raw_panel[nut] = sum(ing.per_100g.get(nut, 0) * true_w[ing.name] / 100 for ing in ingredients)

def fda_round(nut, v):
    # emulate the printed value: round to the class step
    cls = US_FDA.classify(nut)
    if cls == "energy":
        step = 5 if v <= 50 else 10
    elif cls == "gram_macro":
        step = 0.5 if v <= 5 else 1
    elif cls == "mg_mineral":
        step = 5 if v <= 140 else 10
    else:
        step = 1
    return round(v / step) * step

label_values = {nut: fda_round(nut, v) for nut, v in raw_panel.items()}
label = Label(values=label_values, basis_g=basis)

print("True weights (g):        ", {k: round(v, 2) for k, v in true_w.items()})
print("True panel (unrounded):  ", {k: round(v, 1) for k, v in raw_panel.items()})
print("Printed label (rounded): ", label_values)
print("Basis mass (g):          ", round(basis, 2))
print("-" * 66)

sol = solve_label(ingredients, label, respect_order=True, total_mode="eq")

print("Feasible:", sol.feasible)
print("Recovered weights (g):")
for name, w in sol.weights_g.items():
    lo, hi = sol.ranges_g[name]
    print(f"  {name:16s} {w:7.2f}   feasible range [{lo:6.2f}, {hi:6.2f}]")
print("Residual vs label band:  ", {k: round(v, 3) for k, v in sol.residuals.items()})
print("-" * 66)
print("Reconstructed micros/FA the label never listed:")
for k in ["calcium", "vitamin_d_iu", "epa", "dha", "vitamin_e", "oleic"]:
    if k in sol.reconstructed:
        print(f"  {k:16s} {sol.reconstructed[k]:8.2f}")
print("-" * 66)
print("MCP custom-food payload:")
import json

print(json.dumps(to_cronometer_custom_food("Sardines in olive oil (tin)", sol, serving_g=basis), indent=2))
