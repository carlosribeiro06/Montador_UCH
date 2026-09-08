"""Tests for the `UCH` sheet reader, on workbooks built at run time."""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from helpers import plant_row, write_uch_workbook
from montador_uch.model import AggregationLevel
from montador_uch.spreadsheet import (
    AGGREGATION_COLUMN,
    GROUP_COUNT_COLUMN,
    GROUP_MAX_POWER_COLUMN,
    MAX_GROUPS,
    PLANT_CODE_COLUMN,
    PLANT_NAME_COLUMN,
    START_UP_POWER_COLUMN,
    UNIT_COUNT_COLUMN,
    SpreadsheetError,
    build_plant,
    group_column,
    read_plants,
    read_records,
)

SHEET = "UCH"
HEADER_ROW = 1


def _read(path: Path) -> list[object]:
    return list(read_plants(path, SHEET, HEADER_ROW))


def _workbook(tmp_path: Path, *rows: dict[str, object]) -> Path:
    return write_uch_workbook(tmp_path / "UCH.xlsx", rows)


def test_single_group_plant(tmp_path: Path) -> None:
    path = _workbook(tmp_path, plant_row(6, "FURNAS", "Conjunto", [(2, 23.0, 46.0)]))
    plants = read_plants(path, SHEET, HEADER_ROW)

    assert len(plants) == 1
    plant = plants[0]
    assert plant.code == 6
    assert plant.name == "FURNAS"
    assert plant.aggregation is AggregationLevel.GROUP
    assert len(plant.groups) == 1
    assert plant.groups[0].index == 1
    assert plant.groups[0].max_power_mw == pytest.approx(46.0)
    assert plant.groups[0].min_power_mw == pytest.approx(23.0)


def test_unit_maximum_is_the_group_total_split_by_unit_count(tmp_path: Path) -> None:
    path = _workbook(tmp_path, plant_row(1, "A", "Conjunto", [(2, 10.0, 46.0)]))
    units = read_plants(path, SHEET, HEADER_ROW)[0].units

    assert [unit.index for unit in units] == [1, 2]
    for unit in units:
        assert unit.max_power_mw == pytest.approx(23.0)
        assert unit.min_power_mw == pytest.approx(10.0)


def test_plant_name_is_stripped(tmp_path: Path) -> None:
    path = _workbook(tmp_path, plant_row(6, "FURNAS      ", "Conjunto", [(1, 5.0, 10.0)]))
    assert read_plants(path, SHEET, HEADER_ROW)[0].name == "FURNAS"


def test_multi_group_plant_with_a_zero_unit_group(tmp_path: Path) -> None:
    path = _workbook(
        tmp_path,
        plant_row(
            6,
            "FURNAS",
            "Conjunto",
            [(6, 101.0, 912.0), (0, 0.0, 0.0), (2, 101.0, 304.0)],
        ),
    )
    plant = read_plants(path, SHEET, HEADER_ROW)[0]

    # The empty group is dropped, but the surviving groups keep their spreadsheet positions.
    assert [group.index for group in plant.groups] == [1, 3]
    assert len(plant.units) == 8
    assert plant.max_power_mw == pytest.approx(1216.0)
    assert plant.min_power_mw == pytest.approx(101.0)


def test_all_three_aggregation_labels_are_accepted(tmp_path: Path) -> None:
    path = _workbook(
        tmp_path,
        plant_row(1, "U", "Unidade", [(2, 5.0, 20.0)]),
        plant_row(2, "C", "Conjunto", [(2, 5.0, 20.0)]),
        plant_row(3, "P", "Usina", [(2, 5.0, 20.0)]),
    )
    plants = read_plants(path, SHEET, HEADER_ROW)

    assert [plant.aggregation for plant in plants] == [
        AggregationLevel.UNIT,
        AggregationLevel.GROUP,
        AggregationLevel.PLANT,
    ]


def test_sem_uch_rows_are_skipped(tmp_path: Path) -> None:
    path = _workbook(
        tmp_path,
        plant_row(1, "KEEP", "Conjunto", [(1, 5.0, 10.0)]),
        plant_row(2, "DROP", "Sem UCH", [(1, 5.0, 10.0)]),
        plant_row(3, "KEEP2", "Conjunto", [(1, 5.0, 10.0)]),
    )
    plants = read_plants(path, SHEET, HEADER_ROW)

    assert [plant.code for plant in plants] == [1, 3]


