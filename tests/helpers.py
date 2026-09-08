"""Pure test helpers: synthetic `UCH` workbooks and lookup of the reference deck.

Test data is always built at run time under `tmp_path`; `*.xlsx` and `*.csv` are gitignored, so
no fixture file is ever committed.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from openpyxl import Workbook

from montador_uch.spreadsheet import (
    AGGREGATION_COLUMN,
    GROUP_COUNT_COLUMN,
    GROUP_MAX_POWER_COLUMN,
    PLANT_CODE_COLUMN,
    PLANT_NAME_COLUMN,
    START_UP_POWER_COLUMN,
    UNIT_COUNT_COLUMN,
    group_column,
    required_columns,
)

DEFAULT_SAMPLE_DECK = Path("/home/carlosribeiro/git/DS_ONS_092026_RV0D02")
SAMPLE_DECK_ENV_VAR = "MONTADOR_UCH_SAMPLE_DECK"


def sample_deck() -> Path | None:
    """The reference DESSEM deck, or `None` when it is not available on this machine."""
    override = os.environ.get(SAMPLE_DECK_ENV_VAR)
    deck = Path(override) if override else DEFAULT_SAMPLE_DECK
    return deck if deck.is_dir() else None


def write_uch_workbook(path: Path, rows: Sequence[Mapping[str, object]]) -> Path:
    """Write a workbook shaped like `UCH.xlsx`: a banner row, the column names, then `rows`.

    Columns absent from a row are written as blanks, which is how the real workbook represents
    an unused unit group.
    """
    columns = required_columns()
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "UCH"

    sheet.append(["Cadastro de UCH"])
    sheet.append(columns)
    for row in rows:
        unknown = set(row) - set(columns)
        assert not unknown, f"unknown column(s) in test row: {sorted(unknown)}"
        sheet.append([row.get(column) for column in columns])

    workbook.save(path)
    return path


def plant_row(
    code: int,
    name: str,
    aggregation: str,
    groups: Sequence[tuple[int, float, float]],
) -> dict[str, object]:
    """One workbook row: `groups` holds `(unit count, per-unit minimum MW, group total MW)`."""
    row: dict[str, object] = {
        PLANT_CODE_COLUMN: code,
        PLANT_NAME_COLUMN: name,
        AGGREGATION_COLUMN: aggregation,
        GROUP_COUNT_COLUMN: len(groups),
    }
    for position, (unit_count, min_power_mw, max_power_mw) in enumerate(groups):
        row[group_column(UNIT_COUNT_COLUMN, position)] = unit_count
        row[group_column(START_UP_POWER_COLUMN, position)] = min_power_mw
        row[group_column(GROUP_MAX_POWER_COLUMN, position)] = max_power_mw
    return row
