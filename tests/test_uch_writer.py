"""Tests for the UCH builder and writer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from idessem.dessem import Uch
from idessem.dessem.modelos.uch import UchOpcaoPadrao, UchPadraoData

from montador_uch.model import AggregationLevel, GeneratingUnit, HydroPlant, UnitGroup
from montador_uch.uch_writer import (
    StudyEndStage,
    build_uch,
    register_count,
    study_end_stage,
    write_uch,
)

END_STAGE = StudyEndStage(day=2, hour=23, half_hour=1)


def _plant(code: int, aggregation: AggregationLevel) -> HydroPlant:
    """A two-group plant: 6 units of 152 MW (912 MW total) and 2 of 152 MW (304 MW total)."""
    return HydroPlant(
        code=code,
        name=f"PLANT{code}",
        aggregation=aggregation,
        groups=(
            UnitGroup(
                index=1,
                max_power_mw=912.0,
                units=tuple(
                    GeneratingUnit(index=position + 1, min_power_mw=101.0, max_power_mw=152.0)
                    for position in range(6)
                ),
            ),
            UnitGroup(
                index=2,
                max_power_mw=304.0,
                units=tuple(
                    GeneratingUnit(index=position + 1, min_power_mw=101.0, max_power_mw=152.0)
                    for position in range(2)
                ),
            ),
        ),
    )


def _frame(uch: Uch, accessor: str) -> pd.DataFrame:
    result: Any = getattr(uch, accessor)(df=True)
    assert isinstance(result, pd.DataFrame), f"{accessor} returned {type(result).__name__}"
    return result


class TestBuildUch:
    def test_leading_registers_are_the_defaults_and_the_horizon(self) -> None:
        uch = build_uch([], END_STAGE)

        assert isinstance(uch.opcao_padrao, UchOpcaoPadrao)
        assert uch.opcao_padrao.considera_uch == 1

        horizon = uch.uch_padrao_data
        assert isinstance(horizon, UchPadraoData)
        assert (horizon.dia_final, horizon.hora_final, horizon.meia_hora_final) == (2, 23, 1)
        assert register_count(uch) == 2

    def test_group_level_plant(self) -> None:
        uch = build_uch([_plant(6, AggregationLevel.GROUP)], END_STAGE)

        options = _frame(uch, "opcao_padrao_usina")
        assert len(options) == 1
        assert options.iloc[0]["codigo_usina"] == 6
        assert options.iloc[0]["considera_uch_usina"] == 1
        assert options.iloc[0]["tipo_agregacao"] == AggregationLevel.GROUP

        groups = _frame(uch, "gmin_gmax_conjunto")
        assert len(groups) == 2
        assert list(groups["codigo_conjunto"]) == [1, 2]
        assert list(groups["geracao_minima_conjunto"]) == pytest.approx([101.0, 101.0])
        assert list(groups["geracao_maxima_conjunto"]) == pytest.approx([912.0, 304.0])

        assert _frame(uch, "gmin_gmax_unidade").empty
        assert _frame(uch, "gmin_gmax_usina").empty
        assert register_count(uch) == 2 + 1 + 2

    def test_unit_level_plant(self) -> None:
        uch = build_uch([_plant(6, AggregationLevel.UNIT)], END_STAGE)

        options = _frame(uch, "opcao_padrao_usina")
        assert options.iloc[0]["tipo_agregacao"] == AggregationLevel.UNIT

        units = _frame(uch, "gmin_gmax_unidade")
        assert len(units) == 8
        assert list(units["codigo_conjunto"]) == [1, 1, 1, 1, 1, 1, 2, 2]
        assert list(units["codigo_unidade"]) == [1, 2, 3, 4, 5, 6, 1, 2]
        assert set(units["codigo_usina"]) == {6}
        assert list(units["geracao_minima_unidade"]) == pytest.approx([101.0] * 8)
        assert list(units["geracao_maxima_unidade"]) == pytest.approx([152.0] * 8)
        assert register_count(uch) == 2 + 1 + 8

    def test_plant_level_plant_sums_group_totals(self) -> None:
        uch = build_uch([_plant(6, AggregationLevel.PLANT)], END_STAGE)

        options = _frame(uch, "opcao_padrao_usina")
        assert options.iloc[0]["tipo_agregacao"] == AggregationLevel.PLANT

        plants = _frame(uch, "gmin_gmax_usina")
        assert len(plants) == 1
        assert plants.iloc[0]["codigo_usina"] == 6
        assert plants.iloc[0]["geracao_minima_usina"] == pytest.approx(101.0)
        # The legacy branch added each group total once per unit and produced 6080 MW.
        assert plants.iloc[0]["geracao_maxima_usina"] == pytest.approx(1216.0)
        assert register_count(uch) == 2 + 1 + 1

    def test_every_register_is_a_distinct_instance(self) -> None:
        """The legacy script re-appended one shared instance per plant."""
        uch = build_uch(
            [_plant(6, AggregationLevel.GROUP), _plant(7, AggregationLevel.UNIT)], END_STAGE
        )

        identities = [id(register) for register in uch.data]
        assert len(set(identities)) == len(identities)

    def test_mixed_aggregation_levels_keep_plant_order(self) -> None:
        plants = [
            _plant(1, AggregationLevel.UNIT),
            _plant(2, AggregationLevel.GROUP),
            _plant(3, AggregationLevel.PLANT),
        ]
        uch = build_uch(plants, END_STAGE)

        assert list(_frame(uch, "opcao_padrao_usina")["codigo_usina"]) == [1, 2, 3]
        assert len(_frame(uch, "gmin_gmax_unidade")) == 8
        assert len(_frame(uch, "gmin_gmax_conjunto")) == 2
        assert len(_frame(uch, "gmin_gmax_usina")) == 1


class TestWriteUch:
    def test_first_lines_and_round_trip(self, tmp_path: Path) -> None:
        plants = [_plant(1, AggregationLevel.GROUP), _plant(2, AggregationLevel.UNIT)]
        uch = build_uch(plants, END_STAGE)

        path = tmp_path / "uch.csv"
        write_uch(uch, path)

        lines = path.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "UCH-OPCAO-PADRAO;1"
        assert lines[1] == "UCH-PADRAO-DATA;2;23;1"
        assert lines[2].startswith("UCH-OPCAO-PADRAO-USINA;1;1;2")

        reloaded = Uch.read(str(path))
        for accessor in ("opcao_padrao_usina", "gmin_gmax_conjunto", "gmin_gmax_unidade"):
            pd.testing.assert_frame_equal(_frame(uch, accessor), _frame(reloaded, accessor))
        assert register_count(reloaded) == register_count(uch)

    def test_overwrites_an_existing_file(self, tmp_path: Path) -> None:
        path = tmp_path / "uch.csv"
        path.write_text("STALE CONTENT\n" * 50, encoding="utf-8")

        write_uch(build_uch([_plant(9, AggregationLevel.GROUP)], END_STAGE), path)

        content = path.read_text(encoding="utf-8")
        assert "STALE" not in content
        assert content.splitlines()[0] == "UCH-OPCAO-PADRAO;1"

    def test_logs_the_path_and_count(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "uch.csv"
        uch = build_uch([_plant(1, AggregationLevel.GROUP)], END_STAGE)

        with caplog.at_level("INFO", logger="montador_uch.uch_writer"):
            write_uch(uch, path)

        assert str(path) in caplog.text
        assert "5 register(s)" in caplog.text


class _StubEntdados:
    """Minimal stand-in exposing only the `tm(df=True)` call `study_end_stage` uses."""

    def __init__(self, frame: pd.DataFrame | None) -> None:
        self._frame = frame

    def tm(self, df: bool = False) -> pd.DataFrame | None:
        assert df is True
        return self._frame


def _tm_frame(rows: list[tuple[float, int, int, int]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["duracao", "dia_inicial", "hora_inicial", "meia_hora_inicial"]
    )


class TestStudyEndStage:
    def test_last_half_hour_row_wins(self) -> None:
        frame = _tm_frame(
            [
                (0.5, 2, 0, 0),
                (0.5, 2, 23, 1),
                (1.0, 3, 0, 0),
                (8.0, 4, 8, 0),
            ]
        )
        stage = study_end_stage(_StubEntdados(frame), 0.5)  # type: ignore[arg-type]

        assert stage == StudyEndStage(day=2, hour=23, half_hour=1)

    def test_returns_python_ints(self) -> None:
        frame = _tm_frame([(0.5, 2, 23, 1)])
        stage = study_end_stage(_StubEntdados(frame), 0.5)  # type: ignore[arg-type]

        for value in (stage.day, stage.hour, stage.half_hour):
            assert type(value) is int

    def test_duration_is_matched_with_a_tolerance(self) -> None:
        frame = _tm_frame([(0.5 + 1e-12, 7, 4, 1)])
        stage = study_end_stage(_StubEntdados(frame), 0.5)  # type: ignore[arg-type]

        assert stage.day == 7

    def test_no_matching_duration_raises(self) -> None:
        frame = _tm_frame([(1.0, 2, 0, 0), (8.0, 2, 8, 0)])
        with pytest.raises(ValueError, match=r"no TM record with a duration of 0.5 h"):
            study_end_stage(_StubEntdados(frame), 0.5)  # type: ignore[arg-type]

    def test_no_tm_records_raises(self) -> None:
        with pytest.raises(ValueError, match=r"no TM records"):
            study_end_stage(_StubEntdados(None), 0.5)  # type: ignore[arg-type]

    def test_missing_columns_are_listed(self) -> None:
        frame = pd.DataFrame([(0.5, 2)], columns=["duracao", "dia_inicial"])
        with pytest.raises(ValueError, match=r"missing column\(s\).*hora_inicial"):
            study_end_stage(_StubEntdados(frame), 0.5)  # type: ignore[arg-type]
