"""Checks the `dessem.arq` updater against a copy of the reference deck's index file.

The real deck is never modified: everything runs on a copy under `tmp_path`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from montador_uch.dessemarq_writer import register_uch_file
from montador_uch.settings import Settings

SETTINGS = Settings()


@pytest.fixture
def dessemarq_copy(deck_dir: Path, tmp_path: Path) -> Path:
    source = deck_dir / SETTINGS.dessemarq_filename
    if not source.is_file():
        pytest.skip(f"{source} not available")
    target = tmp_path / SETTINGS.dessemarq_filename
    shutil.copy(source, target)
    return target


def test_registers_once_then_reports_no_change(dessemarq_copy: Path) -> None:
    original_lines = dessemarq_copy.read_text(encoding="utf-8").splitlines()

    assert (
        register_uch_file(dessemarq_copy, SETTINGS.uch_filename, SETTINGS.dessemarq_uch_description)
        is True
    )
    after_first = dessemarq_copy.read_bytes()

    assert (
        register_uch_file(dessemarq_copy, SETTINGS.uch_filename, SETTINGS.dessemarq_uch_description)
        is False
    )
    assert dessemarq_copy.read_bytes() == after_first

    # Every original line must survive, ignoring trailing padding differences.
    updated = {line.rstrip() for line in dessemarq_copy.read_text(encoding="utf-8").splitlines()}
    for line in original_lines:
        assert line.rstrip() in updated


def test_uch_record_is_added_to_the_copy(dessemarq_copy: Path) -> None:
    register_uch_file(dessemarq_copy, SETTINGS.uch_filename, SETTINGS.dessemarq_uch_description)

    uch_lines = [
        line
        for line in dessemarq_copy.read_text(encoding="utf-8").splitlines()
        if line.startswith("UCH")
    ]
    assert len(uch_lines) == 1
    assert SETTINGS.uch_filename in uch_lines[0]
