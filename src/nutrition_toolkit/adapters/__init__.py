"""Per-app adapters. Nothing above this package imports a tracker by name.

An adapter shapes a solved/derived result into whatever a given nutrition
tracker wants. Callers pick one by name so adding a tracker is a new module
here plus one registry entry.
"""

from __future__ import annotations

from collections.abc import Callable

from .cronometer import to_cronometer_custom_food

ADAPTERS: dict[str, Callable[..., dict]] = {
    "cronometer": to_cronometer_custom_food,
}
DEFAULT_ADAPTER = "cronometer"

__all__ = ["ADAPTERS", "DEFAULT_ADAPTER", "get_adapter", "to_cronometer_custom_food"]


def get_adapter(name: str) -> Callable[..., dict]:
    """Look up an output adapter by name, e.g. "cronometer"."""
    try:
        return ADAPTERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown adapter {name!r}. Known: {sorted(ADAPTERS)}"
        ) from None
