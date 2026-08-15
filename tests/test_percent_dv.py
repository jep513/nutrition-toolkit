"""Percent-Daily-Value declarations.

Many panels give vitamin D, calcium, iron and potassium as a bare percentage,
and older-format labels do the same for vitamins A and C. %DV is rounded to
coarser increments than absolute amounts, so it has to widen the interval
rather than pin it -- otherwise the solver treats a vague declaration as a
tight constraint and manufactures precision that isn't there.
"""

import json
from importlib import resources

import pytest

from nutrition_toolkit.labels import US_FDA, Label, read_panel
from nutrition_toolkit.labels.regimes.us_fda import daily_values
from nutrition_toolkit.nutrients import load_registry

REG = load_registry()
CALCIUM, IRON, POTASSIUM, VITAMIN_D, ALLULOSE = 301, 303, 306, 324, 900010
PROTEIN = 203


# ---------------------------------------------------------------------------
# The rounding rule itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("printed", "step"),
    [
        (0, 2.0),
        (2, 2.0),
        (10, 2.0),  # "up to and including the 10-percent level"
        (11, 5.0),
        (50, 5.0),  # "...and up to and including the 50-percent level"
        (51, 10.0),
        (90, 10.0),
    ],
)
def test_percent_dv_increments(printed, step):
    assert US_FDA.percent_dv_step(printed) == step


def test_percent_dv_is_coarser_than_the_absolute_rule():
    """The point of the whole exercise: the same nutrient declared as a
    percentage is a far weaker constraint than one declared in mg."""
    from_pct = US_FDA.percent_dv_interval(REG["calcium"], 2)
    from_mg = US_FDA.interval(REG["calcium"], 26)  # 2% of the 1300 mg DV

    assert from_pct == (13.0, 39.0)  # 1%..3% of 1300
    assert from_mg[1] - from_mg[0] < (from_pct[1] - from_pct[0]) / 5


def test_zero_percent_clamps_at_zero():
    """0% means 'below the smallest increment', not 'negative'."""
    lo, hi = US_FDA.percent_dv_interval(REG["vitamin_d"], 0)

    assert lo == 0.0
    assert hi == pytest.approx(0.2)  # 1% of the 20 ug DV


def test_no_daily_value_returns_none():
    """Allulose has no DV, so a percentage can't be turned into an amount."""
    assert US_FDA.percent_dv_interval(REG["allulose"], 5) is None
    assert US_FDA.percent_dv_interval(None, 5) is None


# ---------------------------------------------------------------------------
# Reading a panel
# ---------------------------------------------------------------------------


def test_percent_only_declaration_becomes_a_wide_band():
    reading = read_panel(
        Label(percent_dv={"calcium": 2, "iron": 6, "potassium": 2}, basis_g=32.3)
    )

    assert reading.intervals[CALCIUM] == (13.0, 39.0)
    assert reading.intervals[IRON] == pytest.approx((0.9, 1.26))
    assert reading.intervals[POTASSIUM] == pytest.approx((47.0, 141.0))


def test_percentage_can_be_tighter_than_the_printed_amount():
    """Not a corner case -- it's what the four mandatory micros do.

    The absolute mg rule collapses to [0, 5] below 5 mg, so "Iron 1mg" says
    almost nothing while "Iron 3%" against an 18 mg DV pins it to 0.36-0.72.
    Intersecting means neither source needs to be declared the winner.
    """
    from_amount = read_panel(Label({"iron": 1})).intervals[IRON]
    from_pct = read_panel(Label(percent_dv={"iron": 3})).intervals[IRON]
    both = read_panel(Label({"iron": 1}, percent_dv={"iron": 3})).intervals[IRON]

    assert from_amount == (0.0, 5.0)
    assert from_pct == pytest.approx((0.36, 0.72))
    assert both == pytest.approx(from_pct)  # the percentage is the sharper one


def test_printed_amount_wins_when_it_is_the_tighter_one():
    """The commoner direction: for calcium and potassium the mg figure is far
    tighter, and intersecting picks it up without a precedence rule."""
    reading = read_panel(
        Label(
            {"calcium": 16, "potassium": 109},
            percent_dv={"calcium": 1, "potassium": 2},
            basis_g=32.3,
        )
    )

    assert reading.intervals[CALCIUM] == (13.5, 18.5)
    assert reading.intervals[POTASSIUM] == (106.5, 111.5)


