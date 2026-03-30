from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from repograph.cli import app
from repograph.pipeline.health import read_health_json
from repograph.pipeline.runner import RunConfig, run_full_pipeline_with_runtime_overlay


class _FakeStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.runtime_observed = False

    def initialize_schema(self) -> None:
        return None

    def close(self) -> None:
        return None

    def get_stats(self) -> dict[str, int]:
        return {"files": 1, "functions": 1}

    def get_all_functions(self) -> list[dict]:
        observed = self.runtime_observed
        return [{
            "id": "fn:1",
            "runtime_observed": observed,
            "runtime_observed_for_hash": "h1" if observed else "",
            "source_hash": "h1",
        }]

    def query(self, cypher: str, _params=None):
        if "RETURN e.reason" in cypher:
            return []
        return [[0]]


def _repo_with_pytest(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".repograph").mkdir()
    (repo / ".repograph" / "meta").mkdir()
    (repo / "tests").mkdir()
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    return repo, repo / ".repograph"


def test_run_full_pipeline_with_runtime_overlay_autodetects_pytest_and_stays_file_clean(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, rg_dir = _repo_with_pytest(tmp_path)
    commands: list[list[str]] = []
    hook_calls: list[tuple[bool, bool, bool, bool]] = []

    def _fake_build(_config, _store):
        return [SimpleNamespace(path="main.py", source_hash="h1")], []

    def _fake_hooks(_config, store, _parsed, *, run_graph_built, run_dynamic, run_evidence, run_export):
        hook_calls.append((run_graph_built, run_dynamic, run_evidence, run_export))
        if run_dynamic:
            store.runtime_observed = True
            return {"failed_count": 0, "warnings_count": 0, "failed": [], "dynamic_findings_count": 7}
        return {"failed_count": 0, "warnings_count": 0, "failed": []}

    def _fake_traced_run(command, *, repo_root, repograph_dir, session_name="pytest"):
        commands.append(list(command))
        runtime = Path(repograph_dir) / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "pytest.jsonl").write_text('{"kind":"call"}\n', encoding="utf-8")
        assert repo_root == str(repo)
        assert session_name == "pytest"
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("repograph.pipeline.runner.GraphStore", _FakeStore)
    monkeypatch.setattr("repograph.pipeline.runner._run_full_build_steps", _fake_build)
    monkeypatch.setattr("repograph.pipeline.runner._run_experimental_pipeline_phases", lambda *args, **kwargs: None)
    monkeypatch.setattr("repograph.pipeline.runner._fire_hooks", _fake_hooks)
    monkeypatch.setattr("repograph.runtime.ephemeral.run_command_under_trace", _fake_traced_run)

    stats = run_full_pipeline_with_runtime_overlay(
        RunConfig(
            repo_root=str(repo),
            repograph_dir=str(rg_dir),
            include_git=False,
            full=True,
        )
    )

    assert stats["files"] == 1
    assert len(commands) == 1
    assert commands[0][1:] == ["-m", "pytest", "tests"]
    assert hook_calls == [
        (True, False, False, False),
        (False, True, True, True),
    ]
    assert not (repo / "conftest.py").exists()
    assert not (repo / "sitecustomize.py").exists()

    health = read_health_json(str(rg_dir))
    assert health is not None
    assert health["sync_mode"] == "full_with_runtime_overlay"
    assert health["dynamic_analysis"]["trace_file_count"] == 1
    assert health["dynamic_analysis"]["overlay_persisted_functions"] == 1
    assert health["dynamic_analysis"]["dynamic_findings_count"] == 7


def test_run_full_pipeline_with_runtime_overlay_prefers_sync_test_command_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, rg_dir = _repo_with_pytest(tmp_path)
    (rg_dir / "repograph.index.yaml").write_text(
        "sync_test_command:\n  - custom-test\n  - --fast\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    monkeypatch.setattr("repograph.pipeline.runner.GraphStore", _FakeStore)
    monkeypatch.setattr(
        "repograph.pipeline.runner._run_full_build_steps",
        lambda *_: ([SimpleNamespace(path="main.py", source_hash="h1")], []),
    )
    monkeypatch.setattr("repograph.pipeline.runner._run_experimental_pipeline_phases", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "repograph.pipeline.runner._fire_hooks",
        lambda _config, _store, _parsed, **kwargs: {"failed_count": 0, "warnings_count": 0, "failed": []},
    )

    def _fake_traced_run(command, *, repo_root, repograph_dir, session_name="pytest"):
        commands.append(list(command))
        runtime = Path(repograph_dir) / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "pytest.jsonl").write_text('{"kind":"call"}\n', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("repograph.runtime.ephemeral.run_command_under_trace", _fake_traced_run)

    run_full_pipeline_with_runtime_overlay(
        RunConfig(
            repo_root=str(repo),
            repograph_dir=str(rg_dir),
            include_git=False,
            full=True,
        )
    )

    assert commands == [["custom-test", "--fast"]]
    health = read_health_json(str(rg_dir))
    assert health is not None
    assert health["dynamic_analysis"]["resolution"] == "config_override"


def test_cli_sync_full_dispatches_dynamic_runner(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".repograph").mkdir()
    (repo / ".repograph" / "meta").mkdir()

    with patch("repograph.pipeline.runner.run_full_pipeline_with_runtime_overlay", return_value={"files": 1}) as dynamic_run:
        result = CliRunner().invoke(app, ["sync", str(repo), "--full"])

    assert result.exit_code == 0, result.stdout
    dynamic_run.assert_called_once()


def test_cli_sync_static_only_dispatches_static_runner(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".repograph").mkdir()
    (repo / ".repograph" / "meta").mkdir()

    with patch("repograph.pipeline.runner.run_full_pipeline", return_value={"files": 1}) as full_run:
        with patch("repograph.pipeline.runner.run_full_pipeline_with_runtime_overlay") as dynamic_run:
            result = CliRunner().invoke(app, ["sync", str(repo), "--static-only"])

    assert result.exit_code == 0, result.stdout
    full_run.assert_called_once()
    dynamic_run.assert_not_called()


def test_cli_sync_full_with_tests_alias_warns_and_dispatches(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".repograph").mkdir()
    (repo / ".repograph" / "meta").mkdir()

    with patch("repograph.pipeline.runner.run_full_sync_with_tests", return_value={"files": 1}) as compat_run:
        result = CliRunner().invoke(app, ["sync", str(repo), "--full-with-tests"])

    assert result.exit_code == 0, result.stdout
    assert "--full-with-tests" in result.stdout
    compat_run.assert_called_once()
