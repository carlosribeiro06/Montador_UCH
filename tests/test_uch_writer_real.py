"""Checks `study_end_stage` against the reference deck's own `entdados.dat`."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from idessem.dessem import Entdados

from montador_uch.settings import Settings
from montador_uch.uch_writer import STAGE_DURATION_COLUMN, study_end_stage


@pytest.fixture
def entdados_path(deck_dir: Path) -> Path:
    path = deck_dir / Settings().entdados_filename
    if not path.is_file():
        pytest.skip(f"{path} not available")
    return path


def test_matches_the_last_half_hour_tm_row(entdados_path: Path) -> None:
    duration = Settings().half_hour_stage_duration_h
    entdados = Entdados.read(str(entdados_path))

    stage = study_end_stage(entdados, duration)

    # Recompute independently from the TM table.
    frame = entdados.tm(df=True)
    assert isinstance(frame, pd.DataFrame)
    expected = frame[frame[STAGE_DURATION_COLUMN] == duration].iloc[-1]

    assert stage.day == int(expected["dia_inicial"])
    assert stage.hour == int(expected["hora_inicial"])
    assert stage.half_hour == int(expected["meia_hora_inicial"])


def test_returns_plain_ints(entdados_path: Path) -> None:
    stage = study_end_stage(
        Entdados.read(str(entdados_path)), Settings().half_hour_stage_duration_h
    )

    for value in (stage.day, stage.hour, stage.half_hour):
        assert type(value) is int
