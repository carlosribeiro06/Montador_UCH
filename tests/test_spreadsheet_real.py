"""Regression checks against the repository's own `UCH.xlsx`.

Skipped when the workbook is absent, since it is gitignored and supplied locally.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from montador_uch.model import AggregationLevel, HydroPlant
from montador_uch.settings import Settings
from montador_uch.spreadsheet import read_plants

WORKBOOK = Path(__file__).resolve().parents[1] / "UCH.xlsx"

pytestmark = pytest.mark.skipif(not WORKBOOK.is_file(), reason=f"{WORKBOOK} not available")


@pytest.fixture(scope="module")
def plants() -> list[HydroPlant]:
    defaults = Settings()
    return read_plants(WORKBOOK, defaults.sheet_name, defaults.header_row)


def test_expected_plant_and_unit_counts(plants: list[HydroPlant]) -> None:
    assert len(plants) == 156
    assert sum(len(plant.units) for plant in plants) == 750


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
