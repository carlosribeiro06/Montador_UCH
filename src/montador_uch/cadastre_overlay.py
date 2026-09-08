"""Overlay `AC` cadastre changes (NUMCON/NUMMAQ/POTEFE) on the base `UCH.xlsx` records.

The workbook is the registry of record; the deck's `AC` changes for the study are applied on
top, in file order, one plant at a time, before the domain object (`HydroPlant`) is built.
`hidr.dat` is never read, so every start-up power (Gmin) a resulting group carries must already
be on the workbook -- a group created or kept eligible by `AC NUMCON` that lacks one aborts the
run rather than inheriting or defaulting to a value the plant registry never stated.

Assumption (DESSEM User Manual v22.4.0 III.5.4.7, this plan's reading, carried into the project
README): changes are applied sequentially, and a `NUMMAQ`/`POTEFE` group index is checked
against the plant's *current* number of groups at the point it is applied, not its original
`N_conjuntos`. In practice `AC NUMCON` must precede any `NUMMAQ`/`POTEFE` that relies on the
group it adds; the reverse order raises `CadastreChangeError`.

A plant whose changes leave every unit group at zero units is dropped from the output with a
warning, never modelled with an invented zero-unit group.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from montador_uch.cadastre_changes import (
    CadastreChange,
    CadastreChangeError,
    GroupCountChange,
    UnitCountChange,
    UnitPowerChange,
)
from montador_uch.model import GeneratingUnit, HydroPlant, UnitGroup
from montador_uch.spreadsheet import (
    GROUP_MAX_POWER_COLUMN,
    MAX_GROUPS,
    START_UP_POWER_COLUMN,
    PlantRecord,
    build_plant,
    group_column,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class OmittedPlant:
    """A plant dropped from the output because its cadastre changes zeroed every unit group."""

    code: int
    name: str
    row_number: int
    reason: str


@dataclass(frozen=True, slots=True)
class OverlayResult:
    """The plants built from the overlay, the ones omitted, and how many changes were used."""

    plants: list[HydroPlant]
    omitted: list[OmittedPlant]
    changes_applied: int
    changes_ignored: int


@dataclass(slots=True)
class _GroupState:
    """Mutable working state of one cadastral group position while changes are applied."""

    unit_count: int
    min_mw: float | None
    unit_max_mw: float | None
    spreadsheet_total_mw: float | None
    structure_changed: bool = False


def _initial_group_states(record: PlantRecord) -> list[_GroupState]:
    """Working state for every one of `MAX_GROUPS` cadastral positions, from the raw record."""
    return [
        _GroupState(
            unit_count=group.unit_count,
            min_mw=group.min_power_mw,
            unit_max_mw=(
                group.max_power_mw / group.unit_count
                if group.unit_count > 0 and group.max_power_mw is not None
                else None
            ),
            spreadsheet_total_mw=group.max_power_mw,
        )
        for group in record.groups
    ]


def _check_group_index(index: int, group_count: int, record: PlantRecord, mnemonic: str) -> None:
    """Reject a `NUMMAQ`/`POTEFE` group index beyond the plant's current group count."""
    if index > group_count:
        raise CadastreChangeError(
            f"Row {record.row_number}, plant {record.code} ({record.name}): AC {mnemonic} "
            f"group {index} exceeds the plant's current {group_count} group(s) (DESSEM manual "
            "III.5.4.7: the group index must be at most the plant's number of groups)"
        )


def _apply_group_count_change(
    change: GroupCountChange, group_count: int, record: PlantRecord
) -> int:
    if change.group_count > MAX_GROUPS:
        raise CadastreChangeError(
            f"Row {record.row_number}, plant {record.code} ({record.name}): AC NUMCON sets "
            f"{change.group_count} group(s), exceeding the workbook's maximum of {MAX_GROUPS}"
        )
    logger.info(
        "Plant %d (%s): NUMCON %d -> %d",
        record.code,
        record.name,
        group_count,
        change.group_count,
    )
    return change.group_count


def _apply_unit_count_change(
    change: UnitCountChange, states: list[_GroupState], group_count: int, record: PlantRecord
) -> None:
    _check_group_index(change.group_index, group_count, record, "NUMMAQ")
    state = states[change.group_index - 1]
    logger.info(
        "Plant %d (%s): group %d units %d -> %d",
        record.code,
        record.name,
        change.group_index,
        state.unit_count,
        change.unit_count,
    )
    state.unit_count = change.unit_count
    state.structure_changed = True


def _apply_unit_power_change(
    change: UnitPowerChange, states: list[_GroupState], group_count: int, record: PlantRecord
) -> None:
    _check_group_index(change.group_index, group_count, record, "POTEFE")
    state = states[change.group_index - 1]
    logger.info(
        "Plant %d (%s): group %d unit power %s -> %s MW",
        record.code,
        record.name,
        change.group_index,
        state.unit_max_mw,
        change.power_mw,
    )
    state.unit_max_mw = change.power_mw
    state.structure_changed = True