def test_sem_uch_row_may_be_incomplete(tmp_path: Path) -> None:
    """Skipped rows are never validated, so a blank `Sem UCH` row must not fail the run."""
    path = _workbook(
        tmp_path,
        {"Nome": "NO CODE", "Tipo": "Sem UCH"},
        plant_row(3, "KEEP", "Conjunto", [(1, 5.0, 10.0)]),
    )
    assert [plant.code for plant in read_plants(path, SHEET, HEADER_ROW)] == [3]


def test_unknown_aggregation_label_raises(tmp_path: Path) -> None:
    path = _workbook(tmp_path, plant_row(7, "X", "Reservatorio", [(1, 5.0, 10.0)]))
    with pytest.raises(SpreadsheetError, match=r"plant 7: Unknown aggregation label"):
        _read(path)


def test_non_text_aggregation_raises(tmp_path: Path) -> None:
    row = plant_row(7, "X", "Conjunto", [(1, 5.0, 10.0)])
    row["Tipo"] = 3
    path = _workbook(tmp_path, row)
    with pytest.raises(SpreadsheetError, match=r"'Tipo' must be text"):
        _read(path)


def test_missing_code_raises(tmp_path: Path) -> None:
    row = plant_row(7, "X", "Conjunto", [(1, 5.0, 10.0)])
    del row[PLANT_CODE_COLUMN]
    path = _workbook(tmp_path, row)
    with pytest.raises(SpreadsheetError, match=r"'Código' is empty"):
        _read(path)


def test_duplicate_code_raises_naming_both_rows(tmp_path: Path) -> None:
    path = _workbook(
        tmp_path,
        plant_row(7, "A", "Conjunto", [(1, 5.0, 10.0)]),
        plant_row(7, "B", "Conjunto", [(1, 5.0, 10.0)]),
    )
    with pytest.raises(
        SpreadsheetError, match=r"Row 4: duplicate plant code 7, already read on row 3"
    ):
        _read(path)


def test_non_integer_group_count_raises(tmp_path: Path) -> None:
    row = plant_row(7, "X", "Conjunto", [(1, 5.0, 10.0)])
    row[GROUP_COUNT_COLUMN] = 1.5
    path = _workbook(tmp_path, row)
    with pytest.raises(SpreadsheetError, match=r"'N_conjuntos' must be an integer"):
        _read(path)


def test_group_count_above_maximum_raises(tmp_path: Path) -> None:
    row = plant_row(7, "X", "Conjunto", [(1, 5.0, 10.0)])
    row[GROUP_COUNT_COLUMN] = MAX_GROUPS + 1
    path = _workbook(tmp_path, row)
    with pytest.raises(SpreadsheetError, match=r"'N_conjuntos' must be between 1 and 5, got 6"):
        _read(path)


def test_zero_group_count_raises(tmp_path: Path) -> None:
    row = plant_row(7, "X", "Conjunto", [(1, 5.0, 10.0)])
    row[GROUP_COUNT_COLUMN] = 0
    path = _workbook(tmp_path, row)
    with pytest.raises(SpreadsheetError, match=r"'N_conjuntos' must be between 1 and 5, got 0"):
        _read(path)


def test_non_integer_unit_count_raises(tmp_path: Path) -> None:
    row = plant_row(7, "X", "Conjunto", [(1, 5.0, 10.0)])
    row["Nmaqs"] = 2.5
    path = _workbook(tmp_path, row)
    with pytest.raises(SpreadsheetError, match=r"'Nmaqs' must be an integer"):
        _read(path)


def test_negative_unit_count_raises(tmp_path: Path) -> None:
    row = plant_row(7, "X", "Conjunto", [(1, 5.0, 10.0)])
    row["Nmaqs"] = -1
    path = _workbook(tmp_path, row)
    with pytest.raises(SpreadsheetError, match=r"negative unit count"):
        _read(path)


