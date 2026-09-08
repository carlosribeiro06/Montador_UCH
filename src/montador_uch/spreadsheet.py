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
"""

from __future__ import annotations

import logging
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


def _read_float(row: pd.Series[Any], column: str, row_number: int, code: int) -> float:
    raw = row[column]
    where = _where(row_number, column, code)
    if pd.isna(raw):
        raise SpreadsheetError(f"{where} is empty; a power in MW is required")
    if isinstance(raw, bool):
        raise SpreadsheetError(f"{where} must be a number, got a boolean")
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise SpreadsheetError(f"{where} must be a number, got {raw!r}") from exc


def _read_group(row: pd.Series[Any], position: int, row_number: int, code: int) -> UnitGroup | None:
    """Build the group at 0-based `position`, or `None` when it holds no units."""
    unit_count = _read_int(row, group_column(UNIT_COUNT_COLUMN, position), row_number, code)
    if unit_count < 0:
        raise SpreadsheetError(
            f"Row {row_number}, plant {code}: group {position + 1} has a negative unit count "
            f"{unit_count}"
        )
    if unit_count == 0:
        return None

    max_power_mw = _read_float(
        row, group_column(GROUP_MAX_POWER_COLUMN, position), row_number, code
    )
    min_power_mw = _read_float(row, group_column(START_UP_POWER_COLUMN, position), row_number, code)

    try:
        return UnitGroup(
            index=position + 1,
            max_power_mw=max_power_mw,
            units=tuple(
                GeneratingUnit(
                    index=unit_position + 1,
                    min_power_mw=min_power_mw,
                    max_power_mw=max_power_mw / unit_count,
                )
                for unit_position in range(unit_count)
            ),
        )
    except ValueError as exc:
        raise SpreadsheetError(f"Row {row_number}, plant {code}: {exc}") from exc


def _read_plant(
    row: pd.Series[Any], row_number: int, seen: dict[int, int], label: str
) -> HydroPlant:
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

    groups = [
        group
        for group in (
            _read_group(row, position, row_number, code) for position in range(group_count)
        )
        if group is not None
    ]
    if not groups:
        raise SpreadsheetError(
            f"Row {row_number}, plant {code} ({name}): UCH plant has no group with units"
        )

    try:
        plant = HydroPlant(code=code, name=name, aggregation=aggregation, groups=tuple(groups))
    except ValueError as exc:
        raise SpreadsheetError(f"Row {row_number}, plant {code} ({name}): {exc}") from exc

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


def read_plants(path: Path, sheet_name: str, header_row: int) -> list[HydroPlant]:
    """Read the plants modelled with UCH from the workbook at `path`.

    Rows whose `Tipo` is `Sem UCH` are skipped. Any other malformed row raises
    `SpreadsheetError` naming the plant code and the spreadsheet row.
    """
    logger.info(
        "Reading UCH spreadsheet %s (sheet %r, header row %d)", path, sheet_name, header_row
    )
    try:
        frame = pd.read_excel(path, sheet_name=sheet_name, header=header_row)
    except ValueError as exc:
        raise SpreadsheetError(f"Cannot read sheet {sheet_name!r} from {path}: {exc}") from exc
    _check_columns(frame, path)

    plants: list[HydroPlant] = []
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
        plants.append(_read_plant(row, row_number, seen, label))

    groups = sum(len(plant.groups) for plant in plants)
    units = sum(len(plant.units) for plant in plants)
    logger.info(
        "Read %d row(s): %d plant(s) with UCH, %d skipped as %r, %d group(s), %d unit(s)",
        len(frame),
        len(plants),
        skipped,
        NO_UCH_LABEL,
        groups,
        units,
    )
    return plants
