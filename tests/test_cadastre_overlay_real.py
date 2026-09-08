"""Regression checks for the cadastre overlay against the reference deck and workbook.

Skipped when either the reference deck or the repository workbook is absent, since both are
supplied per machine. The deck-availability check is `sample_deck()` from `tests/helpers.py`
(the same one `conftest.py`'s `deck_dir` fixture uses) rather than that function-scoped fixture
itself, so the expensive read of the 156-row workbook and the ~5300-line `entdados.dat` happens
once per module, mirroring the module-scoped `plants` fixture of `tests/test_spreadsheet_real.py`.

The workbook currently carries four plants whose start-up power exceeds the derived maximum
(Gmin > Gmax); `build_plant` rejects them regardless of any cadastre change (see
`tests/test_spreadsheet_real.py`), so they are filtered out of the record list before the
overlay runs, same as that module does for the plain workbook read.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from idessem.dessem import Entdados

from helpers import SAMPLE_DECK_ENV_VAR, sample_deck
from montador_uch.cadastre_changes import read_cadastre_changes
from montador_uch.cadastre_overlay import OverlayResult, apply_cadastre_changes
from montador_uch.model import HydroPlant
from montador_uch.settings import Settings
from montador_uch.spreadsheet import PlantRecord, build_plant, read_records

WORKBOOK = Path(__file__).resolve().parents[1] / "UCH.xlsx"

pytestmark = pytest.mark.skipif(not WORKBOOK.is_file(), reason=f"{WORKBOOK} not available")

# Same four rows test_spreadsheet_real.py excludes; see that module's docstring for the defect.
KNOWN_INVALID_PLANT_CODES = (195, 196, 241, 249)

CHANGED_OR_OMITTED_PLANT_CODES = (275, 287, 288, 174, 11, 9, 33, 74, 76, 87, 112)

SETTINGS = Settings()


@pytest.fixture(scope="module")
def entdados_path() -> Path:
    deck = sample_deck()
    if deck is None:
        pytest.skip(f"reference deck not available (set {SAMPLE_DECK_ENV_VAR})")
    path = deck / SETTINGS.entdados_filename
    if not path.is_file():
        pytest.skip(f"{path} not available")
    return path


@pytest.fixture(scope="module")
def records() -> list[PlantRecord]:
    return [
        record
        for record in read_records(WORKBOOK, SETTINGS.sheet_name, SETTINGS.header_row)
        if record.code not in KNOWN_INVALID_PLANT_CODES
    ]


@pytest.fixture(scope="module")
def overlay_result(records: list[PlantRecord], entdados_path: Path) -> OverlayResult:
    """The reference deck's AC changes applied on the workbook, invalid rows already dropped."""
    entdados = cast(Entdados, Entdados.read(str(entdados_path)))
    changes = read_cadastre_changes(entdados, entdados_path)
    return apply_cadastre_changes(records, changes)


def _plant(overlay_result: OverlayResult, code: int) -> HydroPlant:
    return next(plant for plant in overlay_result.plants if plant.code == code)


def test_change_and_omission_counts(overlay_result: OverlayResult) -> None:
    assert overlay_result.changes_applied == 36
    assert overlay_result.changes_ignored == 0
    assert tuple(omitted.code for omitted in overlay_result.omitted) == (87, 112)


def test_plant_287_split_into_three_groups(overlay_result: OverlayResult) -> None:
    plant = _plant(overlay_result, 287)

    assert [group.index for group in plant.groups] == [1, 2, 3]
    assert [len(group.units) for group in plant.groups] == [24, 20, 6]
    assert [group.max_power_mw for group in plant.groups] == pytest.approx([1759.2, 1392.0, 417.6])
    assert [group.min_power_mw for group in plant.groups] == pytest.approx([21.0, 11.0, 21.0])
    assert [group.units[0].max_power_mw for group in plant.groups] == pytest.approx(
        [73.3, 69.6, 69.6]
    )


def test_plant_275_group_3_cut_to_ten_units(overlay_result: OverlayResult) -> None:
    plant = _plant(overlay_result, 275)
    group_3 = next(group for group in plant.groups if group.index == 3)

    assert len(group_3.units) == 10
    assert group_3.max_power_mw == pytest.approx(3900.0)
    assert group_3.units[0].max_power_mw == pytest.approx(390.0)


def test_plant_288_single_group_of_sixteen_units(overlay_result: OverlayResult) -> None:
    plant = _plant(overlay_result, 288)

    assert len(plant.groups) == 1
    group = plant.groups[0]
    assert len(group.units) == 16
    assert group.max_power_mw == pytest.approx(16 * 611.111)
    assert group.min_power_mw == pytest.approx(450.0)


def test_plant_174_group_2_cut_to_one_unit(overlay_result: OverlayResult) -> None:
    plant = _plant(overlay_result, 174)
    group_2 = next(group for group in plant.groups if group.index == 2)

    assert len(group_2.units) == 1
    assert group_2.max_power_mw == pytest.approx(70.0)


def test_plant_11_group_1_cut_to_three_units(overlay_result: OverlayResult) -> None:
    plant = _plant(overlay_result, 11)
    group_1 = next(group for group in plant.groups if group.index == 1)

    assert len(group_1.units) == 3
    assert group_1.max_power_mw == pytest.approx(285.0)


@pytest.mark.parametrize(
    ("code", "total"),
    [(9, 424.0), (33, 1710.0), (74, 1676.0), (76, 1260.0)],
)
def test_single_group_plants_reaffirmed_by_nummaq_and_potefe(
    overlay_result: OverlayResult, code: int, total: float
) -> None:
    """Changes reaffirm the workbook: NUMMAQ and POTEFE both applied, total unchanged."""
    plant = _plant(overlay_result, code)

    assert len(plant.groups) == 1
    assert plant.groups[0].max_power_mw == pytest.approx(total)


def test_87_and_112_are_omitted_from_the_built_plants(overlay_result: OverlayResult) -> None:
    codes = {plant.code for plant in overlay_result.plants}
    assert 87 not in codes
    assert 112 not in codes


def test_every_unchanged_plant_matches_build_plant(
    overlay_result: OverlayResult, records: list[PlantRecord]
) -> None:
    """Plants the overlay never touched must equal what `build_plant` alone would produce."""
    records_by_code = {record.code: record for record in records}
    unchanged_plants = [
        plant for plant in overlay_result.plants if plant.code not in CHANGED_OR_OMITTED_PLANT_CODES
    ]
    assert unchanged_plants
    for plant in unchanged_plants:
        assert plant == build_plant(records_by_code[plant.code])