def test_missing_start_up_power_on_active_group_raises(tmp_path: Path) -> None:
    row = plant_row(7, "X", "Conjunto", [(2, 5.0, 10.0)])
    del row["Potencia_de_acionamento"]
    path = _workbook(tmp_path, row)
    with pytest.raises(SpreadsheetError, match=r"'Potencia_de_acionamento' is empty"):
        _read(path)


def test_missing_group_maximum_on_active_group_raises(tmp_path: Path) -> None:
    row = plant_row(7, "X", "Conjunto", [(2, 5.0, 10.0)])
    del row["Potencia_maxima"]
    path = _workbook(tmp_path, row)
    with pytest.raises(SpreadsheetError, match=r"'Potencia_maxima' is empty"):
        _read(path)


def test_negative_power_raises(tmp_path: Path) -> None:
    path = _workbook(tmp_path, plant_row(7, "X", "Conjunto", [(2, -5.0, 10.0)]))
    with pytest.raises(SpreadsheetError, match=r"plant 7: Unit 1 minimum power must not be"):
        _read(path)


def test_start_up_power_above_unit_maximum_raises(tmp_path: Path) -> None:
    """GUAPORE in the real workbook: 41.4 MW start-up against a 120/3 = 40 MW unit maximum."""
    path = _workbook(tmp_path, plant_row(196, "GUAPORE", "Conjunto", [(3, 41.4, 120.0)]))
    with pytest.raises(
        SpreadsheetError,
        match=r"Row 3, plant 196: Unit 1 minimum power 41.4 exceeds its maximum 40.0",
    ):
        _read(path)


def test_start_up_power_above_group_total_raises(tmp_path: Path) -> None:
    """JAURU group 2 in the real workbook: one unit of 39.4 MW with a 40.5 MW start-up."""
    path = _workbook(tmp_path, plant_row(195, "JAURU", "Conjunto", [(1, 40.5, 39.4)]))
    with pytest.raises(SpreadsheetError, match=r"plant 195: Unit 1 minimum power 40.5 exceeds"):
        _read(path)


def test_equal_minimum_and_maximum_is_accepted(tmp_path: Path) -> None:
    path = _workbook(tmp_path, plant_row(1, "TIGHT", "Conjunto", [(2, 23.0, 46.0)]))
    plant = read_plants(path, SHEET, HEADER_ROW)[0]

    assert plant.groups[0].min_power_mw == pytest.approx(23.0)
    assert plant.units[0].max_power_mw == pytest.approx(23.0)


def test_plant_with_only_empty_groups_raises(tmp_path: Path) -> None:
    path = _workbook(tmp_path, plant_row(7, "X", "Conjunto", [(0, 0.0, 0.0), (0, 0.0, 0.0)]))
    with pytest.raises(SpreadsheetError, match=r"UCH plant has no group with units"):
        _read(path)


