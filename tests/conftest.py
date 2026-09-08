"""Fixtures shared by the test suite.

Pure helpers live in `tests/helpers.py`, which is importable because `tests` is on the pytest
`pythonpath` (see `pyproject.toml`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from helpers import SAMPLE_DECK_ENV_VAR, sample_deck


@pytest.fixture
def deck_dir() -> Path:
    """The reference DESSEM deck, skipping the test when it is not present."""
    deck = sample_deck()
    if deck is None:
        pytest.skip(f"reference deck not available (set {SAMPLE_DECK_ENV_VAR})")
    return deck
