"""Fixtures shared by the test suite.

Pure helpers live in `tests/helpers.py`, which is importable because `tests` is on the pytest
`pythonpath` (see `pyproject.toml`).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from helpers import SAMPLE_DECK_ENV_VAR, sample_deck


@pytest.fixture(autouse=True)
def isolate_root_logger() -> Iterator[None]:
    """Keep `configure_logging` calls from leaking handlers between tests."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    try:
        yield
    finally:
        for handler in root.handlers:
            if handler not in saved_handlers:
                handler.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)


@pytest.fixture
def deck_dir() -> Path:
    """The reference DESSEM deck, skipping the test when it is not present."""
    deck = sample_deck()
    if deck is None:
        pytest.skip(f"reference deck not available (set {SAMPLE_DECK_ENV_VAR})")
    return deck
