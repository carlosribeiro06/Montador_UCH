"""Tests for the `dessem.arq` UCH record updater, on a synthetic index file."""

from __future__ import annotations

from pathlib import Path

import pytest
from idessem.dessem import DessemArq

from montador_uch.dessemarq_writer import register_uch_file
from montador_uch.settings import Settings

# Column geometry of RegistroUch and its siblings: a 9-character identifier, a 38-character
# description from 0-based column 10, and an 80-character value from 0-based column 49.
IDENTIFIER_WIDTH = 9
DESCRIPTION_START = 10
DESCRIPTION_WIDTH = 38
VALUE_START = 49
VALUE_WIDTH = 80
LINE_WIDTH = VALUE_START + VALUE_WIDTH

DESCRIPTION = Settings().dessemarq_uch_description
UCH_FILENAME = Settings().uch_filename


def _record_line(identifier: str, description: str, value: str) -> str:
    assert len(identifier) <= IDENTIFIER_WIDTH
    assert len(description) <= DESCRIPTION_WIDTH
    assert len(value) <= VALUE_WIDTH

    line = [" "] * LINE_WIDTH
    line[: len(identifier)] = identifier
    line[DESCRIPTION_START : DESCRIPTION_START + len(description)] = description
    line[VALUE_START : VALUE_START + len(value)] = value
    return "".join(line)


@pytest.fixture
def dessemarq(tmp_path: Path) -> Path:
    """A minimal `dessem.arq` in the real fixed-width layout."""
    lines = [
        "&Mnem        Descricao                           Arquivo",
        "&XXXXXXXX XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX XXXXXXXXXXXXXXXXXXXXXXXX",
        _record_line("CASO", "NOME DO CASO                   (F)", "DAT"),
        _record_line("TITULO", "TITULO DO ESTUDO               (F)", "TE  PMO - TESTE"),
        _record_line("DADGER", "DADOS GERAIS DO PROBLEMA       (F)", "entdados.dat"),
    ]
    path = tmp_path / "dessem.arq"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_missing_file_raises_naming_the_path(tmp_path: Path) -> None:
    absent = tmp_path / "nowhere" / "dessem.arq"
    with pytest.raises(FileNotFoundError, match=r"dessem\.arq"):
        register_uch_file(absent, UCH_FILENAME, DESCRIPTION)


def test_first_call_adds_the_record(dessemarq: Path) -> None:
    assert register_uch_file(dessemarq, UCH_FILENAME, DESCRIPTION) is True

    reloaded = DessemArq.read(str(dessemarq))
    record = reloaded.uch
    assert record is not None
    assert record.valor == UCH_FILENAME
    assert record.descricao == DESCRIPTION


def test_uch_is_the_first_data_record(dessemarq: Path) -> None:
    register_uch_file(dessemarq, UCH_FILENAME, DESCRIPTION)

    data_lines = [
        line
        for line in dessemarq.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("&")
    ]
    assert data_lines[0].startswith("UCH")
    assert UCH_FILENAME in data_lines[0]
    assert DESCRIPTION in data_lines[0]


def test_original_records_are_preserved(dessemarq: Path) -> None:
    before = DessemArq.read(str(dessemarq))
    register_uch_file(dessemarq, UCH_FILENAME, DESCRIPTION)
    after = DessemArq.read(str(dessemarq))

    assert after.caso is not None
    assert after.caso.valor == before.caso.valor  # type: ignore[union-attr]
    assert after.dadger is not None
    assert after.dadger.valor == before.dadger.valor  # type: ignore[union-attr]


def test_second_call_is_a_no_op(dessemarq: Path) -> None:
    assert register_uch_file(dessemarq, UCH_FILENAME, DESCRIPTION) is True
    after_first = dessemarq.read_bytes()

    assert register_uch_file(dessemarq, UCH_FILENAME, DESCRIPTION) is False
    assert dessemarq.read_bytes() == after_first


def test_existing_record_is_not_overwritten(dessemarq: Path) -> None:
    register_uch_file(dessemarq, "outro.csv", "OUTRA DESCRICAO")

    assert register_uch_file(dessemarq, UCH_FILENAME, DESCRIPTION) is False

    record = DessemArq.read(str(dessemarq)).uch
    assert record is not None
    assert record.valor == "outro.csv"


def test_logs_the_existing_value(dessemarq: Path, caplog: pytest.LogCaptureFixture) -> None:
    register_uch_file(dessemarq, "outro.csv", "OUTRA DESCRICAO")

    with caplog.at_level("INFO", logger="montador_uch.dessemarq_writer"):
        register_uch_file(dessemarq, UCH_FILENAME, DESCRIPTION)

    assert "outro.csv" in caplog.text
    assert "leaving it unchanged" in caplog.text
