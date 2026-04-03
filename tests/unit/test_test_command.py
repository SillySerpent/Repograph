from __future__ import annotations

from typer.testing import CliRunner

import json

from repograph.surfaces.cli import app
from repograph.surfaces.cli.commands.sync import _test_profile_args, _test_profiles_catalog


def test_test_profile_args_matrix() -> None:
    assert "tests/unit/" in _test_profile_args("unit-fast")
    assert "plugin or dynamic" in _test_profile_args("plugin-dynamic")
    assert "tests/integration/" in _test_profile_args("integration")
    assert "tests/" in _test_profile_args("full")


def test_test_profile_args_unknown_raises() -> None:
    try:
        _test_profile_args("nope")
    except ValueError as exc:
        assert "Unknown profile" in str(exc)
        return
    assert False, "expected ValueError for unknown profile"


def test_test_profiles_catalog_contains_expected_profiles() -> None:
    c = _test_profiles_catalog()
    assert set(c.keys()) == {"unit-fast", "plugin-dynamic", "integration", "full"}
    assert "selector" in c["unit-fast"]
    assert "description" in c["unit-fast"]


def test_test_command_invokes_pytest(monkeypatch, tmp_path) -> None:
    called = {}

    class _R:
        returncode = 0

    def _fake_run(cmd, cwd=None):
        called["cmd"] = cmd
        called["cwd"] = cwd
        return _R()

    monkeypatch.setattr("repograph.surfaces.cli.commands.sync.subprocess.run", _fake_run)
    runner = CliRunner()
    result = runner.invoke(app, ["test", "--profile", "unit-fast", str(tmp_path), "--", "-k", "runtime"])
    assert result.exit_code == 0, result.stdout + str(result.stderr)
    assert called["cwd"] == str(tmp_path)
    assert called["cmd"][:3] == [called["cmd"][0], "-m", "pytest"]
    assert "-k" in called["cmd"]
    assert "runtime" in called["cmd"]


def test_test_command_list_profiles_json() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["test", "--list-profiles", "--json"])
    assert result.exit_code == 0, result.stdout + str(result.stderr)
    payload = json.loads(result.stdout)
    assert "profiles" in payload
    assert "unit-fast" in payload["profiles"]


def test_test_command_json_run_metadata(monkeypatch, tmp_path) -> None:
    called = {}

    class _R:
        returncode = 0

    def _fake_run(cmd, cwd=None):
        called["cmd"] = cmd
        called["cwd"] = cwd
        return _R()

    monkeypatch.setattr("repograph.surfaces.cli.commands.sync.subprocess.run", _fake_run)
    runner = CliRunner()
    result = runner.invoke(app, ["test", "--json", "--profile", "integration", str(tmp_path)])
    assert result.exit_code == 0, result.stdout + str(result.stderr)
    payload = json.loads(result.stdout)
    assert payload["profile"] == "integration"
    assert payload["repo_root"] == str(tmp_path)
    assert "pytest_cmd" in payload
    assert called["cwd"] == str(tmp_path)
