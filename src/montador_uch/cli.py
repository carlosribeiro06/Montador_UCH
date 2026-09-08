"""Command-line entry point: `montador-uch <deck_dir>`."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from montador_uch import __version__
from montador_uch.cadastre_changes import CadastreChangeError
from montador_uch.logging_setup import configure_logging
from montador_uch.pipeline import run
from montador_uch.settings import LOG_LEVELS, SettingsError, load_settings
from montador_uch.spreadsheet import SpreadsheetError

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="montador-uch",
        description=(
            "Build the DESSEM hydraulic unit commitment file uch.csv from the base workbook, "
            "write it into the deck directory (overwriting any existing file) and register it "
            "in the deck's dessem.arq."
        ),
    )
    parser.add_argument("deck_dir", type=Path, help="DESSEM deck directory to write into")
    parser.add_argument(
        "--spreadsheet",
        type=Path,
        default=None,
        metavar="PATH",
        help="base workbook, overriding spreadsheet_path from the settings file",
    )
    parser.add_argument(
        "--settings",
        type=Path,
        default=None,
        metavar="PATH",
        help="settings file (default: settings.json in the current directory)",
    )
    parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        default=None,
        metavar="LEVEL",
        help=f"console and file log level, overriding the settings file ({', '.join(LOG_LEVELS)})",
    )
    parser.add_argument("--version", action="version", version=f"montador-uch {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = load_settings(args.settings)
        if args.log_level is not None:
            settings = replace(settings, log_level=args.log_level)
        if args.spreadsheet is not None:
            settings = replace(settings, spreadsheet_path=args.spreadsheet.resolve())

        configure_logging(settings)
        summary = run(args.deck_dir, settings)
    except (SettingsError, SpreadsheetError, CadastreChangeError, FileNotFoundError, ValueError):
        # Before configure_logging succeeds this reaches stderr via logging.lastResort.
        logger.exception("montador-uch failed")
        return 1

    segments = [
        f"uch.csv: {summary.uch_path}",
        f"{summary.plants} plants, {summary.groups} groups, {summary.units} units",
        f"horizon end {summary.end_stage.day}/{summary.end_stage.hour}/"
        f"{summary.end_stage.half_hour}",
        f"{summary.changes_applied} AC changes applied",
    ]
    if summary.omitted_plants:
        codes = ", ".join(str(code) for code in summary.omitted_plants)
        segments.append(f"{len(summary.omitted_plants)} plants omitted ({codes})")
    segments.append(
        f"dessem.arq {'updated' if summary.dessemarq_updated else 'already registered'}"
    )
    segments.append(f"{summary.elapsed_s:.2f} s")
    print(" | ".join(segments))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
