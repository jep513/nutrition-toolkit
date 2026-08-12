from nutrition_toolkit import Ingredient, Label, solve_label
from nutrition_toolkit.labels import US_FDA, read_panel
from nutrition_toolkit.recipe_deformulation import solve


def test_label_interval_inversion():
    # protein 22 g uses the >5 g rule (nearest 1 g) -> [21.5, 22.5]
    assert US_FDA.interval("protein", 22) == (21.5, 22.5)
    # sodium 550 mg uses the >140 rule (nearest 10) -> [545, 555]
    assert US_FDA.interval("sodium", 550) == (545.0, 555.0)
    # small fat 3 g uses the <=5 rule (nearest 0.5) -> [2.75, 3.25]
    assert US_FDA.interval("fat", 3) == (2.75, 3.25)
    # calories 380 -> nearest 10 -> [375, 385]
    assert US_FDA.interval("calories", 380) == (375.0, 385.0)


def test_read_panel_marks_energy_derived():
    """Energy is flagged so callers can keep it out of the fit and use it as a
    cross-check; the macros are not."""
    reading = read_panel(Label({"calories": 380, "protein": 22}, basis_g=113))

    assert reading.derived_keys == frozenset({"calories"})
    assert reading.intervals["protein"] == (21.5, 22.5)
    assert reading.basis_g == 113


def test_roundtrip_recovery_within_ranges():
    sardine = Ingredient("sardine", {"protein": 24.6, "fat": 11.5, "sodium": 90})
    oil = Ingredient("oil", {"fat": 100.0, "sodium": 2})
    salt = Ingredient("salt", {"sodium": 38758})
    ings = [sardine, oil, salt]
    true = {"sardine": 90.0, "oil": 22.0, "salt": 1.2}
    basis = sum(true.values())

    panel = {}
    for nut, step in (("protein", 1), ("fat", 1), ("sodium", 10)):
        v = sum(i.per_100g.get(nut, 0) * true[i.name] / 100 for i in ings)
        panel[nut] = round(v / step) * step

    sol = solve_label(ings, Label(panel, basis_g=basis), respect_order=True, total_mode="eq")
    assert sol.feasible
    for name, w in true.items():
        lo, hi = sol.ranges_g[name]
        assert lo - 1e-6 <= w <= hi + 1e-6, (name, w, lo, hi)
        assert abs(sol.weights_g[name] - w) < 1.0
    assert all(abs(r) < 1e-6 for r in sol.residuals.values())


def test_reconstructs_unlabelled_nutrients():
    a = Ingredient("a", {"protein": 20, "epa": 0.5})
    b = Ingredient("b", {"protein": 0, "fat": 100})
    sol = solve_label(
        [a, b],
        Label({"protein": 10, "fat": 50}, basis_g=100),
        respect_order=False,
        total_mode="eq",
    )
    # epa only comes from ingredient a; it must appear in the reconstruction
    assert "epa" in sol.reconstructed
    assert sol.reconstructed["epa"] > 0


def test_infeasible_flags_culprit():
    # sodium far beyond what any weighting of these ingredients can supply
    a = Ingredient("a", {"protein": 20, "sodium": 10})
    b = Ingredient("b", {"fat": 100, "sodium": 5})
    sol = solve_label(
        [a, b],
        Label({"protein": 10, "fat": 50, "sodium": 9000}, basis_g=100),
        respect_order=False,
        total_mode="eq",
    )
    assert not sol.feasible
    assert abs(sol.residuals["sodium"]) > 0


# ---------------------------------------------------------------------------
# The labels/solver seam: the solver takes intervals, not labels.
# ---------------------------------------------------------------------------


def test_solve_accepts_bare_intervals():
    """No Label involved -- intervals can come from anywhere (another regime,
    a lab assay, a hand-written tolerance)."""
    a = Ingredient("a", {"protein": 20})
    b = Ingredient("b", {"fat": 100})

    sol = solve(
        [a, b],
        {"protein": (9.5, 10.5), "fat": (49.5, 50.5)},
        basis_g=100,
        respect_order=False,
    )

    assert sol.feasible
    assert abs(sol.weights_g["a"] - 50.0) < 1.0
    assert abs(sol.weights_g["b"] - 50.0) < 1.0


def test_excluded_nutrient_still_reports_residual():
    """Energy is kept out of the fit but still checked -- that's what makes it
    a cross-check rather than dead weight."""
    a = Ingredient("a", {"protein": 20, "calories": 80})
    b = Ingredient("b", {"fat": 100, "calories": 900})
    label = Label(
        {"protein": 10, "fat": 50, "calories": 9999}, basis_g=100
    )  # energy wildly wrong

    sol = solve_label([a, b], label, respect_order=False, total_mode="eq")

    # The impossible energy figure did not make the macro fit infeasible...
    assert sol.feasible
    # ...but it is reported, and badly missed.
    assert abs(sol.residuals["calories"]) > 1000
