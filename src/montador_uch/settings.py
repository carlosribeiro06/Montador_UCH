"""Application settings, loaded and validated from a JSON file.

Every path, filename and tunable used by the tool lives here so the code is portable across
machines without editing source. Keep this module free of heavy imports (pandas, idessem) so
tests can load it cheaply.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, Final, get_type_hints

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS_FILENAME: Final = "settings.json"

LOG_LEVELS: Final = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class SettingsError(Exception):
    """Raised when the settings file is unreadable or holds an invalid key or value."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved configuration for one run.

    `spreadsheet_path` and `log_dir` are absolute after `load_settings`; relative values in the
    JSON file are taken relative to that file's directory.
    """

    spreadsheet_path: Path = Path("UCH.xlsx")
    sheet_name: str = "UCH"
    header_row: int = 1
    uch_filename: str = "uch.csv"
    dessemarq_filename: str = "dessem.arq"
    entdados_filename: str = "entdados.dat"
    dessemarq_uch_description: str = "UNIT COMMITMENT HIDRAULICO"
    half_hour_stage_duration_h: float = 0.5
    log_level: str = "INFO"
    log_dir: Path = Path("logs")
    log_filename: str = "montador_uch.log"
    log_max_bytes: int = 1_000_000
    log_backup_count: int = 5


def _field_types() -> dict[str, type]:
    hints = get_type_hints(Settings)
    return {field.name: hints[field.name] for field in fields(Settings)}


FIELD_TYPES: Final = _field_types()


def _coerce(key: str, value: Any, source: Path) -> Any:
    expected = FIELD_TYPES[key]
    where = f"key '{key}' in settings file {source}"

    if expected is Path:
        if not isinstance(value, str):
            raise SettingsError(f"{where} must be a string path, got {type(value).__name__}")
        if not value:
            raise SettingsError(f"{where} must not be empty")
        return Path(value)

    if expected is str:
        if not isinstance(value, str):
            raise SettingsError(f"{where} must be a string, got {type(value).__name__}")
        return value

    if expected is int:
        # bool is a subclass of int; reject it so `true` is never read as 1.
        if isinstance(value, bool) or not isinstance(value, int):
            raise SettingsError(f"{where} must be an integer, got {type(value).__name__}")
        return value

    if expected is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise SettingsError(f"{where} must be a number, got {type(value).__name__}")
        return float(value)

    raise SettingsError(f"{where} has an unsupported declared type {expected!r}")


def _check_domain(key: str, value: Any, source: Path) -> None:
    """Reject values that are well-typed but outside the range the code can honour."""
    where = f"key '{key}' in settings file {source}"

    if key == "log_level" and value not in LOG_LEVELS:
        raise SettingsError(f"{where} must be one of {', '.join(LOG_LEVELS)}, got {value!r}")
    if key == "header_row" and value < 0:
        raise SettingsError(f"{where} must not be negative, got {value}")
    if key == "half_hour_stage_duration_h" and value <= 0.0:
        raise SettingsError(f"{where} must be positive, got {value}")
    if key == "log_max_bytes" and value < 1:
        raise SettingsError(f"{where} must be at least 1, got {value}")
    # RotatingFileHandler only rotates while backupCount > 0, so 0 would silently turn the audit
    # log into a single file that grows without bound.
    if key == "log_backup_count" and value < 1:
        raise SettingsError(f"{where} must be at least 1, got {value}")


def _absolute(path: Path, base: Path) -> Path:
    return path if path.is_absolute() else base / path


def _resolve_paths(settings: Settings, base: Path) -> Settings:
    return replace(
        settings,
        spreadsheet_path=_absolute(settings.spreadsheet_path, base),
        log_dir=_absolute(settings.log_dir, base),
    )


def load_settings(path: Path | None = None) -> Settings:
    """Load settings from `path`, falling back to the built-in defaults.

    Every key is optional. An unknown key, a value of the wrong type, a value outside the range
    the code can honour, or unreadable/invalid JSON raises `SettingsError` naming the key and
    the file.
    """
    candidate = Path(DEFAULT_SETTINGS_FILENAME) if path is None else path

    if not candidate.is_file():
        logger.warning(
            "Settings file %s not found; using built-in defaults resolved against %s",
            candidate,
            Path.cwd(),
        )
        return _resolve_paths(Settings(), Path.cwd())

    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SettingsError(f"Cannot read settings file {candidate}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SettingsError(f"Settings file {candidate} is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise SettingsError(
            f"Settings file {candidate} must contain a JSON object, got {type(payload).__name__}"
        )

    unknown = sorted(set(payload) - set(FIELD_TYPES))
    if unknown:
        raise SettingsError(
            f"Unknown key(s) {', '.join(repr(key) for key in unknown)} in settings file {candidate}"
        )

    values = {key: _coerce(key, value, candidate) for key, value in payload.items()}
    for key, value in values.items():
        _check_domain(key, value, candidate)

    logger.info("Loaded settings from %s (%d key(s) overridden)", candidate, len(values))
    return _resolve_paths(Settings(**values), candidate.resolve().parent)
