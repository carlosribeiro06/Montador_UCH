"""Regression checks against the repository's own `UCH.xlsx`.

Skipped when the workbook is absent, since it is supplied per machine.

The workbook currently holds four plants whose start-up power exceeds the corresponding maximum,
so the Gmin <= Gmax guard in `model` rejects it as a whole. Until those rows are corrected the
structural assertions run against a copy with those plants removed, and
`test_repository_workbook_is_currently_rejected` documents the defect. When the workbook is
fixed that test starts failing, which is the signal to drop `KNOWN_INVALID_PLANT_CODES` and
restore the full 156 / 207 / 750 expectations.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from montador_uch.model import AggregationLevel, HydroPlant
from montador_uch.settings import Settings
from montador_uch.spreadsheet import PLANT_CODE_COLUMN, SpreadsheetError, read_plants

WORKBOOK = Path(__file__).resolve().parents[1] / "UCH.xlsx"

pytestmark = pytest.mark.skipif(not WORKBOOK.is_file(), reason=f"{WORKBOOK} not available")

# Plants whose Potencia_de_acionamento exceeds the derived maximum; see the module docstring.
KNOWN_INVALID_PLANT_CODES = (195, 196, 241, 249)

EXPECTED_PLANTS = 152
EXPECTED_GROUPS = 202
EXPECTED_UNITS = 739

SETTINGS = Settings()


def test_repository_workbook_is_currently_rejected() -> None:
    """The whole workbook fails the Gmin <= Gmax guard, on plant 195 (JAURU) first."""
    with pytest.raises(SpreadsheetError, match=r"plant 195: Unit 1 minimum power 40.5 exceeds"):
        read_plants(WORKBOOK, SETTINGS.sheet_name, SETTINGS.header_row)


@pytest.fixture(scope="module")
def plants(tmp_path_factory: pytest.TempPathFactory) -> list[HydroPlant]:
    """The workbook with the known-invalid plants dropped, so the rest stays covered."""
    frame = pd.read_excel(WORKBOOK, sheet_name=SETTINGS.sheet_name, header=SETTINGS.header_row)
    usable = frame[~frame[PLANT_CODE_COLUMN].isin(KNOWN_INVALID_PLANT_CODES)]

    path = tmp_path_factory.mktemp("workbook") / "UCH.xlsx"
    with pd.ExcelWriter(path) as writer:
        # Re-create the banner row the real sheet carries above the column names.
        pd.DataFrame([["Cadastro de UCH"]]).to_excel(
            writer, sheet_name=SETTINGS.sheet_name, index=False, header=False
        )
        usable.to_excel(
            writer, sheet_name=SETTINGS.sheet_name, index=False, startrow=SETTINGS.header_row
        )
    return read_plants(path, SETTINGS.sheet_name, SETTINGS.header_row)


def test_expected_plant_group_and_unit_counts(plants: list[HydroPlant]) -> None:
    assert len(plants) == EXPECTED_PLANTS
    assert sum(len(plant.groups) for plant in plants) == EXPECTED_GROUPS
    assert sum(len(plant.units) for plant in plants) == EXPECTED_UNITS


def test_known_invalid_plants_are_the_only_ones_excluded(plants: list[HydroPlant]) -> None:
    codes = {plant.code for plant in plants}
    assert codes.isdisjoint(KNOWN_INVALID_PLANT_CODES)
    assert len(KNOWN_INVALID_PLANT_CODES) == 156 - EXPECTED_PLANTS


def test_every_plant_is_group_aggregated(plants: list[HydroPlant]) -> None:
    assert {plant.aggregation for plant in plants} == {AggregationLevel.GROUP}


def test_plant_codes_are_unique(plants: list[HydroPlant]) -> None:
    codes = [plant.code for plant in plants]
    assert len(set(codes)) == len(codes)


def test_furnas_derived_limits(plants: list[HydroPlant]) -> None:
    furnas = next(plant for plant in plants if plant.code == 6)

    assert furnas.name == "FURNAS"
    assert len(furnas.groups) == 2
    assert furnas.max_power_mw == pytest.approx(1216.0)
    assert furnas.min_power_mw == pytest.approx(101.0)
    assert [group.max_power_mw for group in furnas.groups] == pytest.approx([912.0, 304.0])
    assert len(furnas.units) == 8


def test_no_plant_has_more_than_five_groups(plants: list[HydroPlant]) -> None:
    assert max(len(plant.groups) for plant in plants) <= 5


def test_every_surviving_plant_has_usable_limits(plants: list[HydroPlant]) -> None:
    for plant in plants:
        assert plant.min_power_mw <= plant.max_power_mw
        for group in plant.groups:
            assert group.min_power_mw <= group.max_power_mw
