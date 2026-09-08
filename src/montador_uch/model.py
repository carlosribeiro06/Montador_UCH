"""Domain model for the UCH hierarchy: plant -> unit group -> generating unit.

Pure Python, no pandas and no idessem imports. The spreadsheet reader builds these objects and
the UCH builder consumes them, so all cross-field validation lives here.

Power units are MW throughout.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import IntEnum

_POWER_TOLERANCE_MW = 1e-9


class AggregationLevel(IntEnum):
    """UCH modelling granularity.

    The integer values are the DESSEM `UCH-OPCAO-PADRAO-USINA` aggregation codes
    (User Manual v22.4.0, section III.32.1).
    """

    UNIT = 1
    GROUP = 2
    PLANT = 3

    @classmethod
    def from_label(cls, label: str) -> AggregationLevel:
        """Map a spreadsheet `Tipo` label to its aggregation level.

        Matching is exact; `Sem UCH` rows are filtered out by the reader and never reach here.
        """
        try:
            return _LABELS[label]
        except KeyError:
            known = ", ".join(repr(key) for key in _LABELS)
            raise ValueError(
                f"Unknown aggregation label {label!r}; expected one of {known}"
            ) from None


_LABELS: dict[str, AggregationLevel] = {
    "Unidade": AggregationLevel.UNIT,
    "Conjunto": AggregationLevel.GROUP,
    "Usina": AggregationLevel.PLANT,
}


def _check_index(value: int, what: str) -> None:
    if value <= 0:
        raise ValueError(f"{what} index must be positive, got {value}")


def _check_power(value: float, what: str) -> None:
    if value < 0.0:
        raise ValueError(f"{what} must not be negative, got {value}")


def _check_limits(minimum: float, maximum: float, what: str) -> None:
    """Reject an inverted limit pair, which DESSEM would receive as an infeasible register."""
    if minimum > maximum + _POWER_TOLERANCE_MW:
        raise ValueError(
            f"{what} minimum power {minimum} exceeds its maximum {maximum}; "
            "the register would be infeasible"
        )


@dataclass(frozen=True, slots=True)
class GeneratingUnit:
    """One generating unit of a unit group."""

    index: int
    min_power_mw: float
    max_power_mw: float

    def __post_init__(self) -> None:
        _check_index(self.index, "Unit")
        _check_power(self.min_power_mw, f"Unit {self.index} minimum power")
        _check_power(self.max_power_mw, f"Unit {self.index} maximum power")
        _check_limits(self.min_power_mw, self.max_power_mw, f"Unit {self.index}")


@dataclass(frozen=True, slots=True)
class UnitGroup:
    """One unit group (conjunto) of a hydro plant.

    `max_power_mw` is the group total, as given by the spreadsheet's `Potencia_maxima`.
    """

    index: int
    max_power_mw: float
    units: tuple[GeneratingUnit, ...]

    def __post_init__(self) -> None:
        _check_index(self.index, "Group")
        _check_power(self.max_power_mw, f"Group {self.index} maximum power")

        if not self.units:
            raise ValueError(f"Group {self.index} has no generating units")

        indices = [unit.index for unit in self.units]
        if len(set(indices)) != len(indices):
            raise ValueError(f"Group {self.index} has non-unique unit indices {sorted(indices)}")

        minima = [unit.min_power_mw for unit in self.units]
        reference = minima[0]
        if any(not math.isclose(value, reference, abs_tol=_POWER_TOLERANCE_MW) for value in minima):
            raise ValueError(
                f"Group {self.index} units have differing minimum powers {minima}; "
                "all units of a group share the spreadsheet start-up power"
            )

        _check_limits(reference, self.max_power_mw, f"Group {self.index}")

    @property
    def min_power_mw(self) -> float:
        """The minimum power common to every unit of the group."""
        return self.units[0].min_power_mw


@dataclass(frozen=True, slots=True)
class HydroPlant:
    """A hydro plant modelled with UCH, with its unit groups."""

    code: int
    name: str
    aggregation: AggregationLevel
    groups: tuple[UnitGroup, ...]

    def __post_init__(self) -> None:
        _check_index(self.code, f"Plant {self.name!r} code")

        if not self.groups:
            raise ValueError(f"Plant {self.code} ({self.name}) has no unit groups")

        indices = [group.index for group in self.groups]
        if len(set(indices)) != len(indices):
            raise ValueError(
                f"Plant {self.code} ({self.name}) has non-unique group indices {sorted(indices)}"
            )

    @property
    def units(self) -> tuple[GeneratingUnit, ...]:
        """Every generating unit of the plant, flattened in group order."""
        return tuple(unit for group in self.groups for unit in group.units)

    @property
    def min_power_mw(self) -> float:
        """The smallest unit minimum power in the plant."""
        return min(unit.min_power_mw for unit in self.units)

    @property
    def max_power_mw(self) -> float:
        """The sum of the group totals.

        Deliberately different from the legacy script, which added each group total once per
        unit and so over-counted the plant maximum by the unit count.
        """
        return math.fsum(group.max_power_mw for group in self.groups)
