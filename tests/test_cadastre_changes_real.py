"""Checks `read_cadastre_changes` against the reference deck's own `entdados.dat`."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest
from idessem.dessem import Entdados

from montador_uch.cadastre_changes import (
    GroupCountChange,
    UnitCountChange,
    UnitPowerChange,
    read_cadastre_changes,
)
from montador_uch.settings import Settings


@pytest.fixture
def entdados_path(deck_dir: Path) -> Path:
    path = deck_dir / Settings().entdados_filename
    if not path.is_file():
        pytest.skip(f"{path} not available")
    return path


def _read(entdados_path: Path) -> list[GroupCountChange | UnitCountChange | UnitPowerChange]:
    # Entdados.read is annotated as returning the base RegisterFile type; pipeline.py casts
    # for the same reason.
    entdados = cast(Entdados, Entdados.read(str(entdados_path)))
    return read_cadastre_changes(entdados, entdados_path)


def test_counts_match_the_reference_deck(entdados_path: Path) -> None:
    changes = _read(entdados_path)

    assert len(changes) == 36
    assert sum(isinstance(change, GroupCountChange) for change in changes) == 8
    assert sum(isinstance(change, UnitCountChange) for change in changes) == 15
    assert sum(isinstance(change, UnitPowerChange) for change in changes) == 13


def test_plant_275_opens_the_sequence(entdados_path: Path) -> None:
    changes = _read(entdados_path)

    assert changes[:3] == [
        GroupCountChange(275, 3),
        UnitCountChange(275, 1, 2),
        UnitCountChange(275, 2, 12),
    ]


def test_plant_287_sequence(entdados_path: Path) -> None:
    changes = _read(entdados_path)
    plant_287 = [change for change in changes if change.plant_code == 287]

    assert plant_287 == [
        GroupCountChange(287, 3),
        UnitCountChange(287, 1, 24),
        UnitPowerChange(287, 1, 73.3),
        UnitCountChange(287, 2, 20),
        UnitPowerChange(287, 2, 69.6),
        UnitCountChange(287, 3, 6),
        UnitPowerChange(287, 3, 69.6),
    ]

    powers = [change.power_mw for change in plant_287 if isinstance(change, UnitPowerChange)]
    assert powers == pytest.approx([73.3, 69.6, 69.6])