def _finalise_groups(
    record: PlantRecord, states: Sequence[_GroupState], group_count: int
) -> list[UnitGroup]:
    """Build one `UnitGroup` per surviving cadastral position `1..group_count`."""
    groups: list[UnitGroup] = []
    for index in range(1, group_count + 1):
        state = states[index - 1]
        if state.unit_count <= 0:
            continue

        unit_max_mw = state.unit_max_mw
        if unit_max_mw is None:
            column = group_column(GROUP_MAX_POWER_COLUMN, index - 1)
            cause = (
                f"workbook column {column!r} is blank"
                if state.spreadsheet_total_mw is None
                else f"the workbook gives group {index} no units, so its total in {column!r} "
                "yields no per-unit power"
            )
            raise CadastreChangeError(
                f"Row {record.row_number}, plant {record.code} ({record.name}): group {index} "
                f"has no per-unit power: {cause}, and no AC POTEFE sets one"
            )
        min_mw = state.min_mw
        if min_mw is None:
            column = group_column(START_UP_POWER_COLUMN, index - 1)
            raise CadastreChangeError(
                f"Row {record.row_number}, plant {record.code} ({record.name}): group {index} "
                f"has no start-up power; fill workbook column {column!r}"
            )

        if state.structure_changed:
            total = state.unit_count * unit_max_mw
        else:
            spreadsheet_total_mw = state.spreadsheet_total_mw
            if spreadsheet_total_mw is None:
                # Unreachable: `structure_changed` is False only when `unit_count`/`unit_max_mw`
                # are unchanged from `_initial_group_states`, where a non-None `unit_max_mw`
                # already implies a non-None `spreadsheet_total_mw` (see that function).
                raise AssertionError(
                    f"Plant {record.code} ({record.name}): group {index} has "
                    f"{state.unit_count} unit(s) but no spreadsheet total despite an "
                    "unchanged structure"
                )
            total = spreadsheet_total_mw

        try:
            group = UnitGroup(
                index=index,
                max_power_mw=total,
                units=tuple(
                    GeneratingUnit(index=unit_index, min_power_mw=min_mw, max_power_mw=unit_max_mw)
                    for unit_index in range(1, state.unit_count + 1)
                ),
            )
        except ValueError as exc:
            raise CadastreChangeError(
                f"Row {record.row_number}, plant {record.code} ({record.name}): {exc}"
            ) from exc
        groups.append(group)
    return groups


def _build_plant_with_changes(
    record: PlantRecord, changes: Sequence[CadastreChange]
) -> HydroPlant | None:
    """Apply `changes` (already restricted to `record`'s plant, in file order) and build it.

    Returns `None` when no unit group survives (see module docstring); every other failure
    raises `CadastreChangeError`.
    """
    group_count = record.group_count
    states = _initial_group_states(record)

    for change in changes:
        if isinstance(change, GroupCountChange):
            group_count = _apply_group_count_change(change, group_count, record)
        elif isinstance(change, UnitCountChange):
            _apply_unit_count_change(change, states, group_count, record)
        else:
            _apply_unit_power_change(change, states, group_count, record)

    groups = _finalise_groups(record, states, group_count)
    if not groups:
        logger.warning(
            "Row %d, plant %d (%s): all unit groups have zero units after AC changes; "
            "omitted from the output",
            record.row_number,
            record.code,
            record.name,
        )
        return None

    return HydroPlant(
        code=record.code, name=record.name, aggregation=record.aggregation, groups=tuple(groups)
    )


def apply_cadastre_changes(
    records: Sequence[PlantRecord], changes: Sequence[CadastreChange]
) -> OverlayResult:
    """Turn `records` into `HydroPlant`s, with `changes` applied on top in file order.

    A plant absent from `changes` goes through `build_plant` unchanged, so a deck without
    relevant `AC` records reproduces `build_plant`'s output and errors exactly. A change whose
    `plant_code` matches no record is ignored and counted in `changes_ignored`, never raised.
    """
    known_codes = {record.code for record in records}
    changes_by_plant: dict[int, list[CadastreChange]] = {}
    changes_ignored = 0
    for change in changes:
        if change.plant_code not in known_codes:
            changes_ignored += 1
            logger.debug(
                "Ignoring cadastre change for plant %d, absent from the workbook: %s",
                change.plant_code,
                change,
            )
            continue
        changes_by_plant.setdefault(change.plant_code, []).append(change)

    plants: list[HydroPlant] = []
    omitted: list[OmittedPlant] = []
    changes_applied = 0

    for record in records:
        plant_changes = changes_by_plant.get(record.code)
        if not plant_changes:
            plants.append(build_plant(record))
            continue

        changes_applied += len(plant_changes)
        plant = _build_plant_with_changes(record, plant_changes)
        if plant is None:
            omitted.append(
                OmittedPlant(
                    code=record.code,
                    name=record.name,
                    row_number=record.row_number,
                    reason="all unit groups have zero units after AC changes",
                )
            )
        else:
            plants.append(plant)

    logger.info(
        "Cadastre overlay: %d plant(s) built, %d plant(s) omitted, %d change(s) applied, "
        "%d change(s) ignored",
        len(plants),
        len(omitted),
        changes_applied,
        changes_ignored,
    )
    return OverlayResult(
        plants=plants,
        omitted=omitted,
        changes_applied=changes_applied,
        changes_ignored=changes_ignored,
    )
