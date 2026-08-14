"""The adapter boundary: canonical ids/units in, tracker-specific ids/units out.

These are the tests that keep the IU trap closed. Everything inside the toolkit
is canonical; Cronometer's quirks (vitamin D in IU, invented ids for nutrients
with no USDA number) live here and nowhere else.
"""

import pytest

from nutrition_toolkit.adapters import from_cronometer_food, to_cronometer_nutrients
from nutrition_toolkit.nutrients import NutrientVector, load_registry

REG = load_registry()

PROTEIN, VITAMIN_D, VITAMIN_A, VITAMIN_E = 203, 324, 320, 323
NET_CARBS, OXALATE = 900001, 900012
CRONO_NET_CARBS, CRONO_OXALATE = -1205, 10012


def test_ids_are_remapped_to_cronometer():
    """Nutrients with no USDA number carry toolkit ids internally and
    Cronometer's invented ids on the way out."""
    out, _ = to_cronometer_nutrients({PROTEIN: 10.0, NET_CARBS: 5.0, OXALATE: 12.0})

    assert out[PROTEIN] == 10.0  # USDA-numbered: unchanged
    assert out[CRONO_NET_CARBS] == 5.0
    assert out[CRONO_OXALATE] == 12.0
    assert NET_CARBS not in out


def test_vitamin_d_converts_to_iu_on_the_way_out():
    """Canonical ug -> Cronometer IU, exactly 40 per ug, and the conversion is
    recorded rather than done silently."""
    out, notes = to_cronometer_nutrients({VITAMIN_D: 10.0})

    assert out[VITAMIN_D] == pytest.approx(400.0)
    assert any("Vitamin D" in n and "IU" in n for n in notes)


def test_vitamin_d_converts_back_on_the_way_in():
    food = {"nutrients": [{"id": VITAMIN_D, "amount": 400.0}]}

    profile = from_cronometer_food(food)

    assert profile[VITAMIN_D] == pytest.approx(10.0)
    assert profile.basis_g == 100.0


def test_round_trip_through_cronometer_preserves_amounts():
    original = {PROTEIN: 24.6, VITAMIN_D: 4.825, NET_CARBS: 3.0}

    out, _ = to_cronometer_nutrients(original)
    back = from_cronometer_food(
        {"nutrients": [{"id": k, "amount": v} for k, v in out.items()]}
    )

    for nid, amount in original.items():
        assert back[nid] == pytest.approx(amount)


def test_ambiguous_iu_nutrients_are_skipped_not_guessed():
    """Vitamins A and E have no single IU factor. Since Cronometer stores them
    in mass units anyway there's nothing to convert -- but if that ever
    changed, the adapter would drop them with a note rather than invent a
    number."""
    out, _ = to_cronometer_nutrients({VITAMIN_A: 150.0, VITAMIN_E: 2.4})

    # both are mass-unit on both sides today, so they pass straight through
    assert out[VITAMIN_A] == 150.0
    assert out[VITAMIN_E] == 2.4


def test_unregistered_ids_pass_through_with_a_note():
    """Cronometer may know a nutrient the registry doesn't. Carrying it beats
    dropping data we can't interpret."""
    out, notes = to_cronometer_nutrients({PROTEIN: 10.0, 987654: 1.5})

    assert out[987654] == 1.5
    assert any("987654" in n for n in notes)

    back = from_cronometer_food({"nutrients": [{"id": 987654, "amount": 1.5}]})
    assert back[987654] == 1.5


def test_from_cronometer_food_ignores_malformed_rows():
    food = {
        "nutrients": [
            {"id": PROTEIN, "amount": 24.6},
            {"id": None, "amount": 1.0},
            {"id": 205},
            "not a mapping",
        ]
    }

    profile = from_cronometer_food(food)

    assert dict(profile) == {PROTEIN: 24.6}


def test_custom_food_payload_is_keyed_for_the_mcp():
    from nutrition_toolkit import Ingredient, Label, solve_label
    from nutrition_toolkit.adapters import to_cronometer_custom_food

    sol = solve_label(
        [Ingredient("a", {"protein": 20, "net_carbs": 4})],
        Label({"protein": 10}, basis_g=50),
        respect_order=False,
    )

    payload = to_cronometer_custom_food("test", sol, serving_g=50)

    assert payload["nutrients"][CRONO_NET_CARBS] > 0
    assert payload["basis_grams"] == pytest.approx(50.0, abs=1.0)
    assert payload["servings_in_basis"] == pytest.approx(1.0, abs=0.05)


def test_vector_helpers_survive_the_adapter():
    vec = NutrientVector({PROTEIN: 20.0}, basis_g=200.0)

    out, _ = to_cronometer_nutrients(vec.rebased(100.0))

    assert out[PROTEIN] == pytest.approx(10.0)
