"""Nutrient identity and the vector type everything else passes around.

The invariant that makes the rest of the toolkit safe: **a NutrientVector is
always in each nutrient's canonical unit**. Amounts carry no unit of their own;
the registry defines it. Conversion happens at the edges -- adapters and label
readers -- so IU/mass mix-ups can't propagate inward.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field


class UnitConversionError(Exception):
    """Raised when a unit conversion isn't well defined."""


@dataclass(frozen=True)
class Contribution:
    """This nutrient contributes `factor` x its amount to nutrient `id`.

    factor 1.0 is a plain sum (saturated fat -> total fat). Vitamin A uses
    Retinol Activity Equivalent weights, so beta-carotene carries 1/12.
    """

    id: int
    factor: float


@dataclass(frozen=True)
class UnitConversion:
    """How an alternate unit relates to the canonical one.

    `per_canonical` is how many alternate units make one canonical unit
    (vitamin D: 40 IU per ug). `ambiguous` records *why* no single factor
    exists, for the cases where one genuinely doesn't -- vitamins A and E,
    where the IU relationship depends on the chemical form present.
    """

    per_canonical: float | None = None
    ambiguous: str | None = None

    @property
    def is_defined(self) -> bool:
        return self.per_canonical is not None


@dataclass(frozen=True)
class Nutrient:
    id: int
    name: str
    unit: str
    category: str
    aliases: tuple[str, ...] = ()
    solubility: str | None = None  # "fat" | "water" | None
    mass_component: bool = False
    carrier: bool = False
    derived: bool = False
    formula: str | None = None
    contributes_to: tuple[Contribution, ...] = ()
    alt_units: Mapping[str, UnitConversion] = field(default_factory=dict)
    external_ids: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    note: str | None = None

    @property
    def fat_soluble(self) -> bool:
        """Partitions into the lipid phase, so it leaves with rendered fat."""
        return self.solubility == "fat"

    def to_canonical(self, amount: float, unit: str) -> float:
        """Convert `amount` expressed in `unit` into the canonical unit."""
        if unit == self.unit:
            return amount
        conv = self.alt_units.get(unit)
        if conv is None:
            raise UnitConversionError(
                f"{self.name} (id {self.id}) has no conversion from {unit!r} "
                f"to {self.unit!r}"
            )
        if not conv.is_defined:
            raise UnitConversionError(
                f"{self.name} (id {self.id}): {unit!r} -> {self.unit!r} is not "
                f"well defined. {conv.ambiguous}"
            )
        return amount / conv.per_canonical

    def from_canonical(self, amount: float, unit: str) -> float:
        """Convert `amount` from the canonical unit into `unit`."""
        if unit == self.unit:
            return amount
        conv = self.alt_units.get(unit)
        if conv is None:
            raise UnitConversionError(
                f"{self.name} (id {self.id}) has no conversion from {self.unit!r} "
                f"to {unit!r}"
            )
        if not conv.is_defined:
            raise UnitConversionError(
                f"{self.name} (id {self.id}): {self.unit!r} -> {unit!r} is not "
                f"well defined. {conv.ambiguous}"
            )
        return amount * conv.per_canonical


class NutrientVector(Mapping[int, float]):
    """An immutable nutrient profile: canonical nutrient id -> amount.

    Amounts are in each nutrient's canonical unit. Ids the registry doesn't
    know are carried unchanged rather than rejected -- databases add nutrients
    (Cronometer added oxalate and phytate recently), and dropping them silently
    would defeat the tools built to notice exactly that.
    """

    __slots__ = ("_amounts", "basis_g")

    def __init__(self, amounts: Mapping[int, float], *, basis_g: float = 100.0):
        self._amounts: dict[int, float] = {int(k): float(v) for k, v in amounts.items()}
        self.basis_g = float(basis_g)

    def __getitem__(self, key: int) -> float:
        return self._amounts[key]

    def __iter__(self) -> Iterator[int]:
        return iter(self._amounts)

    def __len__(self) -> int:
        return len(self._amounts)

    def __repr__(self) -> str:
        return f"NutrientVector({self._amounts!r}, basis_g={self.basis_g})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, NutrientVector):
            return NotImplemented
        return self._amounts == other._amounts and self.basis_g == other.basis_g

    def scaled(self, factor: float) -> NutrientVector:
        """Scale every amount, leaving the basis alone.

        Use for "this profile per 100 g, at 250 g". To change the basis itself
        (a reduction, say), use `rebased`.
        """
        return NutrientVector(
            {k: v * factor for k, v in self._amounts.items()}, basis_g=self.basis_g
        )

    def rebased(self, basis_g: float) -> NutrientVector:
        """Re-express this profile per `basis_g` grams, scaling amounts to match."""
        if self.basis_g == 0:
            raise ValueError("cannot rebase a profile with zero basis")
        factor = basis_g / self.basis_g
        return NutrientVector(
            {k: v * factor for k, v in self._amounts.items()}, basis_g=basis_g
        )

    def with_amounts(self, updates: Mapping[int, float]) -> NutrientVector:
        """Return a copy with `updates` applied -- the override primitive."""
        merged = dict(self._amounts)
        merged.update({int(k): float(v) for k, v in updates.items()})
        return NutrientVector(merged, basis_g=self.basis_g)

    def without(self, ids: object) -> NutrientVector:
        """Return a copy with `ids` removed."""
        drop = {int(i) for i in ids}  # type: ignore[union-attr]
        return NutrientVector(
            {k: v for k, v in self._amounts.items() if k not in drop},
            basis_g=self.basis_g,
        )
