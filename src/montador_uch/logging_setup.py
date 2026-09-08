"""Audit-grade logging: a readable console handler plus a rotating file handler.

Called once from the application entry point. Library modules must only call
`logging.getLogger(__name__)` and never configure handlers at import time.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from typing import Final

from montador_uch.settings import Settings

CONSOLE_HANDLER_NAME: Final = "montador-uch-console"
FILE_HANDLER_NAME: Final = "montador-uch-file"

_FILE_FORMAT: Final = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_PLAIN_CONSOLE_FORMAT: Final = "%(asctime)s %(levelname)-8s %(message)s"


def _console_handler() -> logging.Handler:
    handler: logging.Handler
    try:
        from rich.logging import RichHandler
    except ImportError:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_PLAIN_CONSOLE_FORMAT))
    else:
        handler = RichHandler(rich_tracebacks=True, show_path=False, log_time_format="%H:%M:%S")
        handler.setFormatter(logging.Formatter("%(message)s"))
    handler.set_name(CONSOLE_HANDLER_NAME)
    return handler


def _file_handler(settings: Settings) -> logging.Handler:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    handler: logging.Handler = RotatingFileHandler(
        settings.log_dir / settings.log_filename,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    handler.set_name(FILE_HANDLER_NAME)
    return handler


def configure_logging(settings: Settings) -> None:
    """Attach the console and rotating file handlers to the root logger.

    Idempotent: handlers are identified by name, so repeated calls only update the level.
    """
    root = logging.getLogger()
    root.setLevel(settings.log_level)

    installed = {handler.get_name() for handler in root.handlers}
    if CONSOLE_HANDLER_NAME not in installed:
        root.addHandler(_console_handler())
    if FILE_HANDLER_NAME not in installed:
        root.addHandler(_file_handler(settings))
