"""Tests for settings loading and validation."""

import json
from pathlib import Path

import pytest

from montador_uch.settings import Settings, SettingsError, load_settings


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_defaults_when_path_is_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = load_settings()

    assert settings.sheet_name == "UCH"
    assert settings.header_row == 1
    assert settings.uch_filename == "uch.csv"
    assert settings.dessemarq_filename == "dessem.arq"
    assert settings.entdados_filename == "entdados.dat"
    assert settings.dessemarq_uch_description == "UNIT COMMITMENT HIDRAULICO"
    assert settings.half_hour_stage_duration_h == pytest.approx(0.5)
    assert settings.log_level == "INFO"
    assert settings.log_filename == "montador_uch.log"
    assert settings.log_max_bytes == 1_000_000
    assert settings.log_backup_count == 5
    assert settings.spreadsheet_path == tmp_path / "UCH.xlsx"
    assert settings.log_dir == tmp_path / "logs"


def test_defaults_when_file_missing_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    missing = tmp_path / "absent.json"
    with caplog.at_level("WARNING"):
        settings = load_settings(missing)

    assert settings == load_settings(tmp_path / "also-absent.json")
    assert str(missing) in caplog.text


def test_partial_override_keeps_other_defaults(tmp_path: Path) -> None:
    path = _write(tmp_path / "settings.json", {"sheet_name": "OUTRA", "log_backup_count": 2})
    settings = load_settings(path)

    assert settings.sheet_name == "OUTRA"
    assert settings.log_backup_count == 2
    assert settings.header_row == Settings().header_row
    assert settings.uch_filename == "uch.csv"


def test_unknown_key_raises_naming_key_and_file(tmp_path: Path) -> None:
    path = _write(tmp_path / "settings.json", {"sheet_nme": "UCH"})
    with pytest.raises(SettingsError, match=r"sheet_nme"):
        load_settings(path)
    with pytest.raises(SettingsError, match=r"settings\.json"):
        load_settings(path)


def test_wrong_type_raises_naming_key(tmp_path: Path) -> None:
    path = _write(tmp_path / "settings.json", {"header_row": "1"})
    with pytest.raises(SettingsError, match=r"header_row.*integer"):
        load_settings(path)


def test_bool_is_not_accepted_as_integer(tmp_path: Path) -> None:
    path = _write(tmp_path / "settings.json", {"log_backup_count": True})
    with pytest.raises(SettingsError, match=r"log_backup_count.*integer"):
        load_settings(path)


def test_integer_is_accepted_for_float_key(tmp_path: Path) -> None:
    path = _write(tmp_path / "settings.json", {"half_hour_stage_duration_h": 1})
    assert load_settings(path).half_hour_stage_duration_h == pytest.approx(1.0)


def test_non_string_path_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "settings.json", {"spreadsheet_path": 3})
    with pytest.raises(SettingsError, match=r"spreadsheet_path.*string path"):
        load_settings(path)


def test_empty_path_raises(tmp_path: Path) -> None:
    path = _write(tmp_path / "settings.json", {"log_dir": ""})
    with pytest.raises(SettingsError, match=r"log_dir.*empty"):
        load_settings(path)


def test_relative_paths_resolve_against_settings_directory(tmp_path: Path) -> None:
    config_dir = tmp_path / "conf"
    config_dir.mkdir()
    path = _write(
        config_dir / "settings.json",
        {"spreadsheet_path": "base/UCH.xlsx", "log_dir": "run-logs"},
    )
    settings = load_settings(path)

    assert settings.spreadsheet_path == config_dir / "base" / "UCH.xlsx"
    assert settings.log_dir == config_dir / "run-logs"


def test_absolute_paths_are_kept(tmp_path: Path) -> None:
    absolute = tmp_path / "elsewhere" / "UCH.xlsx"
    path = _write(tmp_path / "settings.json", {"spreadsheet_path": str(absolute)})
    assert load_settings(path).spreadsheet_path == absolute


def test_invalid_json_raises(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SettingsError, match=r"not valid JSON"):
        load_settings(path)


def test_json_array_raises(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(SettingsError, match=r"must contain a JSON object"):
        load_settings(path)


def test_settings_is_frozen() -> None:
    settings = Settings()
    with pytest.raises(AttributeError):
        settings.sheet_name = "X"  # type: ignore[misc]


def test_repository_settings_file_matches_defaults() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    settings = load_settings(repository_root / "settings.json")
    defaults = Settings()

    assert settings.sheet_name == defaults.sheet_name
    assert settings.header_row == defaults.header_row
    assert settings.uch_filename == defaults.uch_filename
    assert settings.dessemarq_filename == defaults.dessemarq_filename
    assert settings.entdados_filename == defaults.entdados_filename
    assert settings.dessemarq_uch_description == defaults.dessemarq_uch_description
    assert settings.half_hour_stage_duration_h == pytest.approx(defaults.half_hour_stage_duration_h)
    assert settings.log_level == defaults.log_level
    assert settings.log_filename == defaults.log_filename
    assert settings.log_max_bytes == defaults.log_max_bytes
    assert settings.log_backup_count == defaults.log_backup_count
    assert settings.spreadsheet_path == repository_root / defaults.spreadsheet_path
    assert settings.log_dir == repository_root / defaults.log_dir
