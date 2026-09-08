"""Reader for the `UCH` sheet of the base workbook.

Sheet contract (verified on `UCH.xlsx`, 2026-09-08)
---------------------------------------------------
Two header rows; the column names live on the 0-based `header_row`, so the data starts at
spreadsheet row `header_row + 2`.

Per-plant columns: `Código`, `Nome`, `Tipo`, `N_conjuntos`.
Per-group columns repeat `MAX_GROUPS` times with the pandas suffixes ``""``, `.1` ... `.4`:
`Nmaqs`, `Potencia_de_acionamento`, `Potencia_maxima`.

`Potencia_maxima` is the group total in MW; `Potencia_de_acionamento` is the per-unit minimum in
MW, shared by every unit of the group. `Pmin_usina`, `Pmin_conjunto*` and `Regularização` are
essentially empty in the current workbook and are ignored, as the legacy script does.

The reader is split in two stages. `read_records` reads every row into a `PlantRecord` that
exposes all `MAX_GROUPS` group positions verbatim (including a start-up power kept on a group the
workbook otherwise leaves at zero units), with only the checks that make sense on the raw cells.
`build_plant` then turns a record into the validated `HydroPlant` domain object; a later overlay
step can rewrite a `PlantRecord` between the two stages before the domain object is built.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pandas as pd

from montador_uch.model import AggregationLevel, GeneratingUnit, HydroPlant, UnitGroup

logger = logging.getLogger(__name__)

PLANT_CODE_COLUMN: Final = "Código"
PLANT_NAME_COLUMN: Final = "Nome"
AGGREGATION_COLUMN: Final = "Tipo"
GROUP_COUNT_COLUMN: Final = "N_conjuntos"
UNIT_COUNT_COLUMN: Final = "Nmaqs"
START_UP_POWER_COLUMN: Final = "Potencia_de_acionamento"
GROUP_MAX_POWER_COLUMN: Final = "Potencia_maxima"

NO_UCH_LABEL: Final = "Sem UCH"
MAX_GROUPS: Final = 5

PLANT_COLUMNS: Final = (
    PLANT_CODE_COLUMN,
    PLANT_NAME_COLUMN,
    AGGREGATION_COLUMN,
    GROUP_COUNT_COLUMN,
)
GROUP_COLUMNS: Final = (UNIT_COUNT_COLUMN, START_UP_POWER_COLUMN, GROUP_MAX_POWER_COLUMN)


class SpreadsheetError(Exception):
    """Raised when the workbook cannot be read or a row violates the sheet contract."""


@dataclass(frozen=True, slots=True)
class GroupRecord:
    """One unit group position exactly as read from the sheet, before model validation."""

    index: int
    unit_count: int
    min_power_mw: float | None
    max_power_mw: float | None


@dataclass(frozen=True, slots=True)
class PlantRecord:
    """One UCH plant row exactly as read from the sheet, before model validation.

    `groups` always holds `MAX_GROUPS` positions with `groups[i].index == i + 1`; only
    `groups[:group_count]` are the plant's active positions, the rest are the sheet's unused
    columns kept verbatim for a later overlay step to inspect or rewrite.
    """

    code: int
    name: str
    row_number: int
    aggregation: AggregationLevel
    group_count: int
    groups: tuple[GroupRecord, ...]


def group_column(column: str, position: int) -> str:
    """The pandas column name of `column` for the 0-based group `position`."""
    return column if position == 0 else f"{column}.{position}"


def required_columns() -> list[str]:
    """Every column the reader needs, in sheet order."""
    return [
        *PLANT_COLUMNS,
        *(
            group_column(column, position)
            for position in range(MAX_GROUPS)
            for column in GROUP_COLUMNS
        ),
    ]


def _where(row_number: int, column: str, code: int | None) -> str:
    plant = "" if code is None else f", plant {code}"
    return f"Row {row_number}{plant}: column {column!r}"


def _read_int(row: pd.Series[Any], column: str, row_number: int, code: int | None = None) -> int:
    raw = row[column]
    where = _where(row_number, column, code)
    if pd.isna(raw):
        raise SpreadsheetError(f"{where} is empty; an integer is required")
    if isinstance(raw, bool):
        raise SpreadsheetError(f"{where} must be an integer, got a boolean")
    try:
        numeric = float(raw)
    except (TypeError, ValueError) as exc:
        raise SpreadsheetError(f"{where} must be an integer, got {raw!r}") from exc
    if not numeric.is_integer():
        raise SpreadsheetError(f"{where} must be an integer, got {raw!r}")
    return int(numeric)


def _read_optional_float(
    row: pd.Series[Any], column: str, row_number: int, code: int
) -> float | None:
    """Like a required float read, but a blank cell reads as `None` instead of raising."""
    raw = row[column]
    if pd.isna(raw):
        return None
    where = _where(row_number, column, code)
    if isinstance(raw, bool):
        raise SpreadsheetError(f"{where} must be a number, got a boolean")
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise SpreadsheetError(f"{where} must be a number, got {raw!r}") from exc


def _read_group_record(
    row: pd.Series[Any], position: int, row_number: int, code: int
) -> GroupRecord:
    """Read the raw group at 0-based `position`; a blank unit count defaults to zero."""
    raw_unit_count = row[group_column(UNIT_COUNT_COLUMN, position)]
    if pd.isna(raw_unit_count):
        unit_count = 0
    else:
        unit_count = _read_int(row, group_column(UNIT_COUNT_COLUMN, position), row_number, code)
        if unit_count < 0:
            raise SpreadsheetError(
                f"Row {row_number}, plant {code}: group {position + 1} has a negative unit "
                f"count {unit_count}"
            )

    return GroupRecord(
        index=position + 1,
        unit_count=unit_count,
        min_power_mw=_read_optional_float(
            row, group_column(START_UP_POWER_COLUMN, position), row_number, code
        ),
        max_power_mw=_read_optional_float(
            row, group_column(GROUP_MAX_POWER_COLUMN, position), row_number, code
        ),
    )


def _read_plant_record(
    row: pd.Series[Any], row_number: int, seen: dict[int, int], label: str
) -> PlantRecord:
    code = _read_int(row, PLANT_CODE_COLUMN, row_number)
    if code in seen:
        raise SpreadsheetError(
            f"Row {row_number}: duplicate plant code {code}, already read on row {seen[code]}"
        )
    seen[code] = row_number

    name = str(row[PLANT_NAME_COLUMN]).strip()
    try:
        aggregation = AggregationLevel.from_label(label)
    except ValueError as exc:
        raise SpreadsheetError(f"Row {row_number}, plant {code}: {exc}") from exc

    group_count = _read_int(row, GROUP_COUNT_COLUMN, row_number, code)
    if not 1 <= group_count <= MAX_GROUPS:
        raise SpreadsheetError(
            f"Row {row_number}, plant {code}: column {GROUP_COUNT_COLUMN!r} must be between 1 "
            f"and {MAX_GROUPS}, got {group_count}"
        )

    groups = tuple(
        _read_group_record(row, position, row_number, code) for position in range(MAX_GROUPS)
    )
    return PlantRecord(
        code=code,
        name=name,
        row_number=row_number,
        aggregation=aggregation,
        group_count=group_count,
        groups=groups,
    )


def _build_group(group: GroupRecord, row_number: int, code: int) -> UnitGroup:
    """Turn an active, non-empty `GroupRecord` into a `UnitGroup`, requiring both limits."""
    if group.max_power_mw is None:
        where = _where(row_number, group_column(GROUP_MAX_POWER_COLUMN, group.index - 1), code)
        raise SpreadsheetError(f"{where} is empty; a power in MW is required")
    if group.min_power_mw is None:
        where = _where(row_number, group_column(START_UP_POWER_COLUMN, group.index - 1), code)
        raise SpreadsheetError(f"{where} is empty; a power in MW is required")

    try:
        return UnitGroup(
            index=group.index,
            max_power_mw=group.max_power_mw,
            units=tuple(
                GeneratingUnit(
                    index=unit_position + 1,
                    min_power_mw=group.min_power_mw,
                    max_power_mw=group.max_power_mw / group.unit_count,
                )
                for unit_position in range(group.unit_count)
            ),
        )
    except ValueError as exc:
        raise SpreadsheetError(f"Row {row_number}, plant {code}: {exc}") from exc


def build_plant(record: PlantRecord) -> HydroPlant:
    """Turn a raw `PlantRecord` into a validated `HydroPlant`.

    Only positions before `record.group_count` are considered; a group with no units is dropped.
    An active, non-empty group with a blank power limit or a limit rejected by the model raises
    `SpreadsheetError` with the wording `read_plants` has always used.
    """
    groups = [
        _build_group(group, record.row_number, record.code)
        for group in record.groups[: record.group_count]
        if group.unit_count > 0
    ]
    if not groups:
        raise SpreadsheetError(
            f"Row {record.row_number}, plant {record.code} ({record.name}): "
            "UCH plant has no group with units"
        )

    try:
        plant = HydroPlant(
            code=record.code,
            name=record.name,
            aggregation=record.aggregation,
            groups=tuple(groups),
        )
    except ValueError as exc:
        raise SpreadsheetError(
            f"Row {record.row_number}, plant {record.code} ({record.name}): {exc}"
        ) from exc

    logger.debug(
        "Plant %d (%s): %s, %d group(s), %d unit(s), %.3f-%.3f MW",
        plant.code,
        plant.name,
        plant.aggregation.name,
        len(plant.groups),
        len(plant.units),
        plant.min_power_mw,
        plant.max_power_mw,
    )
    return plant


def _check_columns(frame: pd.DataFrame, path: Path) -> None:
    missing = [column for column in required_columns() if column not in frame.columns]
    if missing:
        raise SpreadsheetError(
            f"Spreadsheet {path} is missing required column(s): {', '.join(missing)}"
        )


def read_records(path: Path, sheet_name: str, header_row: int) -> list[PlantRecord]:
    """Read one raw `PlantRecord` per UCH plant from the workbook at `path`.

    Rows whose `Tipo` is `Sem UCH` are skipped. Any other malformed row raises
    `SpreadsheetError` naming the plant code and the spreadsheet row. Every record carries all
    `MAX_GROUPS` group positions, whatever `N_conjuntos` says; `build_plant` is where a position
    beyond it stops mattering.
    """
    logger.info(
        "Reading UCH spreadsheet %s (sheet %r, header row %d)", path, sheet_name, header_row
    )
    try:
        frame = pd.read_excel(path, sheet_name=sheet_name, header=header_row)
    except ValueError as exc:
        raise SpreadsheetError(f"Cannot read sheet {sheet_name!r} from {path}: {exc}") from exc
    _check_columns(frame, path)

    records: list[PlantRecord] = []
    seen: dict[int, int] = {}
    skipped = 0

    for position, (_, row) in enumerate(frame.iterrows()):
        # Spreadsheet rows are 1-based and the column names sit on the 0-based `header_row`,
        # so the first data row is spreadsheet row `header_row + 2`.
        row_number = position + header_row + 2
        label = row[AGGREGATION_COLUMN]
        if not isinstance(label, str):
            raise SpreadsheetError(
                f"Row {row_number}: column {AGGREGATION_COLUMN!r} must be text, got {label!r}"
            )
        if label == NO_UCH_LABEL:
            skipped += 1
            continue
        records.append(_read_plant_record(row, row_number, seen, label))

    # Identical to summing `len(plant.groups)` / `len(plant.units)` over the plants `build_plant`
    # would construct from these records: both only count active, non-empty group positions.
    groups = sum(
        sum(1 for group in record.groups[: record.group_count] if group.unit_count > 0)
        for record in records
    )
    units = sum(
        sum(
            group.unit_count
            for group in record.groups[: record.group_count]
            if group.unit_count > 0
        )
        for record in records
    )
    logger.info(
        "Read %d row(s): %d plant(s) with UCH, %d skipped as %r, %d group(s), %d unit(s)",
        len(frame),
        len(records),
        skipped,
        NO_UCH_LABEL,
        groups,
        units,
    )
    return records


def read_plants(path: Path, sheet_name: str, header_row: int) -> list[HydroPlant]:
    """Read the plants modelled with UCH from the workbook at `path`.

    Rows whose `Tipo` is `Sem UCH` are skipped. Any other malformed row raises
    `SpreadsheetError` naming the plant code and the spreadsheet row.
    """
    return [build_plant(record) for record in read_records(path, sheet_name, header_row)]
