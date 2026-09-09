"""End-to-end pipeline: workbook and deck directory -> `uch.csv` and its `dessem.arq` record."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from idessem.dessem import Entdados

from montador_uch.cadastre_changes import read_cadastre_changes
from montador_uch.cadastre_overlay import apply_cadastre_changes
from montador_uch.dessemarq_writer import register_uch_file
from montador_uch.settings import Settings
from montador_uch.spreadsheet import read_records
from montador_uch.uch_writer import StudyEndStage, build_uch, study_end_stage, write_uch

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunSummary:
    """What one run produced, for the audit log and the CLI's closing line."""

    plants: int
    groups: int
    units: int
    uch_path: Path
    dessemarq_updated: bool
    end_stage: StudyEndStage
    elapsed_s: float
    changes_applied: int
    changes_ignored: int
    omitted_plants: tuple[int, ...]


def _require_file(path: Path, what: str) -> Path:
    if not path.is_file():
        raise FileNotFoundError(f"{what} not found: {path}")
    return path


def run(deck_dir: Path, settings: Settings) -> RunSummary:
    """Build `uch.csv` in `deck_dir` and register it in the deck's `dessem.arq`.

    `uch.csv` is written before `dessem.arq` is touched, so a failed write never leaves the deck
    index pointing at a file that does not exist.
    """
    started = time.perf_counter()
    logger.info("Run started for deck %s", deck_dir)

    if not deck_dir.is_dir():
        raise FileNotFoundError(f"Deck directory not found: {deck_dir}")
    entdados_path = _require_file(deck_dir / settings.entdados_filename, "Deck stage file")
    dessemarq_path = _require_file(deck_dir / settings.dessemarq_filename, "Deck index file")
    spreadsheet_path = _require_file(settings.spreadsheet_path, "Base workbook")

    records = read_records(spreadsheet_path, settings.sheet_name, settings.header_row)

    logger.info("Reading study stages and cadastre changes from %s", entdados_path)
    # RegisterFile.read is annotated as returning the base class, which hides `tm` and `data`.
    entdados = cast(Entdados, Entdados.read(str(entdados_path)))
    changes = read_cadastre_changes(entdados, entdados_path)
    end_stage = study_end_stage(entdados, settings.half_hour_stage_duration_h)

    overlay = apply_cadastre_changes(records, changes)

    uch_path = deck_dir / settings.uch_filename
    write_uch(build_uch(overlay.plants, end_stage), uch_path)

    dessemarq_updated = register_uch_file(
        dessemarq_path, settings.uch_filename, settings.dessemarq_uch_description
    )

    summary = RunSummary(
        plants=len(overlay.plants),
        groups=sum(len(plant.groups) for plant in overlay.plants),
        units=sum(len(plant.units) for plant in overlay.plants),
        uch_path=uch_path,
        dessemarq_updated=dessemarq_updated,
        end_stage=end_stage,
        elapsed_s=time.perf_counter() - started,
        changes_applied=overlay.changes_applied,
        changes_ignored=overlay.changes_ignored,
        omitted_plants=tuple(omitted.code for omitted in overlay.omitted),
    )
    omitted_codes = ", ".join(str(code) for code in summary.omitted_plants)
    logger.info(
        "Run finished in %.3f s: %d plant(s), %d group(s), %d unit(s); %d cadastre change(s) "
        "applied, %d ignored, %d plant(s) omitted%s; %s; %s",
        summary.elapsed_s,
        summary.plants,
        summary.groups,
        summary.units,
        summary.changes_applied,
        summary.changes_ignored,
        len(summary.omitted_plants),
        f" ({omitted_codes})" if omitted_codes else "",
        summary.uch_path,
        "dessem.arq updated" if summary.dessemarq_updated else "dessem.arq already registered",
    )
    return summary