def test_missing_required_columns_are_listed(tmp_path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = SHEET
    sheet.append(["Cadastro de UCH"])
    sheet.append([PLANT_CODE_COLUMN, "Nome"])
    sheet.append([6, "FURNAS"])

    path = tmp_path / "broken.xlsx"
    workbook.save(path)

    with pytest.raises(SpreadsheetError) as failure:
        _read(path)

    message = str(failure.value)
    assert "missing required column(s)" in message
    for column in ("Tipo", "N_conjuntos", "Nmaqs", "Potencia_maxima.4"):
        assert column in message
    assert PLANT_CODE_COLUMN not in message.split(":")[-1]


def test_unknown_sheet_name_raises(tmp_path: Path) -> None:
    path = _workbook(tmp_path, plant_row(1, "A", "Conjunto", [(1, 5.0, 10.0)]))
    with pytest.raises(SpreadsheetError, match=r"Cannot read sheet 'ABSENT'"):
        read_plants(path, "ABSENT", HEADER_ROW)


def test_group_column_suffixes(tmp_path: Path) -> None:
    assert group_column("Nmaqs", 0) == "Nmaqs"
    assert group_column("Nmaqs", 1) == "Nmaqs.1"
    assert group_column("Potencia_maxima", 4) == "Potencia_maxima.4"


def test_logs_counts_at_info(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = _workbook(
        tmp_path,
        plant_row(1, "A", "Conjunto", [(2, 5.0, 20.0)]),
        plant_row(2, "B", "Sem UCH", [(1, 5.0, 10.0)]),
    )
    with caplog.at_level("INFO", logger="montador_uch.spreadsheet"):
        read_plants(path, SHEET, HEADER_ROW)

    assert "1 plant(s) with UCH" in caplog.text
    assert "1 skipped" in caplog.text
    assert "2 unit(s)" in caplog.text


def test_record_always_has_five_group_positions(tmp_path: Path) -> None:
    path = _workbook(tmp_path, plant_row(6, "FURNAS", "Conjunto", [(2, 23.0, 46.0)]))
    record = read_records(path, SHEET, HEADER_ROW)[0]

    assert len(record.groups) == MAX_GROUPS
    assert [group.index for group in record.groups] == list(range(1, MAX_GROUPS + 1))
    assert record.code == 6
    assert record.name == "FURNAS"
    assert record.row_number == 3
    assert record.aggregation is AggregationLevel.GROUP
    assert record.group_count == 1


def test_record_exposes_min_power_of_a_zero_unit_group(tmp_path: Path) -> None:
    """Plant 287 in the real workbook: group 2 keeps a start-up power despite `Nmaqs.2 = 0`."""
    row = {
        PLANT_CODE_COLUMN: 287,
        PLANT_NAME_COLUMN: "SAMPLE",
        AGGREGATION_COLUMN: "Conjunto",
        GROUP_COUNT_COLUMN: 2,
        group_column(UNIT_COUNT_COLUMN, 0): 6,
        group_column(START_UP_POWER_COLUMN, 0): 101.0,
        group_column(GROUP_MAX_POWER_COLUMN, 0): 912.0,
        group_column(UNIT_COUNT_COLUMN, 1): 0,
        group_column(START_UP_POWER_COLUMN, 1): 21.0,
        group_column(GROUP_MAX_POWER_COLUMN, 1): 0.0,
    }
    path = write_uch_workbook(tmp_path / "UCH.xlsx", [row])
    record = read_records(path, SHEET, HEADER_ROW)[0]

    zero_unit_group = record.groups[1]
    assert zero_unit_group.unit_count == 0
    assert zero_unit_group.min_power_mw == pytest.approx(21.0)
    assert zero_unit_group.max_power_mw == pytest.approx(0.0)


def test_record_exposes_a_position_beyond_group_count(tmp_path: Path) -> None:
    row = {
        PLANT_CODE_COLUMN: 1,
        PLANT_NAME_COLUMN: "X",
        AGGREGATION_COLUMN: "Conjunto",
        GROUP_COUNT_COLUMN: 1,
        group_column(UNIT_COUNT_COLUMN, 0): 2,
        group_column(START_UP_POWER_COLUMN, 0): 5.0,
        group_column(GROUP_MAX_POWER_COLUMN, 0): 20.0,
        group_column(START_UP_POWER_COLUMN, 2): 99.0,
    }
    path = write_uch_workbook(tmp_path / "UCH.xlsx", [row])
    record = read_records(path, SHEET, HEADER_ROW)[0]

    beyond_group_count = record.groups[2]
    assert beyond_group_count.unit_count == 0
    assert beyond_group_count.min_power_mw == pytest.approx(99.0)
    assert beyond_group_count.max_power_mw is None


def test_blank_cells_beyond_the_first_group_default_to_zero_and_none(tmp_path: Path) -> None:
    path = _workbook(tmp_path, plant_row(1, "A", "Conjunto", [(2, 5.0, 20.0)]))
    record = read_records(path, SHEET, HEADER_ROW)[0]

    for position in range(1, MAX_GROUPS):
        blank_group = record.groups[position]
        assert blank_group.unit_count == 0
        assert blank_group.min_power_mw is None
        assert blank_group.max_power_mw is None


def test_build_plant_of_a_record_matches_read_plants(tmp_path: Path) -> None:
    path = _workbook(
        tmp_path,
        plant_row(
            6,
            "FURNAS",
            "Conjunto",
            [(6, 101.0, 912.0), (0, 0.0, 0.0), (2, 101.0, 304.0)],
        ),
    )
    record = read_records(path, SHEET, HEADER_ROW)[0]

    assert build_plant(record) == read_plants(path, SHEET, HEADER_ROW)[0]
