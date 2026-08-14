import json
from importlib import resources

import pytest

from nutrition_toolkit.nutrients import (
    NutrientVector,
    UnitConversionError,
    load_registry,
)

REG = load_registry()

# Canonical ids used below, by name so the intent survives an id change.
PROTEIN, FAT, CARBS, FIBER, ALCOHOL = 203, 204, 205, 291, 221
VITAMIN_A, RETINOL = 320, 319
BETA_CAROTENE, ALPHA_CAROTENE, CRYPTOXANTHIN, LYCOPENE = 321, 322, 334, 337
VITAMIN_D, VITAMIN_E = 324, 323
SUGAR_ALCOHOL = 900007


# ---------------------------------------------------------------------------
# Data integrity -- the registry is hand-maintained, so guard the invariants
# an editor could plausibly break.
# ---------------------------------------------------------------------------


def _raw() -> dict:
    text = (
        resources.files("nutrition_toolkit.nutrients.data")
        .joinpath("nutrients.json")
        .read_text("utf-8")
    )
    return json.loads(text)


def test_ids_and_aliases_are_unique():
    entries = _raw()["nutrients"]
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == len(ids)

    aliases = [a for e in entries for a in e.get("aliases", [])]
    assert len(set(aliases)) == len(aliases)


def test_every_contribution_target_exists():
    entries = _raw()["nutrients"]
    known = {e["id"] for e in entries}
    for entry in entries:
        for contribution in entry.get("contributes_to", []):
            assert contribution["id"] in known, (entry["id"], contribution)


def test_units_are_canonical_ascii():
    """No stray micro signs: 'ug', not 'µg'. Keeps the file safe to read on a
    cp1252 console and stable to diff."""
    units = {e["unit"] for e in _raw()["nutrients"]}
    assert units <= {"g", "mg", "ug", "kcal", "IU"}, units


def test_energy_terms_reference_known_nutrients():
    doc = _raw()
    known = {e["id"] for e in doc["nutrients"]}
    for term in doc["energy"]["terms"]:
        assert term["id"] in known, term


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def test_lookup_by_id_alias_and_name():
    assert REG[BETA_CAROTENE].name == "Beta-carotene"
    assert REG["beta_carotene"].id == BETA_CAROTENE
    assert REG["Beta-carotene"].id == BETA_CAROTENE  # name, normalized
    assert REG["EPA"].id == 629  # case-insensitive alias


def test_unknown_lookup_is_none_not_an_error():
    assert REG.get("unobtainium") is None
    assert REG.resolve_id("unobtainium") is None
    with pytest.raises(KeyError):
        REG["unobtainium"]


def test_selections_used_by_transforms():
    fat_soluble = REG.ids_where(solubility="fat")
    # the ones that must leave with rendered fat
    for nid in (VITAMIN_A, VITAMIN_D, VITAMIN_E, 430, 601, BETA_CAROTENE):
        assert nid in fat_soluble
    # ...and the ones that must not
    for nid in (PROTEIN, 401, 307):
        assert nid not in fat_soluble

    assert REG.ids_where(mass_component=True) == frozenset(
        {PROTEIN, FAT, CARBS, 207, ALCOHOL, 255}
    )


# ---------------------------------------------------------------------------
# Units -- the trap this registry exists to close
# ---------------------------------------------------------------------------


def test_vitamin_d_iu_round_trip():
    """Vitamin D is exactly 40 IU per ug, so the conversion is safe to do."""
    vit_d = REG[VITAMIN_D]

    assert vit_d.unit == "ug"
    assert vit_d.to_canonical(400, "IU") == 10.0
    assert vit_d.from_canonical(10, "IU") == 400.0


@pytest.mark.parametrize("key", ["vitamin_a", "vitamin_e"])
def test_ambiguous_iu_conversions_refuse(key):
    """A and E have no single IU factor -- it depends on the chemical form.
    Refusing beats inventing a number that's quietly wrong."""
    with pytest.raises(UnitConversionError, match="not well defined"):
        REG[key].to_canonical(1000, "IU")


def test_unconvertible_unit_raises():
    with pytest.raises(UnitConversionError, match="no conversion"):
        REG[PROTEIN].to_canonical(5, "IU")


# ---------------------------------------------------------------------------
# NutrientVector
# ---------------------------------------------------------------------------


