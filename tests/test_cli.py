"""End-to-end tests for the `montador-uch` CLI on a throwaway deck."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest
from idessem.dessem import DessemArq, Uch
from idessem.dessem.modelos.entdados import ACNUMMAQ

from helpers import plant_row, write_uch_workbook
from montador_uch import __version__
from montador_uch.cli import build_parser, main
from montador_uch.settings import Settings

PLANTS = [
    plant_row(6, "FURNAS", "Conjunto", [(6, 101.0, 912.0), (2, 101.0, 304.0)]),
    plant_row(7, "SEM UCH", "Sem UCH", [(1, 5.0, 10.0)]),
    plant_row(8, "UNIT LEVEL", "Unidade", [(2, 12.0, 46.0)]),
    plant_row(9, "PLANT LEVEL", "Usina", [(3, 20.0, 150.0)]),
]

EXPECTED_GROUP_REGISTERS = 2
EXPECTED_UNIT_REGISTERS = 2
EXPECTED_PLANT_REGISTERS = 1
EXPECTED_PLANTS = 3


@pytest.fixture
def deck(deck_dir: Path, tmp_path: Path) -> Path:
    """A deck copy holding only the two files the tool reads."""
    target = tmp_path / "deck"
    target.mkdir()
    settings = Settings()
    for name in (settings.entdados_filename, settings.dessemarq_filename):
        source = deck_dir / name
        if not source.is_file():
            pytest.skip(f"{source} not available")
        shutil.copy(source, target / name)
    return target


@pytest.fixture
def deck_with_omission(deck: Path) -> Path:
    """`deck` with an extra `AC NUMMAQ 0` change that zeroes workbook plant 8's only group.

    The line is generated through idessem's own register writer, then appended after a fresh
    newline since the reference deck's `entdados.dat` has no trailing one.
    """
    entdados_path = deck / Settings().entdados_filename
    change = ACNUMMAQ()
    change.codigo_usina = 8
    change.codigo_conjunto = 1
    change.numero_maquinas = 0
    buffer = io.StringIO()
    change.write(buffer)
    with entdados_path.open("a", encoding="latin-1") as handle:
        handle.write("\n" + buffer.getvalue())
    return deck


@pytest.fixture
def settings_file(tmp_path: Path) -> Path:
    """A settings file whose workbook and log directory both live under `tmp_path`."""
    workbook = write_uch_workbook(tmp_path / "UCH.xlsx", PLANTS)
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"spreadsheet_path": str(workbook), "log_dir": str(tmp_path / "logs")}),
        encoding="utf-8",
    )
    return path


def _argv(deck: Path, settings_file: Path) -> list[str]:
    return [str(deck), "--settings", str(settings_file)]


class TestParser:
    def test_requires_a_deck_directory(self) -> None:
        with pytest.raises(SystemExit) as failure:
            build_parser().parse_args([])
        assert failure.value.code == 2

    def test_version_exits_zero(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit) as failure:
            build_parser().parse_args(["--version"])
        assert failure.value.code == 0
        assert __version__ in capsys.readouterr().out

    def test_main_without_arguments_exits_two(self) -> None:
        with pytest.raises(SystemExit) as failure:
            main([])
        assert failure.value.code == 2

    def test_rejects_an_unknown_log_level(self) -> None:
        with pytest.raises(SystemExit) as failure:
            build_parser().parse_args(["deck", "--log-level", "LOUD"])
        assert failure.value.code == 2


class TestRun:
    def test_writes_uch_and_registers_it(
        self, deck: Path, settings_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(_argv(deck, settings_file)) == 0

        uch_path = deck / Settings().uch_filename
        assert uch_path.is_file()

        lines = uch_path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "UCH-OPCAO-PADRAO;1"
        assert lines[1].startswith("UCH-PADRAO-DATA;")

        registers = [line.split(";", 1)[0] for line in lines if line]
        assert registers.count("UCH-OPCAO-PADRAO-USINA") == EXPECTED_PLANTS
        assert registers.count("UCH-GERACAO-MINIMA-MAXIMA-CONJUNTO") == EXPECTED_GROUP_REGISTERS
        assert registers.count("UCH-GERACAO-MINIMA-MAXIMA-UNIDADE") == EXPECTED_UNIT_REGISTERS
        assert registers.count("UCH-GERACAO-MINIMA-MAXIMA-USINA") == EXPECTED_PLANT_REGISTERS

        out = capsys.readouterr().out
        assert "3 plants" in out
        assert "AC changes applied" in out

    def test_output_is_parseable_by_idessem(self, deck: Path, settings_file: Path) -> None:
        main(_argv(deck, settings_file))

        uch = Uch.read(str(deck / Settings().uch_filename))
        assert uch.opcao_padrao is not None
        assert uch.uch_padrao_data is not None

    def test_dessemarq_gains_exactly_one_uch_record(self, deck: Path, settings_file: Path) -> None:
        main(_argv(deck, settings_file))

        dessemarq_path = deck / Settings().dessemarq_filename
        uch_lines = [
            line
            for line in dessemarq_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("UCH")
        ]
        assert len(uch_lines) == 1
        assert Settings().uch_filename in uch_lines[0]
        assert DessemArq.read(str(dessemarq_path)).uch is not None

    def test_second_run_overwrites_and_stays_idempotent(
        self, deck: Path, settings_file: Path
    ) -> None:
        assert main(_argv(deck, settings_file)) == 0
        uch_path = deck / Settings().uch_filename
        first_content = uch_path.read_text(encoding="utf-8")
        dessemarq_path = deck / Settings().dessemarq_filename
        first_index = dessemarq_path.read_bytes()

        assert main(_argv(deck, settings_file)) == 0

        assert uch_path.read_text(encoding="utf-8") == first_content
        assert dessemarq_path.read_bytes() == first_index
        uch_lines = [
            line
            for line in dessemarq_path.read_text(encoding="utf-8").splitlines()
            if line.startswith("UCH")
        ]
        assert len(uch_lines) == 1

    def test_spreadsheet_flag_overrides_the_settings_file(
        self, deck: Path, settings_file: Path, tmp_path: Path
    ) -> None:
        other = write_uch_workbook(
            tmp_path / "OTHER.xlsx", [plant_row(1, "ONLY", "Conjunto", [(1, 5.0, 10.0)])]
        )

        assert main([*_argv(deck, settings_file), "--spreadsheet", str(other)]) == 0

        lines = (deck / Settings().uch_filename).read_text(encoding="utf-8").splitlines()
        options = [line for line in lines if line.startswith("UCH-OPCAO-PADRAO-USINA")]
        assert len(options) == 1
        assert options[0].startswith("UCH-OPCAO-PADRAO-USINA;1;")

    def test_log_file_is_written(self, deck: Path, settings_file: Path, tmp_path: Path) -> None:
        main([*_argv(deck, settings_file), "--log-level", "DEBUG"])

        log_file = tmp_path / "logs" / Settings().log_filename
        assert log_file.is_file()
        assert "Run finished" in log_file.read_text(encoding="utf-8")

    def test_stdout_reports_a_plant_omitted_by_an_ac_change(
        self, deck_with_omission: Path, settings_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(_argv(deck_with_omission, settings_file)) == 0

        out = capsys.readouterr().out
        assert "AC changes applied" in out
        assert "plants omitted (8)" in out

    def test_audit_line_omits_the_codes_when_no_plant_was_omitted(
        self, deck: Path, settings_file: Path, tmp_path: Path
    ) -> None:
        """The audit line joins the codes as text; a tuple would leak its repr as `omitted ()`."""
        assert main(_argv(deck, settings_file)) == 0

        log = (tmp_path / "logs" / Settings().log_filename).read_text(encoding="utf-8")
        assert "0 plant(s) omitted;" in log
        assert "omitted ()" not in log

    def test_audit_line_reports_a_single_omitted_plant_as_a_bare_code(
        self, deck_with_omission: Path, settings_file: Path, tmp_path: Path
    ) -> None:
        assert main(_argv(deck_with_omission, settings_file)) == 0

        log = (tmp_path / "logs" / Settings().log_filename).read_text(encoding="utf-8")
        assert "1 plant(s) omitted (8);" in log
        assert "(8,)" not in log


class TestFailures:
    def test_missing_deck_directory_exits_one(self, settings_file: Path, tmp_path: Path) -> None:
        assert main([str(tmp_path / "absent"), "--settings", str(settings_file)]) == 1

    def test_deck_without_entdados_exits_one(self, settings_file: Path, tmp_path: Path) -> None:
        empty = tmp_path / "empty-deck"
        empty.mkdir()
        assert main([str(empty), "--settings", str(settings_file)]) == 1

    def test_missing_spreadsheet_exits_one(self, deck: Path, settings_file: Path) -> None:
        assert main([*_argv(deck, settings_file), "--spreadsheet", "/nowhere/UCH.xlsx"]) == 1

    def test_invalid_settings_file_exits_one(self, deck: Path, tmp_path: Path) -> None:
        broken = tmp_path / "broken.json"
        broken.write_text('{"unknown_key": 1}', encoding="utf-8")
        assert main([str(deck), "--settings", str(broken)]) == 1

    def test_malformed_spreadsheet_exits_one(
        self, deck: Path, settings_file: Path, tmp_path: Path
    ) -> None:
        bad = write_uch_workbook(
            tmp_path / "BAD.xlsx", [plant_row(1, "X", "Reservatorio", [(1, 5.0, 10.0)])]
        )
        assert main([*_argv(deck, settings_file), "--spreadsheet", str(bad)]) == 1
