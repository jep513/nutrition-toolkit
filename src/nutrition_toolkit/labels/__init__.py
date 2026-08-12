"""Read a printed nutrition panel into solver constraints.

This package owns everything jurisdiction-specific about labels: how a printed
number maps back to a range of true values, and (as regimes beyond the US land)
how declared quantities map onto canonical nutrients. It knows nothing about
solving -- it just produces intervals.

    from nutrition_toolkit.labels import Label, read_panel

    reading = read_panel(Label({"protein": 22, "fat": 32}, basis_g=113))
    reading.intervals   # {"protein": (21.5, 22.5), "fat": (31.5, 32.5)}
"""

from __future__ import annotations

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


def read_panel(label: Label, regime: Regime = DEFAULT_REGIME) -> PanelReading:
    """Translate a printed panel into true-value intervals under `regime`."""
    intervals = {k: regime.interval(k, v) for k, v in label.values.items()}
    derived = frozenset(k for k in label.values if regime.is_derived(k))
    notes = [f"read under {regime.name}"]
    return PanelReading(
        intervals=intervals,
        basis_g=label.basis_g,
        derived_keys=derived,
        notes=notes,
    )
