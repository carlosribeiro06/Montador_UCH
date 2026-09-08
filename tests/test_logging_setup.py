"""Tests for the console + rotating file logging setup."""

import logging
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from montador_uch.logging_setup import (
    CONSOLE_HANDLER_NAME,
    FILE_HANDLER_NAME,
    configure_logging,
)
from montador_uch.settings import Settings


@pytest.fixture(autouse=True)
def _isolate_root_logger() -> Iterator[None]:
    """Restore the root logger so these tests never leak handlers into the suite."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers = []
    try:
        yield
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers = saved_handlers
        root.setLevel(saved_level)


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base = replace(Settings(), log_dir=tmp_path / "logs")
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_creates_log_directory_and_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    configure_logging(settings)

    logging.getLogger("montador_uch.test").info("hello")

    log_file = settings.log_dir / settings.log_filename
    assert log_file.is_file()
    assert "hello" in log_file.read_text(encoding="utf-8")


def _own_handlers() -> list[logging.Handler]:
    """Handlers installed by `configure_logging`, ignoring pytest's own capture handlers."""
    return [
        handler
        for handler in logging.getLogger().handlers
        if handler.get_name() in {CONSOLE_HANDLER_NAME, FILE_HANDLER_NAME}
    ]


def test_installs_both_named_handlers(tmp_path: Path) -> None:
    configure_logging(_settings(tmp_path))

    assert {handler.get_name() for handler in _own_handlers()} == {
        CONSOLE_HANDLER_NAME,
        FILE_HANDLER_NAME,
    }


def test_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    configure_logging(settings)
    configure_logging(settings)
    configure_logging(settings)

    assert len(_own_handlers()) == 2


def test_applies_configured_level(tmp_path: Path) -> None:
    configure_logging(_settings(tmp_path, log_level="DEBUG"))
    assert logging.getLogger().level == logging.DEBUG


def test_second_call_updates_level_without_new_handlers(tmp_path: Path) -> None:
    configure_logging(_settings(tmp_path))
    configure_logging(_settings(tmp_path, log_level="WARNING"))

    assert logging.getLogger().level == logging.WARNING
    assert len(_own_handlers()) == 2


def test_rotation_parameters_are_honoured(tmp_path: Path) -> None:
    settings = _settings(tmp_path, log_max_bytes=200, log_backup_count=1)
    configure_logging(settings)

    logger = logging.getLogger("montador_uch.rotation")
    for index in range(50):
        logger.info("padding line %03d for rotation", index)

    log_file = settings.log_dir / settings.log_filename
    assert log_file.is_file()
    assert (settings.log_dir / f"{settings.log_filename}.1").is_file()


def test_falls_back_to_stream_handler_without_rich(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    real_import = builtins.__import__

    def _no_rich(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("rich"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _no_rich)
    configure_logging(_settings(tmp_path))

    console = next(
        handler
        for handler in logging.getLogger().handlers
        if handler.get_name() == CONSOLE_HANDLER_NAME
    )
    assert type(console) is logging.StreamHandler
