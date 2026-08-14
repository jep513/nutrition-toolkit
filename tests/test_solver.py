import pytest

from nutrition_toolkit import Ingredient, Label, solve_label
from nutrition_toolkit.labels import US_FDA, read_panel
from nutrition_toolkit.nutrients import load_registry
from nutrition_toolkit.recipe_deformulation import solve

REG = load_registry()

ENERGY, PROTEIN, FAT, CARBS = 208, 203, 205, 205
SODIUM, CALCIUM = 307, 301
EPA, VITAMIN_D, MUFA = 629, 324, 645


def test_label_interval_inversion():
    # protein 22 g uses the >5 g rule (nearest 1 g) -> [21.5, 22.5]
    assert US_FDA.interval(REG["protein"], 22) == (21.5, 22.5)
    # sodium 550 mg uses the >140 rule (nearest 10) -> [545, 555]
    assert US_FDA.interval(REG["sodium"], 550) == (545.0, 555.0)
    # small fat 3 g uses the <=5 rule (nearest 0.5) -> [2.75, 3.25]
    assert US_FDA.interval(REG["fat"], 3) == (2.75, 3.25)
    # calories 380 -> nearest 10 -> [375, 385]
    assert US_FDA.interval(REG["calories"], 380) == (375.0, 385.0)


def test_rounding_class_comes_from_the_unit_not_the_name():
    """Registry-driven classification: sodium is mg because the registry says
    so, not because the string contains 'sodium'."""
    assert US_FDA.classify(REG["sodium"]) == "mg_mineral"
    assert US_FDA.classify(REG["cholesterol"]) == "mg_mineral"  # mg, not a mineral
    assert US_FDA.classify(REG["protein"]) == "gram_macro"
    assert US_FDA.classify(REG["calories"]) == "energy"
    # ug nutrients have their own 101.9 increments, not yet encoded
    assert US_FDA.classify(REG["folate"]) == "generic"
    assert US_FDA.classify(None) == "generic"


def test_read_panel_resolves_names_to_ids():
    reading = read_panel(Label({"calories": 380, "protein": 22}, basis_g=113))

    assert reading.intervals[PROTEIN] == (21.5, 22.5)
    assert reading.derived_keys == frozenset({ENERGY})
    assert reading.basis_g == 113
    assert any("us_fda" in n for n in reading.notes)


def test_panel_accepts_ids_directly():
    by_name = read_panel(Label({"protein": 22}, basis_g=100))
    by_id = read_panel(Label({PROTEIN: 22}, basis_g=100))

    assert by_name.intervals == by_id.intervals


def test_unknown_nutrient_name_raises_with_a_suggestion():
    with pytest.raises(KeyError, match="proteinn"):
        read_panel(Label({"proteinn": 22}, basis_g=100))

    with pytest.raises(KeyError, match="did you mean"):
        Ingredient("typo", {"stodium": 90})


def test_roundtrip_recovery_within_ranges():
    sardine = Ingredient("sardine", {"protein": 24.6, "fat": 11.5, "sodium": 90})
    oil = Ingredient("oil", {"fat": 100.0, "sodium": 2})
    salt = Ingredient("salt", {"sodium": 38758})
    ings = [sardine, oil, salt]
    true = {"sardine": 90.0, "oil": 22.0, "salt": 1.2}
    basis = sum(true.values())

    panel = {}
    for nid, step in ((PROTEIN, 1), (FAT, 1), (SODIUM, 10)):
        v = sum(i.amount(nid, true[i.name]) for i in ings)
        panel[nid] = round(v / step) * step

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
    assert EPA in sol.reconstructed
    assert sol.reconstructed[EPA] > 0


def test_reconstruction_is_a_nutrient_vector_on_the_solved_basis():
    """The output is a profile the derive/ tools can consume directly, with the
    basis set to the solved total mass rather than assumed to be 100 g."""
    a = Ingredient("a", {"protein": 20})
    b = Ingredient("b", {"fat": 100})

    sol = solve_label(
        [a, b], Label({"protein": 10, "fat": 50}, basis_g=100), respect_order=False
    )

    assert sol.reconstructed.basis_g == pytest.approx(100.0, abs=1.0)
    per_100g = sol.reconstructed.rebased(100.0)
    assert per_100g[PROTEIN] == pytest.approx(10.0, abs=0.5)


def test_named_views_are_available_for_humans():
    sol = solve_label(
        [Ingredient("a", {"protein": 20})],
        Label({"protein": 10}, basis_g=50),
        respect_order=False,
    )

    assert "Protein" in sol.reconstructed_named()
    assert "Protein" in sol.residuals_named()


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
    assert abs(sol.residuals[SODIUM]) > 0


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
        {PROTEIN: (9.5, 10.5), FAT: (49.5, 50.5)},
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
    label = Label({"protein": 10, "fat": 50, "calories": 9999}, basis_g=100)

    sol = solve_label([a, b], label, respect_order=False, total_mode="eq")

    # The impossible energy figure did not make the macro fit infeasible...
    assert sol.feasible
    # ...but it is reported, and badly missed.
    assert abs(sol.residuals[ENERGY]) > 1000