def test_intersection_can_tighten_the_absolute_band():
    """When the percentage genuinely excludes part of the printed band, the
    result is narrower than either alone."""
    # 140 mg calcium -> [135, 145] under the mg rule.
    # 11% DV -> [8.5%, 13.5%] -> [110.5, 175.5] mg. Overlap: [135, 145].
    # Push the percentage up so it clips the bottom of the mg band:
    # 12% -> [9.5%, 14.5%] -> [123.5, 188.5]; still covers. Use 11% at 130 mg:
    reading = read_panel(Label({"calcium": 130}, percent_dv={"calcium": 11}))

    lo, hi = reading.intervals[CALCIUM]
    assert lo >= 125.0  # mg rule alone would allow 125
    assert hi <= 135.0


def test_contradictory_declarations_are_reported_not_silently_merged():
    """An empty intersection means the panel disagrees with itself. Keep the
    printed amount, but say so."""
    # 16 mg -> [13.5, 18.5]; 20% of 1300 -> [227.5, 292.5]. No overlap.
    reading = read_panel(Label({"calcium": 16}, percent_dv={"calcium": 20}))

    assert reading.intervals[CALCIUM] == (13.5, 18.5)
    assert any("don't overlap" in n for n in reading.notes)


def test_percentage_for_a_nutrient_with_no_dv_is_reported():
    reading = read_panel(Label(percent_dv={"allulose": 5}))

    assert ALLULOSE not in reading.intervals
    assert any("no Daily Value" in n for n in reading.notes)


# ---------------------------------------------------------------------------
# Protein: the %DV is quality-corrected, so it can't be inverted.
# ---------------------------------------------------------------------------


def test_protein_percent_dv_is_refused():
    """A real peanut butter panel prints "Protein 7g / 8%". Against the 50 g DV
    a raw fraction would be 14%; the 8% is PDCAAS-corrected for protein
    quality. Inverting it would imply 3.75-4.25 g and contradict the 7 g
    printed alongside it."""
    assert US_FDA.percent_dv_interval(REG["protein"], 8) is None
    assert "PDCAAS" in US_FDA.percent_dv_caveat(REG["protein"])


def test_protein_percentage_does_not_corrupt_the_printed_amount():
    reading = read_panel(Label({"protein": 7}, percent_dv={"protein": 8}))

    # the printed grams survive untouched
    assert reading.intervals[PROTEIN] == (6.5, 7.5)
    assert any("PDCAAS" in n for n in reading.notes)


def test_other_nutrients_still_invert_normally():
    """The refusal is protein-specific, not a blanket retreat."""
    assert US_FDA.percent_dv_caveat(REG["calcium"]) is None
    assert US_FDA.percent_dv_interval(REG["calcium"], 2) == (13.0, 39.0)


# ---------------------------------------------------------------------------
# The DV table is hand-entered reference data; guard it like the registry.
# ---------------------------------------------------------------------------


def _raw_dv() -> dict:
    text = (
        resources.files("nutrition_toolkit.labels.regimes.data")
        .joinpath("us_fda_daily_values.json")
        .read_text("utf-8")
    )
    return json.loads(text)


def test_every_daily_value_names_a_known_nutrient():
    for row in _raw_dv()["daily_values"]:
        nutrient = REG.get(row["id"])
        assert nutrient is not None, row
        # the name in the file is a comment for readers; keep it honest
        assert nutrient.name == row["name"], (nutrient.name, row["name"])


def test_daily_value_units_are_convertible_to_canonical():
    for nid, (value, unit) in daily_values().items():
        nutrient = REG[nid]
        assert value > 0
        if unit != nutrient.unit:
            nutrient.to_canonical(value, unit)  # must not raise


def test_the_four_mandatory_micronutrients_are_present():
    """Vitamin D, calcium, iron and potassium are mandatory on a 2016-format
    panel and are exactly the ones often given as a bare percentage."""
    for nid in (VITAMIN_D, CALCIUM, IRON, POTASSIUM):
        assert nid in daily_values()
