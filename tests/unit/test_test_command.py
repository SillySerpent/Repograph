from __future__ import annotations

from typer.testing import CliRunner

from repograph.cli import app, _test_profile_args


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


def test_test_command_invokes_pytest(monkeypatch, tmp_path) -> None:
    called = {}

    class _R:
        returncode = 0

    def _fake_run(cmd, cwd=None):
        called["cmd"] = cmd
        called["cwd"] = cwd
        return _R()

    monkeypatch.setattr("repograph.cli.subprocess.run", _fake_run)
    runner = CliRunner()
    result = runner.invoke(app, ["test", "--profile", "unit-fast", str(tmp_path), "--", "-k", "runtime"])
    assert result.exit_code == 0, result.stdout + str(result.stderr)
    assert called["cwd"] == str(tmp_path)
    assert called["cmd"][:3] == [called["cmd"][0], "-m", "pytest"]
    assert "-k" in called["cmd"]
    assert "runtime" in called["cmd"]