def test_vector_is_immutable_and_derives_copies():
    base = NutrientVector({PROTEIN: 10.0, FAT: 5.0}, basis_g=100)

    doubled = base.scaled(2)
    assert doubled[PROTEIN] == 20.0
    assert base[PROTEIN] == 10.0  # original untouched
    assert doubled.basis_g == 100  # scaling doesn't move the basis

    at_250 = base.rebased(250)
    assert at_250[PROTEIN] == 25.0
    assert at_250.basis_g == 250

    patched = base.with_amounts({FAT: 1.0, CARBS: 3.0})
    assert (patched[FAT], patched[CARBS]) == (1.0, 3.0)
    assert CARBS not in base


def test_unknown_ids_are_carried_not_dropped():
    """Databases grow nutrients. Silently dropping one would defeat the sync
    tool, whose whole job is noticing that."""
    vec = NutrientVector({PROTEIN: 10.0, 987654: 1.5})

    assert vec[987654] == 1.5
    assert REG.unknown_ids(vec) == frozenset({987654})
    assert vec.scaled(2)[987654] == 3.0


# ---------------------------------------------------------------------------
# Energy
# ---------------------------------------------------------------------------


def test_energy_uses_two_kcal_per_gram_of_fibre():
    """Carbohydrate is declared inclusive of fibre, so fibre carries a -2.0
    correction against carbs' 4.0 and nets to 2 kcal/g."""
    vec = {PROTEIN: 10.0, FAT: 5.0, CARBS: 20.0, FIBER: 5.0}

    # 4*10 + 9*5 + 4*20 - 2*5
    assert REG.energy_kcal(vec) == pytest.approx(155.0)

    # the same food with the fibre reclassified as non-fibre carbohydrate
    # gains 2 kcal/g of fibre
    no_fibre = {**vec, FIBER: 0.0}
    assert REG.energy_kcal(no_fibre) - REG.energy_kcal(vec) == pytest.approx(10.0)


def test_energy_counts_alcohol_and_sugar_alcohol():
    assert REG.energy_kcal({ALCOHOL: 10.0}) == pytest.approx(70.0)
    # sugar alcohol nets to 2.4 kcal/g against carbs' 4.0
    vec = {CARBS: 10.0, SUGAR_ALCOHOL: 10.0}
    assert REG.energy_kcal(vec) == pytest.approx(40.0 - 16.0)


# ---------------------------------------------------------------------------
# Derived nutrients -- the orange bell pepper
# ---------------------------------------------------------------------------


def _red_bell_pepper() -> NutrientVector:
    """Stand-in for the NCCDB red bell pepper: provitamin-A carotenoids plus
    lycopene, which has no vitamin A activity."""
    return NutrientVector(
        {
            RETINOL: 0.0,
            BETA_CAROTENE: 1200.0,
            ALPHA_CAROTENE: 24.0,
            CRYPTOXANTHIN: 480.0,
            LYCOPENE: 300.0,
            VITAMIN_A: 0.0,  # deliberately stale; recompute must fix it
        }
    )


def test_recompute_derived_rebuilds_vitamin_a_from_carotenoids():
    vec = REG.recompute_derived(_red_bell_pepper())

    # RAE = retinol + beta/12 + alpha/24 + cryptoxanthin/24
    expected = 0 + 1200 / 12 + 24 / 24 + 480 / 24
    assert vec[VITAMIN_A] == pytest.approx(expected, rel=1e-4)


def test_orange_bell_pepper_override_flows_into_vitamin_a():
    """The maintained-variant case: swap lycopene for beta-carotene and vitamin
    A follows, because lycopene contributes nothing and beta-carotene is
    weighted 1/12."""
    red = REG.recompute_derived(_red_bell_pepper())

    orange = REG.recompute_derived(
        red.with_amounts({BETA_CAROTENE: 2400.0, LYCOPENE: 0.0})
    )

    assert orange[LYCOPENE] == 0.0
    # beta-carotene doubled -> its 1/12 contribution doubled, nothing else moved
    assert orange[VITAMIN_A] == pytest.approx(red[VITAMIN_A] + 1200 / 12, rel=1e-4)


def test_recompute_leaves_partial_profiles_alone():
    """With a contributor missing we can't rebuild the total, so the source
    value stands rather than being silently degraded."""
    partial = NutrientVector({BETA_CAROTENE: 1200.0, VITAMIN_A: 999.0})

    assert REG.recompute_derived(partial)[VITAMIN_A] == 999.0
