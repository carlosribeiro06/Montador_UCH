"""Tests for the NUMCON/NUMMAQ/POTEFE `AC` cadastre change reader, on synthetic decks.

A synthetic `entdados.dat` holding only `AC` lines (plus a `&` comment) was confirmed to read
through `Entdados.read` with no `TM` record required, so none is prepended here.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest
from idessem.dessem import Entdados

from montador_uch.cadastre_changes import (
    CadastreChangeError,
    GroupCountChange,
    UnitCountChange,
    UnitPowerChange,
    read_cadastre_changes,
)


def _entdados(tmp_path: Path, *lines: str) -> tuple[Entdados, Path]:
    """Write `lines` as a synthetic `entdados.dat` under `tmp_path` and read it back."""
    path = tmp_path / "entdados.dat"
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    # Entdados.read is annotated as returning the base RegisterFile type; pipeline.py casts
    # for the same reason.
    return cast(Entdados, Entdados.read(str(path))), path


def test_order_is_preserved_across_types_and_plants(tmp_path: Path) -> None:
    entdados, path = _entdados(
        tmp_path,
        "AC  100  NUMCON        2",
        "AC  100  NUMMAQ        1    4",
        "AC  200  NUMCON        1",
        "AC  100  POTEFE        1     50.0",
        "AC  200  NUMMAQ        1    2",
    )

    changes = read_cadastre_changes(entdados, path)

    assert changes == [
        GroupCountChange(100, 2),
        UnitCountChange(100, 1, 4),
        GroupCountChange(200, 1),
        UnitPowerChange(100, 1, 50.0),
        UnitCountChange(200, 1, 2),
    ]


def test_other_ac_mnemonics_and_comments_are_ignored(tmp_path: Path) -> None:
    entdados, path = _entdados(
        tmp_path,
        "&  AC  275  NUMCON        3",
        "AC  100  VOLMAX       500.000",
        "AC  275  NUMCON        3",
    )

    changes = read_cadastre_changes(entdados, path)

    assert changes == [GroupCountChange(275, 3)]


def test_potefe_power_matches_the_two_decimal_field(tmp_path: Path) -> None:
    entdados, path = _entdados(tmp_path, "AC  287  POTEFE        1      73.3")

    [change] = read_cadastre_changes(entdados, path)

    assert isinstance(change, UnitPowerChange)
    assert change.power_mw == pytest.approx(73.3)


class TestFieldValidation:
    """Every condition listed in the ticket: a `None` field or an out-of-range value."""

    def test_none_plant_code_raises_naming_the_mnemonic(self, tmp_path: Path) -> None:
        entdados, path = _entdados(tmp_path, "AC       NUMCON        3")

        with pytest.raises(CadastreChangeError, match=r"NUMCON.*missing field"):
            read_cadastre_changes(entdados, path)

    def test_none_group_count_raises_naming_the_mnemonic(self, tmp_path: Path) -> None:
        entdados, path = _entdados(tmp_path, "AC  275  NUMCON")

        with pytest.raises(CadastreChangeError, match=r"NUMCON.*missing field"):
            read_cadastre_changes(entdados, path)

    def test_none_unit_count_raises_naming_the_mnemonic(self, tmp_path: Path) -> None:
        entdados, path = _entdados(tmp_path, "AC  275  NUMMAQ        1")

        with pytest.raises(CadastreChangeError, match=r"NUMMAQ.*missing field"):
            read_cadastre_changes(entdados, path)

    def test_none_power_raises_naming_the_mnemonic(self, tmp_path: Path) -> None:
        entdados, path = _entdados(tmp_path, "AC  275  POTEFE        1")

        with pytest.raises(CadastreChangeError, match=r"POTEFE.*missing field"):
            read_cadastre_changes(entdados, path)

    def test_plant_code_below_one_raises(self) -> None:
        with pytest.raises(CadastreChangeError, match=r"plant code must be >= 1"):
            GroupCountChange(plant_code=0, group_count=1)

    def test_group_index_below_one_raises(self) -> None:
        with pytest.raises(CadastreChangeError, match=r"group index must be >= 1"):
            UnitCountChange(plant_code=1, group_index=0, unit_count=1)

    def test_group_count_below_zero_raises(self) -> None:
        with pytest.raises(CadastreChangeError, match=r"group count must be >= 0"):
            GroupCountChange(plant_code=1, group_count=-1)

    def test_unit_count_below_zero_raises(self) -> None:
        with pytest.raises(CadastreChangeError, match=r"unit count must be >= 0"):
            UnitCountChange(plant_code=1, group_index=1, unit_count=-1)

    def test_power_below_zero_raises(self) -> None:
        with pytest.raises(CadastreChangeError, match=r"power must be >= 0 MW"):
            UnitPowerChange(plant_code=1, group_index=1, power_mw=-1.0)


def test_raw_line_count_mismatch_raises_stating_both_counts_and_path(tmp_path: Path) -> None:
    """The idessem-drops-a-line failure mode, forced deterministically via the raw-count helper.

    A crafted `AC` line with a 4+ digit plant code cannot demonstrate this: it falls outside
    the sanity regex's own `\\d{1,3}` cap just as much as idessem's fixed 3-column field, so it
    is never counted on either side and never produces a mismatch. Patching the helper is the
    reliable way to force the discrepancy this check exists to catch.
    """
    entdados, path = _entdados(tmp_path, "AC  275  NUMCON        3")

    with (
        patch("montador_uch.cadastre_changes._count_raw_change_lines", return_value=2),
        pytest.raises(CadastreChangeError) as excinfo,
    ):
        read_cadastre_changes(entdados, path)

    message = str(excinfo.value)
    assert "Parsed 1" in message
    assert "2 line(s)" in message
    assert str(path) in message
