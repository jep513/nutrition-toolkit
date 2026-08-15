"""Read a printed nutrition panel into solver constraints.

This package owns everything jurisdiction-specific about labels: which declared
quantities map onto which canonical nutrients, and how a printed number maps
back to a range of true values. It knows nothing about solving -- it produces
intervals keyed by canonical nutrient id.

    from nutrition_toolkit.labels import Label, read_panel

    reading = read_panel(Label({"protein": 22, "fat": 32}, basis_g=113))
    reading.intervals   # {203: (21.5, 22.5), 204: (31.5, 32.5)}
"""

from __future__ import annotations

from ..nutrients import Registry, load_registry
from .models import Label, PanelReading
from .regimes import DEFAULT_REGIME, REGIMES, US_FDA, Regime, get_regime

__all__ = [
    "DEFAULT_REGIME",
    "REGIMES",
    "US_FDA",
    "Label",
    "PanelReading",
    "Regime",
    "get_regime",
    "read_panel",
]


def read_panel(
    label: Label,
    regime: Regime = DEFAULT_REGIME,
    registry: Registry | None = None,
) -> PanelReading:
    """Translate a printed panel into true-value intervals under `regime`.

    Panel keys may be canonical ids, registry names, or aliases; the regime
    resolves them, since that mapping is jurisdiction-specific.
    """
    registry = registry or load_registry()
    amounts, notes = regime.normalize_declared(label.values, registry)

    intervals: dict[int, tuple[float, float]] = {}
    derived: set[int] = set()
    for nid, printed in amounts.items():
        nutrient = registry.get(nid)
        intervals[nid] = regime.interval(nutrient, printed)
        if regime.is_derived(nutrient):
            derived.add(nid)

    # Percent-DV declarations. Where a nutrient is declared both ways the two
    # bands must overlap; intersecting keeps whichever is tighter without
    # needing a precedence rule. That matters because it isn't always the
    # printed amount -- under 5 mg the absolute rule collapses to [0, 5], so a
    # percentage can be the sharper of the two. An empty intersection means
    # the panel disagrees with itself, which is worth saying out loud.
    if label.percent_dv:
        pct_amounts, pct_notes = regime.normalize_declared(label.percent_dv, registry)
        notes.extend(pct_notes)
        for nid, printed_pct in pct_amounts.items():
            nutrient = registry.get(nid)
            band = regime.percent_dv_interval(nutrient, printed_pct)
            if band is None:
                caveat = regime.percent_dv_caveat(nutrient)
                reason = caveat or f"no Daily Value under {regime.name}"
                notes.append(
                    f"{registry.name_for(nid)}: {printed_pct}% declaration "
                    f"ignored -- {reason}"
                )
                continue
            existing = intervals.get(nid)
            if existing is None:
                intervals[nid] = band
                continue
            lo, hi = max(existing[0], band[0]), min(existing[1], band[1])
            if lo > hi:
                notes.append(
                    f"{registry.name_for(nid)}: printed amount implies "
                    f"{existing[0]:g}-{existing[1]:g} but {printed_pct}% DV implies "
                    f"{band[0]:g}-{band[1]:g}; they don't overlap, keeping the "
                    f"printed amount"
                )
            else:
                intervals[nid] = (lo, hi)

    unknown = registry.unknown_ids(intervals)
    if unknown:
        notes.append(
            "panel declares nutrient id(s) the registry doesn't describe: "
            + ", ".join(str(i) for i in sorted(unknown))
        )

    return PanelReading(
        intervals=intervals,
        basis_g=label.basis_g,
        derived_keys=frozenset(derived),
        notes=[f"read under {regime.name}", *notes],
    )
