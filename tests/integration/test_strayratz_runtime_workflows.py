from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace

import pytest

from repograph.pipeline.health import read_health_json
from repograph.pipeline.runner import RunConfig, run_full_pipeline_with_runtime_overlay
from tests.support import (
    ArtifactRegistry,
    StrayRatzRuntimeWorkspace,
    assert_no_child_processes_left,
    allocate_free_port,
    build_live_sitecustomize_env,
    configure_strayratz_managed_runtime,
    create_strayratz_runtime_workspace,
    install_live_attach_bootstrap,
    spawn_repo_process,
    stop_process_tree,
    wait_for_http_ready,
    write_strayratz_launcher,
)


class _FakeStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.runtime_observed = False

    def initialize_schema(self) -> None:
        return None

    def close(self) -> None:
        return None

    def get_stats(self) -> dict[str, int]:
        return {"files": 12, "functions": 34}

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


def _patch_runtime_overlay_runner(monkeypatch) -> None:
    def _fake_build(_config, _store):
        return [SimpleNamespace(path="run.py", source_hash="h1")], []

    def _fake_hooks(
        _config,
        store,
        _parsed,
        *,
        run_graph_built,
        run_dynamic,
        run_evidence,
        run_export,
    ):
        if run_graph_built and not run_dynamic and not run_evidence and not run_export:
            return {"failed_count": 0, "warnings_count": 0, "failed": []}
        if run_dynamic:
            store.runtime_observed = True
            return {
                "failed_count": 0,
                "warnings_count": 0,
                "failed": [],
                "dynamic_findings_count": 2,
                "dynamic_stage": {
                    "plugins": {
                        "dynamic_analyzer.runtime_overlay": {"executed": True},
                    }
                },
            }
        return {"failed_count": 0, "warnings_count": 0, "failed": []}

    monkeypatch.setattr("repograph.pipeline.runner.GraphStore", _FakeStore)
    monkeypatch.setattr("repograph.pipeline.runner._run_full_build_steps", _fake_build)
    monkeypatch.setattr(
        "repograph.pipeline.runner._run_experimental_pipeline_phases",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("repograph.pipeline.runner._fire_hooks", _fake_hooks)


@pytest.fixture
def strayratz_runtime_workspace(tmp_path: Path) -> Generator[StrayRatzRuntimeWorkspace, None, None]:
    registry = ArtifactRegistry()
    workspace_root = registry.register(tmp_path / "StrayRatz")
    try:
        try:
            yield create_strayratz_runtime_workspace(workspace_root)
        except RuntimeError as exc:
            pytest.skip(str(exc))
    finally:
        registry.cleanup()


def test_strayratz_managed_runtime_full_sync_executes_and_cleans_up(
    strayratz_runtime_workspace: StrayRatzRuntimeWorkspace,
    monkeypatch,
) -> None:
    _patch_runtime_overlay_runner(monkeypatch)
    repo = strayratz_runtime_workspace.repo_root
    repograph_dir = repo / ".repograph"
    port = allocate_free_port()
    launcher = write_strayratz_launcher(
        repo,
        relative_path=".repograph/runtime_launchers/managed/server.py",
        port=port,
        database_name="managed.db",
    )
    configure_strayratz_managed_runtime(
        repo,
        command=strayratz_runtime_workspace.python_command(launcher),
        probe_url=f"http://127.0.0.1:{port}/",
        scenario_urls=("/", "/login"),
    )

    stats = run_full_pipeline_with_runtime_overlay(
        RunConfig(
            repo_root=str(repo),
            repograph_dir=str(repograph_dir),
            include_git=False,
            full=True,
        )
    )

    health = read_health_json(str(repograph_dir))

    assert stats == {"files": 12, "functions": 34}
    assert health is not None
    assert health["dynamic_analysis"]["mode"] == "managed_python_server"
    assert health["dynamic_analysis"]["executed_mode"] == "managed_python_server"
    assert health["dynamic_analysis"]["scenario_actions"]["successful_count"] == 2
    assert health["dynamic_analysis"]["cleanup"]["stopped"] is True
    assert health["dynamic_analysis"]["cleanup"]["bootstrap_removed"] is True
    assert health["dynamic_analysis"]["cleanup"]["pid_alive_after_stop"] is False
    assert health["dynamic_analysis"]["cleanup"]["process_group_alive_after_stop"] is False
    assert health["dynamic_analysis"]["trace_file_count"] >= 1
    assert health["analysis_readiness"]["runtime_overlay_applied"] is True


def test_strayratz_live_attach_failure_falls_back_to_managed_runtime(
    strayratz_runtime_workspace: StrayRatzRuntimeWorkspace,
    monkeypatch,
) -> None:
    _patch_runtime_overlay_runner(monkeypatch)
    repo = strayratz_runtime_workspace.repo_root
    repograph_dir = repo / ".repograph"
    live_port = allocate_free_port()
    managed_port = allocate_free_port()
    live_command = strayratz_runtime_workspace.python_command(repo / "run.py")
    managed_launcher = write_strayratz_launcher(
        repo,
        relative_path=".repograph/runtime_launchers/managed/server.py",
        port=managed_port,
        database_name="managed.db",
    )
    configure_strayratz_managed_runtime(
        repo,
        command=strayratz_runtime_workspace.python_command(managed_launcher),
        probe_url=f"http://127.0.0.1:{managed_port}/",
        scenario_urls=("/",),
    )
    install_live_attach_bootstrap(repo)

    live_process = spawn_repo_process(
        live_command,
        cwd=repo,
        env=build_live_sitecustomize_env(
            repo,
            port=live_port,
            database_name="live.db",
        ),
    )
    try:
        wait_for_http_ready(f"http://127.0.0.1:{live_port}/", timeout_seconds=20.0)

        def _fail_live_attach(*_args, **_kwargs):
            raise RuntimeError("simulated live attach handshake failure")

        monkeypatch.setattr("repograph.runtime.execution.execute_live_attach", _fail_live_attach)

        stats = run_full_pipeline_with_runtime_overlay(
            RunConfig(
                repo_root=str(repo),
                repograph_dir=str(repograph_dir),
                include_git=False,
                full=True,
                runtime_attach_policy="always",
            )
        )
    finally:
        returncode = stop_process_tree(live_process)
        assert returncode is not None
        assert_no_child_processes_left(live_process)

    health = read_health_json(str(repograph_dir))

    assert stats == {"files": 12, "functions": 34}
    assert health is not None
    assert health["dynamic_analysis"]["mode"] == "attach_live_python"
    assert health["dynamic_analysis"]["executed_mode"] == "managed_python_server"
    assert health["dynamic_analysis"]["attach_outcome"] == "selected"
    assert health["dynamic_analysis"]["fallback_execution"]["from_mode"] == "attach_live_python"
    assert health["dynamic_analysis"]["fallback_execution"]["to_mode"] == "managed_python_server"
    assert health["dynamic_analysis"]["fallback_execution"]["succeeded"] is True
    assert "simulated live attach handshake failure" in health["dynamic_analysis"]["fallback_execution"]["reason"]
    attempts = health["dynamic_analysis"]["execution_attempts"]
    assert attempts[0]["phase"] == "primary"
    assert attempts[0]["mode"] == "attach_live_python"
    assert attempts[0]["outcome"] == "failed"
    assert attempts[1]["phase"] == "fallback"
    assert attempts[1]["mode"] == "managed_python_server"
    assert attempts[1]["outcome"] == "succeeded"
    assert health["dynamic_analysis"]["cleanup"]["stopped"] is True
    assert health["dynamic_analysis"]["cleanup"]["bootstrap_removed"] is True
    assert health["analysis_readiness"]["runtime_overlay_applied"] is True
