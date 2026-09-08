"""Reader for the `NUMCON` / `NUMMAQ` / `POTEFE` `AC` cadastre changes in `entdados.dat`.

These are the three `AC` mnemonics that change the unit structure of a hydro plant for the
study (DESSEM User Manual v22.4.0, section III.5.4.7):

- `NUMCON` -- number of unit groups (conjuntos) of the plant.
- `NUMMAQ` -- unit count of one group.
- `POTEFE` -- effective power per unit of one group, in MW.

`idessem` can silently drop an `AC` line that fails to match any registered mnemonic pattern,
falling back to an untyped `DefaultRegister` instead of raising (confirmed on the reference
deck's `AC  118  DESVIO ...` lines, an unrelated mnemonic). `read_cadastre_changes` guards
against the same failure mode for NUMCON/NUMMAQ/POTEFE by cross-checking the parsed count
against an independent raw-text scan of `entdados_path`.

Only extraction is done here; interpreting or applying a change to the plant model is out of
scope (see ticket-003).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from idessem.dessem import Entdados
from idessem.dessem.modelos.entdados import ACNUMCON, ACNUMMAQ, ACPOTEFE

logger = logging.getLogger(__name__)

# Deliberately more permissive on whitespace than idessem's own fixed-width identifiers, so
# that this raw-text count is a trustworthy upper bound independent of idessem's parsing.
# `^AC` already excludes `&` comment lines without any special-casing.
_CHANGE_LINE_PATTERN: Final = re.compile(r"^AC\s+\d{1,3}\s+(NUMCON|NUMMAQ|POTEFE)\b")


class CadastreChangeError(Exception):
    """Raised on a malformed AC cadastre change record or a parsed/raw-file count mismatch."""


@dataclass(frozen=True, slots=True)
class GroupCountChange:
    """`AC ... NUMCON`: sets the number of unit groups (conjuntos) of a plant."""

    plant_code: int
    group_count: int

    def __post_init__(self) -> None:
        if self.plant_code < 1:
            raise CadastreChangeError(
                f"AC NUMCON (plant {self.plant_code}): plant code must be >= 1"
            )
        if self.group_count < 0:
            raise CadastreChangeError(
                f"AC NUMCON (plant {self.plant_code}): group count must be >= 0, "
                f"got {self.group_count}"
            )


@dataclass(frozen=True, slots=True)
class UnitCountChange:
    """`AC ... NUMMAQ`: sets the unit count of one group (conjunto) of a plant."""

    plant_code: int
    group_index: int
    unit_count: int

    def __post_init__(self) -> None:
        if self.plant_code < 1:
            raise CadastreChangeError(
                f"AC NUMMAQ (plant {self.plant_code}): plant code must be >= 1"
            )
        if self.group_index < 1:
            raise CadastreChangeError(
                f"AC NUMMAQ (plant {self.plant_code}): group index must be >= 1, "
                f"got {self.group_index}"
            )
        if self.unit_count < 0:
            raise CadastreChangeError(
                f"AC NUMMAQ (plant {self.plant_code}, group {self.group_index}): unit count "
                f"must be >= 0, got {self.unit_count}"
            )


@dataclass(frozen=True, slots=True)
class UnitPowerChange:
    """`AC ... POTEFE`: sets the effective power per unit, in MW, of one group of a plant."""

    plant_code: int
    group_index: int
    power_mw: float

    def __post_init__(self) -> None:
        if self.plant_code < 1:
            raise CadastreChangeError(
                f"AC POTEFE (plant {self.plant_code}): plant code must be >= 1"
            )
        if self.group_index < 1:
            raise CadastreChangeError(
                f"AC POTEFE (plant {self.plant_code}): group index must be >= 1, "
                f"got {self.group_index}"
            )
        if self.power_mw < 0:
            raise CadastreChangeError(
                f"AC POTEFE (plant {self.plant_code}, group {self.group_index}): power must "
                f"be >= 0 MW, got {self.power_mw}"
            )


CadastreChange = GroupCountChange | UnitCountChange | UnitPowerChange


def _build_group_count_change(register: ACNUMCON) -> GroupCountChange:
    plant_code = register.codigo_usina
    group_count = register.numero_conjuntos
    if plant_code is None or group_count is None:
        raise CadastreChangeError(
            f"AC NUMCON (plant {plant_code!r}): missing field(s), "
            f"plant_code={plant_code!r}, group_count={group_count!r}"
        )
    return GroupCountChange(plant_code=plant_code, group_count=group_count)


def _build_unit_count_change(register: ACNUMMAQ) -> UnitCountChange:
    plant_code = register.codigo_usina
    group_index = register.codigo_conjunto
    unit_count = register.numero_maquinas
    if plant_code is None or group_index is None or unit_count is None:
        raise CadastreChangeError(
            f"AC NUMMAQ (plant {plant_code!r}): missing field(s), "
            f"plant_code={plant_code!r}, group_index={group_index!r}, unit_count={unit_count!r}"
        )
    return UnitCountChange(plant_code=plant_code, group_index=group_index, unit_count=unit_count)


def _build_unit_power_change(register: ACPOTEFE) -> UnitPowerChange:
    plant_code = register.codigo_usina
    group_index = register.codigo_conjunto
    power_mw = register.potencia
    if plant_code is None or group_index is None or power_mw is None:
        raise CadastreChangeError(
            f"AC POTEFE (plant {plant_code!r}): missing field(s), "
            f"plant_code={plant_code!r}, group_index={group_index!r}, power_mw={power_mw!r}"
        )
    return UnitPowerChange(plant_code=plant_code, group_index=group_index, power_mw=power_mw)


def _count_raw_change_lines(entdados_path: Path) -> int:
    """Count `entdados_path` lines that look like a NUMCON/NUMMAQ/POTEFE `AC` record.

    Read as plain text (`latin-1`, `idessem`'s own encoding for this file) so the count does
    not go through `idessem`'s own parsing and can catch a record `idessem` fails to surface.
    """
    text = entdados_path.read_text(encoding="latin-1")
    return sum(1 for line in text.splitlines() if _CHANGE_LINE_PATTERN.match(line))


def read_cadastre_changes(entdados: Entdados, entdados_path: Path) -> list[CadastreChange]:
    """Extract the NUMCON/NUMMAQ/POTEFE `AC` cadastre changes of `entdados`, in file order.

    `entdados` must have been read from `entdados_path`; the two are cross-checked against
    each other (see module docstring). Any other `AC` mnemonic and every other register type
    are ignored.
    """
    changes: list[CadastreChange] = []
    mnemonic_counts = {"NUMCON": 0, "NUMMAQ": 0, "POTEFE": 0}

    for register in entdados.data:
        change: CadastreChange
        if isinstance(register, ACNUMCON):
            change = _build_group_count_change(register)
            mnemonic_counts["NUMCON"] += 1
        elif isinstance(register, ACNUMMAQ):
            change = _build_unit_count_change(register)
            mnemonic_counts["NUMMAQ"] += 1
        elif isinstance(register, ACPOTEFE):
            change = _build_unit_power_change(register)
            mnemonic_counts["POTEFE"] += 1
        else:
            continue
        changes.append(change)
        logger.debug("Cadastre change: %s", change)

    raw_count = _count_raw_change_lines(entdados_path)
    if raw_count != len(changes):
        raise CadastreChangeError(
            f"Parsed {len(changes)} cadastre change(s) from entdados.data, but {entdados_path} "
            f"has {raw_count} line(s) matching a NUMCON/NUMMAQ/POTEFE AC record; idessem may "
            "have silently dropped one or more of them"
        )

    logger.info(
        "Read %d cadastre change(s) from %s: %d NUMCON, %d NUMMAQ, %d POTEFE",
        len(changes),
        entdados_path,
        mnemonic_counts["NUMCON"],
        mnemonic_counts["NUMMAQ"],
        mnemonic_counts["POTEFE"],
    )
    return changes
