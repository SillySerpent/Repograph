from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.support.strayratz_runtime import (
    build_live_sitecustomize_env,
    create_strayratz_runtime_workspace,
)


def test_create_strayratz_runtime_workspace_bootstraps_isolated_venv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []

    def _fake_run(command, *, cwd, env, capture_output, text, timeout, check):
        del env, capture_output, text, timeout, check
        commands.append(list(command))
        if command[1:3] == ["-m", "venv"]:
            venv_dir = Path(command[3])
            bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
            bin_dir.mkdir(parents=True)
            python_name = "python.exe" if os.name == "nt" else "python"
            pip_name = "pip.exe" if os.name == "nt" else "pip"
            (bin_dir / python_name).write_text("", encoding="utf-8")
            (bin_dir / pip_name).write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr("tests.support.strayratz_runtime.subprocess.run", _fake_run)

    workspace = create_strayratz_runtime_workspace(tmp_path / "StrayRatz")

    assert workspace.repo_root.name == "StrayRatz"
    assert workspace.venv_dir == workspace.repo_root / ".venv"
    assert workspace.python_executable.exists()
    assert workspace.pip_executable.exists()
    assert workspace.python_command("run.py") == [
        str(workspace.python_executable),
        "run.py",
    ]
    assert commands[0][1:3] == ["-m", "venv"]
    assert commands[1][1:5] == ["-m", "pip", "install", "-r"]


def test_create_strayratz_runtime_workspace_reports_bootstrap_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["python", "-m", "venv"], timeout=123)

    monkeypatch.setattr("tests.support.strayratz_runtime.subprocess.run", _raise_timeout)

    with pytest.raises(RuntimeError, match="bootstrap timed out"):
        create_strayratz_runtime_workspace(tmp_path / "StrayRatz")


def test_build_live_sitecustomize_env_adds_fixture_defaults(tmp_path: Path) -> None:
    env = build_live_sitecustomize_env(
        tmp_path,
        port=5123,
        database_name="live.db",
    )

    assert env["FLASK_RUN_PORT"] == "5123"
    assert env["SECRET_KEY"] == "repograph-strayratz-test-secret"
    assert env["ADMIN_EMAIL"] == "admin@example.com"
    assert env["DATABASE_URL"].endswith("/instance/live.db")
    assert "PYTHONPATH" in env
    assert (tmp_path / "instance").is_dir()
