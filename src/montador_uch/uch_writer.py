"""Builder and writer for the DESSEM `uch.csv` file.

Register layout (DESSEM User Manual v22.4.0, section III.32; CSV with `;` delimiter):

1. `UCH-OPCAO-PADRAO;1`
2. `UCH-PADRAO-DATA;<day>;<hour>;<half hour>` -- the end of the UCH horizon, taken from the last
   half-hour `TM` record of `entdados.dat`.
3. For each plant, in spreadsheet order, `UCH-OPCAO-PADRAO-USINA;<code>;1;<level>` followed by the
   Gmin/Gmax registers for its aggregation level:
   - `UNIT`  -> one `UCH-GERACAO-MINIMA-MAXIMA-UNIDADE` per generating unit;
   - `GROUP` -> one `UCH-GERACAO-MINIMA-MAXIMA-CONJUNTO` per unit group;
   - `PLANT` -> one `UCH-GERACAO-MINIMA-MAXIMA-USINA`.

Every line is a distinct register instance: the legacy script created one instance per plant and
appended the same object once per unit or group, so the written file repeated the last values.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
from cfinterface.components.defaultregister import DefaultRegister
from cfinterface.components.register import Register
from cfinterface.data.registerdata import RegisterData
from idessem.dessem import Entdados, Uch
from idessem.dessem.modelos.uch import (
    UchGminGmaxConjunto,
    UchGminGmaxUnidade,
    UchGminGmaxUsina,
    UchOpcaoPadrao,
    UchOpcaoPadraoUsina,
    UchPadraoData,
)

from montador_uch.model import AggregationLevel, HydroPlant

logger = logging.getLogger(__name__)

CONSIDER_UCH: Final = 1

STAGE_DAY_COLUMN: Final = "dia_inicial"
STAGE_HOUR_COLUMN: Final = "hora_inicial"
STAGE_HALF_HOUR_COLUMN: Final = "meia_hora_inicial"
STAGE_DURATION_COLUMN: Final = "duracao"


@dataclass(frozen=True, slots=True)
class StudyEndStage:
    """The last half-hour stage of the study, which closes the UCH horizon."""

    day: int
    hour: int
    half_hour: int


def study_end_stage(entdados: Entdados, stage_duration_h: float) -> StudyEndStage:
    """The last `TM` stage of `entdados` whose duration is `stage_duration_h`.

    Durations are compared with a tolerance because they are read as floats from a fixed-width
    field.
    """
    frame = entdados.tm(df=True)
    if not isinstance(frame, pd.DataFrame):
        raise ValueError("entdados.dat has no TM records; the UCH horizon cannot be determined")

    required = (
        STAGE_DURATION_COLUMN,
        STAGE_DAY_COLUMN,
        STAGE_HOUR_COLUMN,
        STAGE_HALF_HOUR_COLUMN,
    )
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"TM records are missing column(s): {', '.join(missing)}")

    matching = frame[np.isclose(frame[STAGE_DURATION_COLUMN], stage_duration_h)]
    if matching.empty:
        raise ValueError(
            f"entdados.dat has no TM record with a duration of {stage_duration_h} h; "
            f"durations present: {sorted(set(frame[STAGE_DURATION_COLUMN]))}"
        )

    last = matching.iloc[-1]
    stage = StudyEndStage(
        day=int(last[STAGE_DAY_COLUMN]),
        hour=int(last[STAGE_HOUR_COLUMN]),
        half_hour=int(last[STAGE_HALF_HOUR_COLUMN]),
    )
    logger.info(
        "UCH horizon ends at day %d, hour %d, half hour %d (last of %d stage(s) of %s h)",
        stage.day,
        stage.hour,
        stage.half_hour,
        len(matching),
        stage_duration_h,
    )
    return stage


def _empty_uch() -> Uch:
    """An empty `Uch` with its own register container.

    `cfinterface.RegisterFile.__init__` declares `data` as a mutable default argument, so every
    bare `Uch()` in a process shares one container and a second build would append to the first
    one's registers. Passing an explicit container makes each build independent.
    """
    return Uch(RegisterData(DefaultRegister(data="")))


def _limit_registers(plant: HydroPlant) -> Iterator[Register]:
    """The Gmin/Gmax registers of `plant`, one new instance per line."""
    if plant.aggregation is AggregationLevel.UNIT:
        for group in plant.groups:
            for unit in group.units:
                by_unit = UchGminGmaxUnidade()
                by_unit.codigo_usina = plant.code
                by_unit.codigo_conjunto = group.index
                by_unit.codigo_unidade = unit.index
                by_unit.geracao_minima_unidade = unit.min_power_mw
                by_unit.geracao_maxima_unidade = unit.max_power_mw
                yield by_unit
    elif plant.aggregation is AggregationLevel.GROUP:
        for group in plant.groups:
            by_group = UchGminGmaxConjunto()
            by_group.codigo_usina = plant.code
            by_group.codigo_conjunto = group.index
            by_group.geracao_minima_conjunto = group.min_power_mw
            by_group.geracao_maxima_conjunto = group.max_power_mw
            yield by_group
    else:
        by_plant = UchGminGmaxUsina()
        by_plant.codigo_usina = plant.code
        by_plant.geracao_minima_usina = plant.min_power_mw
        by_plant.geracao_maxima_usina = plant.max_power_mw
        yield by_plant


def build_uch(plants: Sequence[HydroPlant], end_stage: StudyEndStage) -> Uch:
    """Build the `Uch` file object for `plants` over a horizon ending at `end_stage`.

    Pure in-memory construction; `write_uch` is the only function that touches disk.
    """
    uch = _empty_uch()

    default = UchOpcaoPadrao()
    default.considera_uch = CONSIDER_UCH
    uch.data.append(default)

    horizon = UchPadraoData()
    horizon.dia_final = end_stage.day
    horizon.hora_final = end_stage.hour
    horizon.meia_hora_final = end_stage.half_hour
    uch.data.append(horizon)

    for plant in plants:
        option = UchOpcaoPadraoUsina()
        option.codigo_usina = plant.code
        option.considera_uch_usina = CONSIDER_UCH
        option.tipo_agregacao = int(plant.aggregation)
        uch.data.append(option)

        for register in _limit_registers(plant):
            uch.data.append(register)

    logger.info("Built %d UCH register(s) for %d plant(s)", register_count(uch), len(plants))
    return uch


def register_count(uch: Uch) -> int:
    """The number of registers held by `uch`, excluding the container's root sentinel."""
    return sum(1 for register in uch.data if not isinstance(register, DefaultRegister))


def write_uch(uch: Uch, path: Path) -> None:
    """Write `uch` to `path`, overwriting any existing file."""
    existed = path.is_file()
    uch.write(str(path))
    logger.info(
        "%s %s with %d register(s)",
        "Overwrote" if existed else "Wrote",
        path,
        register_count(uch),
    )
