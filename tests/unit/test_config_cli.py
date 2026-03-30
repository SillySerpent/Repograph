from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from typer.testing import CliRunner

from repograph.surfaces.cli import app


def _settings_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_init_creates_settings_scaffold(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    result = CliRunner().invoke(app, ["init", str(repo)])

    assert result.exit_code == 0, result.stdout
    settings_path = repo / ".repograph" / "settings.json"
    assert settings_path.exists()
    payload = _settings_payload(settings_path)
    assert payload["runtime_overrides"] == {}
    assert payload["effective_values"]["include_git"] is True


def test_init_gitignore_includes_settings_json(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    result = CliRunner().invoke(app, ["init", str(repo)])

    assert result.exit_code == 0, result.stdout
    gitignore = (repo / ".repograph" / ".gitignore").read_text(encoding="utf-8")
    assert "settings.json" in gitignore


def test_sync_first_run_creates_settings_scaffold(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    with patch("repograph.pipeline.runner.run_full_pipeline_with_runtime_overlay", return_value={"files": 1}):
        result = CliRunner().invoke(app, ["sync", str(repo)])

    assert result.exit_code == 0, result.stdout
    settings_path = repo / ".repograph" / "settings.json"
    assert settings_path.exists()
    payload = _settings_payload(settings_path)
    assert payload["runtime_overrides"] == {}


def test_sync_recreates_missing_settings_scaffold_for_existing_repograph_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    rg_dir = repo / ".repograph"
    (rg_dir / "meta").mkdir(parents=True)

    with patch("repograph.pipeline.runner.run_full_pipeline_with_runtime_overlay", return_value={"files": 1}):
        result = CliRunner().invoke(app, ["sync", str(repo), "--full"])

    assert result.exit_code == 0, result.stdout
    settings_path = repo / ".repograph" / "settings.json"
    assert settings_path.exists()
    payload = _settings_payload(settings_path)
    assert payload["runtime_overrides"] == {}


def test_config_describe_single_key(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    CliRunner().invoke(app, ["init", str(repo)])

    result = CliRunner().invoke(app, ["config", "describe", "include_git", "--path", str(repo)])

    assert result.exit_code == 0, result.stdout
    assert "include_git" in result.stdout
    assert "Takes Effect" in result.stdout


def test_config_unset_clears_runtime_override(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = CliRunner()
    runner.invoke(app, ["init", str(repo)])
    runner.invoke(app, ["config", "set", "include_git", "false", "--path", str(repo)])

    result = runner.invoke(app, ["config", "unset", "include_git", "--path", str(repo)])

    assert result.exit_code == 0, result.stdout
    settings_path = repo / ".repograph" / "settings.json"
    payload = _settings_payload(settings_path)
    assert payload["runtime_overrides"] == {}


def test_config_set_invalid_value_fails_cleanly(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = CliRunner()
    runner.invoke(app, ["init", str(repo)])

    result = runner.invoke(
        app,
        ["config", "set", "entry_point_limit", "nonsense", "--path", str(repo)],
    )

    assert result.exit_code == 1
    assert "entry_point_limit" in result.stdout
    settings_path = repo / ".repograph" / "settings.json"
    payload = _settings_payload(settings_path)
    assert payload["runtime_overrides"] == {}


def test_config_reset_keeps_empty_scaffold(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = CliRunner()
    runner.invoke(app, ["init", str(repo)])
    runner.invoke(app, ["config", "set", "include_git", "false", "--path", str(repo)])

    result = runner.invoke(app, ["config", "reset", str(repo), "--yes"])

    assert result.exit_code == 0, result.stdout
    settings_path = repo / ".repograph" / "settings.json"
    assert settings_path.exists()
    payload = _settings_payload(settings_path)
    assert payload["runtime_overrides"] == {}


def test_config_describe_json_preserves_type_shapes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = CliRunner()
    runner.invoke(app, ["init", str(repo)])

    result = runner.invoke(
        app,
        ["config", "describe", "sync_test_command", "--path", str(repo), "--json"],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["type"] == "list[str] | null"
    assert payload["value_shape"] == "null or JSON array of command arguments"
