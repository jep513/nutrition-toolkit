"""Labelling regimes, one per jurisdiction.

Add a regime by implementing `Regime` and registering it here. Planned:
`eu_1169` (Regulation (EU) No 1169/2011), `ca_cfia`, `au_nz_fsanz`.
"""

from __future__ import annotations

from .base import Regime
from .us_fda import US_FDA, USFDARegime

REGIMES: dict[str, Regime] = {US_FDA.name: US_FDA}
DEFAULT_REGIME: Regime = US_FDA

__all__ = ["DEFAULT_REGIME", "REGIMES", "US_FDA", "Regime", "USFDARegime", "get_regime"]


def get_regime(name: str) -> Regime:
    """Look up a regime by name, e.g. "us_fda"."""
    try:
        return REGIMES[name]
    except KeyError:
        raise ValueError(
            f"Unknown labelling regime {name!r}. Known: {sorted(REGIMES)}"
        ) from None
