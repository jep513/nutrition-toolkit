"""Load and query the nutrient registry.

The registry is the spine every other package keys off: identity, canonical
unit, physical behaviour (what dissolves in fat, what carries mass, what
carries energy), and how nutrients aggregate into one another.

It describes what a nutrient *is*. What a *process* does to one -- boiling
leaching 45% of the vitamin C out -- belongs in the retention tables instead.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from .models import Contribution, Nutrient, NutrientVector, UnitConversion

_DATA_PACKAGE = "nutrition_toolkit.nutrients.data"
_DATA_FILE = "nutrients.json"


@dataclass(frozen=True)
class EnergyTerm:
    id: int
    factor: float


class Registry:
    """An immutable view over the nutrient catalog."""

    def __init__(self, doc: Mapping[str, object]) -> None:
        self.schema_version = int(doc.get("schema_version", 0))  # type: ignore[arg-type]
        self.sources: tuple[str, ...] = tuple(doc.get("sources", ()))  # type: ignore[arg-type]

        energy = doc.get("energy") or {}
        self.energy_terms: tuple[EnergyTerm, ...] = tuple(
            EnergyTerm(int(t["id"]), float(t["factor"]))
            for t in energy.get("terms", ())  # type: ignore[union-attr]
        )
        self.energy_note: str | None = energy.get("note")  # type: ignore[union-attr]

        self._by_id: dict[int, Nutrient] = {}
        self._by_key: dict[str, int] = {}
        for raw in doc.get("nutrients", ()):  # type: ignore[union-attr]
            nutrient = _parse_nutrient(raw)
            self._by_id[nutrient.id] = nutrient
            for key in self._lookup_keys(nutrient):
                # Aliases are validated as unique when the file loads; a clash
                # is a data bug, not something to resolve arbitrarily.
                existing = self._by_key.get(key)
                if existing is not None and existing != nutrient.id:
                    raise ValueError(
                        f"nutrient key {key!r} maps to both {existing} and {nutrient.id}"
                    )
                self._by_key[key] = nutrient.id

        # child -> parents is stored on the nutrient; build the reverse once.
        self._contributors: dict[int, list[Contribution]] = {}
        for nutrient in self._by_id.values():
            for contribution in nutrient.contributes_to:
                self._contributors.setdefault(contribution.id, []).append(
                    Contribution(nutrient.id, contribution.factor)
                )

    # -- lookup ---------------------------------------------------------

    @staticmethod
    def _lookup_keys(nutrient: Nutrient) -> Iterator[str]:
        yield _normalize(nutrient.name)
        for alias in nutrient.aliases:
            yield _normalize(alias)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, int):
            return key in self._by_id
        return _normalize(str(key)) in self._by_key

    def __iter__(self) -> Iterator[Nutrient]:
        return iter(self._by_id.values())

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, key: int | str) -> Nutrient | None:
        """Look up by canonical id, alias, or name. None if unknown."""
        if isinstance(key, int):
            return self._by_id.get(key)
        nid = self._by_key.get(_normalize(key))
        return self._by_id.get(nid) if nid is not None else None

    def __getitem__(self, key: int | str) -> Nutrient:
        nutrient = self.get(key)
        if nutrient is None:
            raise KeyError(f"unknown nutrient {key!r}")
        return nutrient

    def resolve_id(self, key: int | str) -> int | None:
        """Canonical id for a name/alias/id, or None if the registry doesn't
        know it. Unknown keys are a normal condition -- see NutrientVector."""
        nutrient = self.get(key)
        return nutrient.id if nutrient else None

    def contributors_to(self, nutrient_id: int) -> tuple[Contribution, ...]:
        """Nutrients that feed into `nutrient_id`, with their factors."""
        return tuple(self._contributors.get(nutrient_id, ()))

    # -- selections used by the derive/ tools ---------------------------

    def ids_where(
        self,
        *,
        solubility: str | None = None,
        category: str | None = None,
        mass_component: bool | None = None,
    ) -> frozenset[int]:
        """Ids matching every supplied criterion."""
        out = set()
        for nutrient in self._by_id.values():
            if solubility is not None and nutrient.solubility != solubility:
                continue
            if category is not None and nutrient.category != category:
                continue
            if mass_component is not None and nutrient.mass_component != mass_component:
                continue
            out.add(nutrient.id)
        return frozenset(out)

    # -- computed quantities --------------------------------------------

    def energy_kcal(self, vector: Mapping[int, float]) -> float:
        """Energy from the macros via Atwater factors.

        Fibre and sugar alcohols carry negative corrections because
        carbohydrate is declared inclusive of them; see `energy_note`.
        """
        return sum(term.factor * vector.get(term.id, 0.0) for term in self.energy_terms)

    def recompute_derived(self, vector: NutrientVector) -> NutrientVector:
        """Recompute nutrients marked `derived` from their contributors.

        Only recomputes when *every* contributor is present, so a partial
        profile keeps whatever the source database said rather than silently
        losing information. This is what makes an edit to beta-carotene flow
        through to vitamin A.
        """
        updates: dict[int, float] = {}
        for nutrient in self._by_id.values():
            if not nutrient.derived:
                continue
            contributors = self.contributors_to(nutrient.id)
            if not contributors:
                continue
            if not all(c.id in vector for c in contributors):
                continue
            updates[nutrient.id] = sum(c.factor * vector[c.id] for c in contributors)
        return vector.with_amounts(updates) if updates else vector

    def unknown_ids(self, vector: Iterable[int]) -> frozenset[int]:
        """Ids in `vector` the registry doesn't describe.

        Carried through by every operation, but not aggregated or converted.
        A non-empty result usually means the upstream database grew a nutrient.
        """
        return frozenset(i for i in vector if i not in self._by_id)


def _normalize(key: str) -> str:
    return key.strip().lower().replace(" ", "_").replace("-", "_")


def _parse_nutrient(raw: Mapping[str, object]) -> Nutrient:
    alt_units = {
        unit: UnitConversion(
            per_canonical=conv.get("per_canonical"),  # type: ignore[union-attr]
            ambiguous=conv.get("ambiguous"),  # type: ignore[union-attr]
        )
        for unit, conv in (raw.get("alt_units") or {}).items()  # type: ignore[union-attr]
    }
    return Nutrient(
        id=int(raw["id"]),  # type: ignore[arg-type]
        name=str(raw["name"]),
        unit=str(raw["unit"]),
        category=str(raw["category"]),
        aliases=tuple(raw.get("aliases", ())),  # type: ignore[arg-type]
        solubility=raw.get("solubility"),  # type: ignore[arg-type]
        mass_component=bool(raw.get("mass_component", False)),
        carrier=bool(raw.get("carrier", False)),
        derived=bool(raw.get("derived", False)),
        formula=raw.get("formula"),  # type: ignore[arg-type]
        contributes_to=tuple(
            Contribution(int(c["id"]), float(c["factor"]))
            for c in raw.get("contributes_to", ())  # type: ignore[union-attr]
        ),
        alt_units=alt_units,
        external_ids=dict(raw.get("external_ids", {})),  # type: ignore[arg-type]
        note=raw.get("note"),  # type: ignore[arg-type]
    )


@lru_cache(maxsize=1)
def load_registry() -> Registry:
    """The bundled registry, parsed once per process."""
    text = resources.files(_DATA_PACKAGE).joinpath(_DATA_FILE).read_text("utf-8")
    return Registry(json.loads(text))
