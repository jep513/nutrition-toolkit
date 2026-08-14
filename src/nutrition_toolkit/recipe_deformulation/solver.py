"""Back out ingredient weights from an ordered ingredient list + nutrient bounds.

The feasible weights form a polytope defined by linear constraints:
  * nutrient intervals :  low_j <= (A w)_j <= high_j
  * non-negativity     :  w_i >= 0
  * ingredient order   :  w_1 >= w_2 >= ... >= w_n   (optional)
  * known total mass   :  sum w = basis            (optional)

We (1) test feasibility, (2) report the min/max of every weight over that
polytope so identifiability is explicit, and (3) return one representative
point. If the polytope is empty we fall back to a best-fit that minimises how
far outside the intervals we land, and report the offending nutrients.

This module takes intervals as input and knows nothing about nutrition labels.
Getting from a printed panel to intervals is `nutrition_toolkit.labels`; the
two are wired together by `nutrition_toolkit.solve_label`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
from scipy.optimize import linprog, minimize

from ..nutrients import NutrientVector
from .models import Ingredient, Solution


def _select_nutrients(ingredients, intervals, exclude):
    keys = []
    for k in intervals:
        if k in exclude:
            continue
        col = [ing.per_100g.get(k, 0.0) for ing in ingredients]
        if any(abs(c) > 0 for c in col):  # at least one ingredient supplies it
            keys.append(k)
    return keys


def _matrix(ingredients, nutrients):
    # A[j, i] = amount of nutrient j per gram of ingredient i
    return np.array(
        [[ing.per_100g.get(n, 0.0) / 100.0 for ing in ingredients] for n in nutrients],
        dtype=float,
    )


def _constraints(A, iv, nutrients, n, respect_order, basis_g, total_mode):
    A_ub, b_ub = [], []
    for j, nut in enumerate(nutrients):
        lo, hi = iv[nut]
        A_ub.append(A[j])
        b_ub.append(hi)  #  A_j w <= hi
        A_ub.append(-A[j])
        b_ub.append(-lo)  # -A_j w <= -lo
    if respect_order:
        for i in range(n - 1):
            row = np.zeros(n)
            row[i + 1] = 1.0
            row[i] = -1.0
            A_ub.append(row)
            b_ub.append(0.0)  # w_{i+1} - w_i <= 0
    A_eq, b_eq = None, None
    if basis_g is not None and total_mode == "eq":
        A_eq = [np.ones(n)]
        b_eq = [basis_g]
    elif basis_g is not None and total_mode == "max":
        A_ub.append(np.ones(n))
        b_ub.append(basis_g)
    return (
        np.array(A_ub),
        np.array(b_ub),
        (np.array(A_eq) if A_eq else None),
        (np.array(b_eq) if b_eq else None),
    )


def solve(
    ingredients: list[Ingredient],
    intervals: Mapping[int, tuple[float, float]],
    *,
    basis_g: float | None = None,
    respect_order: bool = True,
    total_mode: str = "eq",  # "eq" | "max" | "free"
    exclude: Iterable[int] = (),
) -> Solution:
    """Solve for ingredient weights consistent with `intervals`.

    Args:
        ingredients: Components in label order (heaviest first) with per-100 g
            nutrient profiles.
        intervals: canonical nutrient id -> (low, high) bounds on the total
            amount in the basis. Typically `PanelReading.intervals`.
        basis_g: Known total mass, applied per `total_mode`.
        respect_order: Enforce w_1 >= w_2 >= ... (regulated ingredient order).
        total_mode: "eq" (mass known exactly), "max" (mass is an upper bound,
            for an unmodelled component like brine), or "free".
        exclude: Nutrients to drop from the fit but still report residuals for
            -- typically `PanelReading.derived_keys`, i.e. energy.
    """
    n = len(ingredients)
    exclude = frozenset(exclude)
    nutrients = _select_nutrients(ingredients, intervals, exclude)
    if not nutrients:
        raise ValueError("No constrained nutrient overlaps the ingredient profiles.")
    A = _matrix(ingredients, nutrients)
    iv = dict(intervals)
    basis = basis_g if total_mode != "free" else None
    A_ub, b_ub, A_eq, b_eq = _constraints(
        A, iv, nutrients, n, respect_order, basis, total_mode
    )
    bounds = [(0.0, None)] * n
    notes: list[str] = []

    feas = linprog(
        np.zeros(n),
        A_ub=A_ub,
        b_ub=b_ub,
        A_eq=A_eq,
        b_eq=b_eq,
        bounds=bounds,
        method="highs",
    )
    feasible = feas.success

    if feasible:
        ranges = {}
        for i in range(n):
            c = np.zeros(n)
            c[i] = 1.0
            lo = linprog(
                c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs"
            )
            hi = linprog(
                -c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs"
            )
            ranges[ingredients[i].name] = (float(lo.fun), float(-hi.fun))
        # representative point: stay near interval midpoints, feasible by construction
        mids = np.array([(iv[n_]) for n_ in nutrients])
        mid = mids.mean(axis=1)
        half = (mids[:, 1] - mids[:, 0]) / 2
        half[half == 0] = 1.0

        def obj(w):
            r = (A @ w - mid) / half
            return float(r @ r) + 1e-6 * float(w @ w)

        cons = [
            {"type": "ineq", "fun": (lambda w, a=row, b=bv: b - a @ w)}
            for row, bv in zip(A_ub, b_ub)
        ]
        if A_eq is not None:
            cons.append({"type": "eq", "fun": (lambda w: (A_eq @ w - b_eq).ravel())})
        x0 = np.array([np.clip(np.mean(ranges[ing.name]), 0, None) for ing in ingredients])
        res = minimize(
            obj,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=cons,
            options={"maxiter": 500, "ftol": 1e-10},
        )
        w = np.clip(res.x, 0, None)
    else:
        notes.append(
            "Nutrient intervals are jointly infeasible under these ingredients -- "
            "returning best-fit. Check for an unlisted component (water/brine/glaze) "
            "or a mismatched base food."
        )
        ranges = {ing.name: (float("nan"), float("nan")) for ing in ingredients}

        def soft(w):
            y = A @ w
            lo = np.array([iv[n_][0] for n_ in nutrients])
            hi = np.array([iv[n_][1] for n_ in nutrients])
            half = np.maximum((hi - lo) / 2, 1e-9)
            over = np.maximum(0, y - hi) / half
            under = np.maximum(0, lo - y) / half
            return float(over @ over + under @ under)

        cons = []
        if respect_order:
            cons += [
                {"type": "ineq", "fun": (lambda w, i=i: w[i] - w[i + 1])}
                for i in range(n - 1)
            ]
        if basis is not None and total_mode == "eq":
            cons.append({"type": "eq", "fun": (lambda w: np.sum(w) - basis)})
        x0 = np.full(n, (basis or 100.0) / n)
        res = minimize(
            soft,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=cons,
            options={"maxiter": 800, "ftol": 1e-12},
        )
        w = np.clip(res.x, 0, None)

    # residual vs nearest interval edge (0 == inside the band). Excluded
    # nutrients are reported too -- that's what makes energy a cross-check.
    residuals = {}
    for nut, (lo, hi) in iv.items():
        y = sum(ing.amount(nut, w[i]) for i, ing in enumerate(ingredients))
        residuals[nut] = 0.0 if lo <= y <= hi else (y - hi if y > hi else y - lo)

    # full reconstructed profile over every nutrient any ingredient carries
    all_keys = sorted({k for ing in ingredients for k in ing.per_100g})
    total_g = float(np.sum(w))
    reconstructed = NutrientVector(
        {
            k: sum(ing.amount(k, w[i]) for i, ing in enumerate(ingredients))
            for k in all_keys
        },
        basis_g=total_g,
    )
    return Solution(
        feasible=bool(feasible),
        weights_g={ing.name: float(w[i]) for i, ing in enumerate(ingredients)},
        ranges_g=ranges,
        reconstructed=reconstructed,
        residuals=residuals,
        notes=notes,
    )
