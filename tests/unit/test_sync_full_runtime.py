from __future__ import annotations

import os
import re
import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from repograph.surfaces.cli import app
from repograph.surfaces.cli.commands.sync import _repo_venv_activate_hint
from repograph.pipeline.health import read_health_json
from repograph.pipeline.runner import RunConfig, run_full_pipeline_with_runtime_overlay
from repograph.runtime.orchestration import LiveTarget, RuntimePlan
from repograph.runtime.session import (
    DynamicInputInventory,
    RuntimeAttachApproval,
    RuntimeAttachDecision,
    RuntimeExecutionAttempt,
    RuntimeExecutionResult,
    RuntimeFallbackExecution,
    RuntimeSessionTarget,
)

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


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


def _compact_terminal_output(text: str) -> str:
    """Normalize ANSI and terminal wrapping for stable CLI assertions."""
    return "".join(_ANSI_RE.sub("", text).split())


def _patch_basic_runtime_runner(monkeypatch, *, dynamic_findings_count: int = 0) -> None:
    def _fake_build(_config, _store):
        return [SimpleNamespace(path="main.py", source_hash="h1")], []

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
        if run_dynamic:
            store.runtime_observed = True
            return {
                "failed_count": 0,
                "warnings_count": 0,
                "failed": [],
                "dynamic_findings_count": dynamic_findings_count,
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
            return {
                "failed_count": 0,
                "warnings_count": 0,
                "failed": [],
                "dynamic_findings_count": 7,
                "dynamic_stage": {
                    "plugins": {
                        "dynamic_analyzer.runtime_overlay": {"executed": True},
                    }
                },
            }
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
    monkeypatch.setattr("repograph.runtime.execution.run_command_under_trace", _fake_traced_run)

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
    assert health["dynamic_analysis"]["mode"] == "traced_tests"
    assert health["dynamic_analysis"]["trace_file_count"] == 1
    assert health["dynamic_analysis"]["overlay_persisted_functions"] == 1
    assert health["dynamic_analysis"]["dynamic_findings_count"] == 7
    assert health["analysis_readiness"]["runtime_overlay_applied"] is True
    assert health["analysis_readiness"]["coverage_json_present"] is False
    assert health["analysis_readiness"]["coverage_overlay_applied"] is False


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

    monkeypatch.setattr("repograph.runtime.execution.run_command_under_trace", _fake_traced_run)

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
    assert health["dynamic_analysis"]["mode"] == "traced_tests"
    assert health["dynamic_analysis"]["resolution"] == "config_override"


def test_run_full_pipeline_with_runtime_overlay_records_detected_live_targets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, rg_dir = _repo_with_pytest(tmp_path)

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
    monkeypatch.setattr(
        "repograph.pipeline.runner.resolve_runtime_plan",
        lambda *_args, **_kwargs: RuntimePlan(
            mode="none",
            resolution="live_target_detected",
            command=(),
            skip_reason="live_python_target_not_trace_capable",
            detected_targets=(
                LiveTarget(
                    pid=321,
                    runtime="python",
                    kind="uvicorn",
                    command=f"uvicorn main:app --app-dir {repo}",
                    association="command_path",
                    port=8000,
                ),
            ),
            attach_decision=RuntimeAttachDecision(
                outcome="unavailable",
                reason="live_python_target_not_trace_capable",
                attach_mode="attach_live_python",
                candidate_count=1,
                target=LiveTarget(
                    pid=321,
                    runtime="python",
                    kind="uvicorn",
                    command=f"uvicorn main:app --app-dir {repo}",
                    association="command_path",
                    port=8000,
                ),
            ),
        ),
    )

    run_full_pipeline_with_runtime_overlay(
        RunConfig(
            repo_root=str(repo),
            repograph_dir=str(rg_dir),
            include_git=False,
            full=True,
        )
    )

    health = read_health_json(str(rg_dir))
    assert health is not None
    assert health["dynamic_analysis"]["mode"] == "none"
    assert health["dynamic_analysis"]["resolution"] == "live_target_detected"
    assert health["dynamic_analysis"]["skipped_reason"] == "live_python_target_not_trace_capable"
    assert health["dynamic_analysis"]["detected_live_target_count"] == 1
    assert health["dynamic_analysis"]["detected_live_targets"][0]["kind"] == "uvicorn"
    assert health["dynamic_analysis"]["detected_live_targets"][0]["port"] == 8000
    assert health["dynamic_analysis"]["attach_outcome"] == "unavailable"
    assert health["dynamic_analysis"]["attach_mode"] == "attach_live_python"
    assert health["dynamic_analysis"]["attach_target"]["kind"] == "uvicorn"


def test_run_full_pipeline_with_runtime_overlay_records_ambiguous_live_targets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo, rg_dir = _repo_with_pytest(tmp_path)
    _patch_basic_runtime_runner(monkeypatch)

    monkeypatch.setattr(
        "repograph.pipeline.runner.resolve_runtime_plan",
        lambda *_args, **_kwargs: RuntimePlan(
            mode="traced_tests",
            resolution="pyproject_tests_dir",
            command=("python", "-m", "pytest", "tests"),
            fallback_reason="multiple_live_targets_detected",
            detected_targets=(
                LiveTarget(
                    pid=321,
                    runtime="python",
                    kind="uvicorn",
                    command=f"uvicorn main:app --app-dir {repo}",
                    association="command_path",
                    port=8000,
                ),
                LiveTarget(
                    pid=654,
                    runtime="python",
                    kind="python_server_script",
                    command=f"python {repo}/server.py --port 5001",
                    association="command_path",
                    port=5001,
                ),
            ),
            attach_decision=RuntimeAttachDecision(
                outcome="ambiguous",
                reason="multiple_live_targets_detected",
                attach_mode="none",
                candidate_count=2,
            ),
        ),
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.run_command_under_trace",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0),
    )

    run_full_pipeline_with_runtime_overlay(
        RunConfig(
            repo_root=str(repo),
            repograph_dir=str(rg_dir),
            include_git=False,
            full=True,
        )
    )

    health = read_health_json(str(rg_dir))
    assert health is not None
    assert health["dynamic_analysis"]["mode"] == "traced_tests"
    assert health["dynamic_analysis"]["fallback_reason"] == "multiple_live_targets_detected"
    assert health["dynamic_analysis"]["attach_outcome"] == "ambiguous"
    assert health["dynamic_analysis"]["attach_candidate_count"] == 2
    assert health["dynamic_analysis"]["attach_target"] == {}
    assert health["dynamic_analysis"]["detected_live_target_count"] == 2


def test_run_full_pipeline_with_runtime_overlay_managed_runtime_server_flow(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from repograph.pipeline.runner_parts.shared import console

    repo, rg_dir = _repo_with_pytest(tmp_path)
    hook_calls: list[tuple[bool, bool, bool, bool]] = []

    def _fake_build(_config, _store):
        return [SimpleNamespace(path="main.py", source_hash="h1")], []

    def _fake_hooks(_config, store, _parsed, *, run_graph_built, run_dynamic, run_evidence, run_export):
        hook_calls.append((run_graph_built, run_dynamic, run_evidence, run_export))
        if run_dynamic:
            store.runtime_observed = True
            return {
                "failed_count": 0,
                "warnings_count": 0,
                "failed": [],
                "dynamic_findings_count": 3,
                "dynamic_stage": {
                    "plugins": {
                        "dynamic_analyzer.runtime_overlay": {"executed": True},
                    }
                },
            }
        return {"failed_count": 0, "warnings_count": 0, "failed": []}

    fake_process = SimpleNamespace(pid=987, poll=lambda: None, returncode=0)
    traced_process = SimpleNamespace(
        pid=987,
        process=fake_process,
        command=("python", "app.py"),
        bootstrap_dir=str(rg_dir / "tmp-bootstrap"),
        stdout_path=str(rg_dir / "server.stdout.log"),
        stderr_path=str(rg_dir / "server.stderr.log"),
    )

    monkeypatch.setattr("repograph.pipeline.runner.GraphStore", _FakeStore)
    monkeypatch.setattr("repograph.pipeline.runner._run_full_build_steps", _fake_build)
    monkeypatch.setattr("repograph.pipeline.runner._run_experimental_pipeline_phases", lambda *args, **kwargs: None)
    monkeypatch.setattr("repograph.pipeline.runner._fire_hooks", _fake_hooks)
    monkeypatch.setattr(
        "repograph.pipeline.runner.resolve_runtime_plan",
        lambda *_args, **_kwargs: RuntimePlan(
            mode="managed_python_server",
            resolution="managed_runtime_config",
            command=("python", "app.py"),
            probe_url="http://127.0.0.1:8000/health",
            scenario_urls=("/", "/health"),
            ready_timeout=9,
        ),
    )
    monkeypatch.setattr("repograph.runtime.execution.spawn_command_under_trace", lambda *args, **kwargs: traced_process)
    monkeypatch.setattr("repograph.runtime.execution.wait_for_http_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "repograph.runtime.execution.drive_http_scenarios",
        lambda **kwargs: {
            "planned_count": 2,
            "executed_count": 2,
            "successful_count": 2,
            "failed_count": 0,
            "requests": [
                {"url": "http://127.0.0.1:8000/", "ok": True, "status_code": 200},
                {"url": "http://127.0.0.1:8000/health", "ok": True, "status_code": 200},
            ],
        },
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.stop_command_under_trace",
        lambda _traced: {
            "pid": 987,
            "stopped": True,
            "forced_kill": False,
            "returncode": 0,
            "bootstrap_removed": True,
        },
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.dynamic_input_state",
        lambda *_args, **_kwargs: DynamicInputInventory(
            trace_file_count=1,
            trace_record_count=12,
            coverage_json_present=False,
            inputs_present=True,
        ),
    )

    with console.capture() as capture:
        run_full_pipeline_with_runtime_overlay(
            RunConfig(
                repo_root=str(repo),
                repograph_dir=str(rg_dir),
                include_git=False,
                full=True,
            )
        )
    output = capture.get()

    health = read_health_json(str(rg_dir))
    assert health is not None
    assert health["dynamic_analysis"]["mode"] == "managed_python_server"
    assert health["dynamic_analysis"]["resolution"] == "managed_runtime_config"
    assert health["dynamic_analysis"]["chosen_target"]["probe_url"] == "http://127.0.0.1:8000/health"
    assert health["dynamic_analysis"]["scenario_actions"]["successful_count"] == 2
    assert health["dynamic_analysis"]["cleanup"]["stopped"] is True
    assert health["dynamic_analysis"]["trace_file_count"] == 1
    assert health["analysis_readiness"]["runtime_overlay_applied"] is True
    assert hook_calls == [
        (True, False, False, False),
        (False, True, True, True),
    ]
    assert "Dynamic Analysis Plan" in output
    assert "Runtime mode: managed traced Python server" in output
    assert "Probe URL: http://127.0.0.1:8000/health" in output
    assert "Scenario URLs: /, /health" in output
    assert "Dynamic Analysis Result" in output
    assert "Scenarios: 2 ok / 0 failed" in output
    assert "Cleanup: clean" in output


def test_run_full_pipeline_with_runtime_overlay_prints_traced_test_plan_and_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from repograph.pipeline.runner_parts.shared import console

    repo, rg_dir = _repo_with_pytest(tmp_path)
    _patch_basic_runtime_runner(monkeypatch, dynamic_findings_count=2)

    def _fake_traced_run(command, *, repo_root, repograph_dir, session_name="pytest"):
        runtime = Path(repograph_dir) / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "pytest.jsonl").write_text('{"kind":"call"}\n', encoding="utf-8")
        assert repo_root == str(repo)
        assert session_name == "pytest"
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("repograph.runtime.execution.run_command_under_trace", _fake_traced_run)

    with console.capture() as capture:
        run_full_pipeline_with_runtime_overlay(
            RunConfig(
                repo_root=str(repo),
                repograph_dir=str(rg_dir),
                include_git=False,
                full=True,
            )
        )
    output = capture.get()

    assert "Dynamic Analysis Plan" in output
    assert "Runtime mode: traced tests" in output
    assert "Selection: pyproject.toml pytest config with tests/ directory" in output
    assert "Trace collection: capture Python call events during test execution" in output
    assert "Command:" in output
    assert "Dynamic Analysis Result" in output
    assert "Executed: yes" in output
    assert "Trace files: 1" in output
    assert "Trace records: 1" in output
    assert "Cleanup: clean" in output


def test_run_full_pipeline_with_runtime_overlay_prints_live_attach_plan_and_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from repograph.pipeline.runner_parts.shared import console

    repo, rg_dir = _repo_with_pytest(tmp_path)
    _patch_basic_runtime_runner(monkeypatch, dynamic_findings_count=1)
    plan = RuntimePlan(
        mode="attach_live_python",
        resolution="live_target_attach",
        command=(),
        probe_url="http://127.0.0.1:5001/",
        scenario_urls=("http://127.0.0.1:5001/",),
        detected_targets=(
            LiveTarget(
                pid=321,
                runtime="python",
                kind="uvicorn",
                command=f"uvicorn main:app --app-dir {repo}",
                association="command_path",
                port=5001,
            ),
        ),
        attach_decision=RuntimeAttachDecision(
            outcome="selected",
            reason="live_python_trace_session_detected",
            attach_mode="attach_live_python",
            strategy_id="python.live_trace_session",
            candidate_count=1,
            policy="always",
            approval=RuntimeAttachApproval(
                outcome="approved",
                reason="live_attach_enabled_by_policy",
            ),
            target=LiveTarget(
                pid=321,
                runtime="python",
                kind="uvicorn",
                command=f"uvicorn main:app --app-dir {repo}",
                association="command_path",
                port=5001,
            ),
        ),
    )
    monkeypatch.setattr(
        "repograph.pipeline.runner.resolve_runtime_plan",
        lambda *_args, **_kwargs: plan,
    )
    monkeypatch.setattr(
        "repograph.pipeline.runner_parts.full_runtime.execute_runtime_plan",
        lambda *_args, **_kwargs: RuntimeExecutionResult(
            executed=True,
            chosen_target=RuntimeSessionTarget.from_runtime_plan(plan),
            input_state=DynamicInputInventory(
                trace_file_count=1,
                trace_record_count=2,
                coverage_json_present=False,
                inputs_present=True,
            ),
        ),
    )

    with console.capture() as capture:
        run_full_pipeline_with_runtime_overlay(
            RunConfig(
                repo_root=str(repo),
                repograph_dir=str(rg_dir),
                include_git=False,
                full=True,
            )
        )
    output = capture.get()

    health = read_health_json(str(rg_dir))
    assert health is not None
    assert health["dynamic_analysis"]["mode"] == "attach_live_python"
    assert health["dynamic_analysis"]["resolution"] == "live_target_attach"
    assert health["dynamic_analysis"]["attach_outcome"] == "selected"
    assert health["dynamic_analysis"]["chosen_target"]["source"] == "live_target"
    assert "Dynamic Analysis Plan" in output
    assert "Runtime mode: live Python attach" in output
    assert "Selection:" in output
    assert "attachable live runtime target" in output
    assert "Attach decision: selected" in output
    assert "Attach policy: always attach" in output
    assert "Attach approval: approved" in output
    assert "Attach target: python uvicorn pid=321 port=5001" in output
    assert "Dynamic Analysis Result" in output
    assert "Executed: yes" in output
    assert "Trace files: 1" in output


def test_run_full_pipeline_with_runtime_overlay_records_attach_failure_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from repograph.pipeline.runner_parts.shared import console

    repo, rg_dir = _repo_with_pytest(tmp_path)
    _patch_basic_runtime_runner(monkeypatch, dynamic_findings_count=1)
    plan = RuntimePlan(
        mode="attach_live_python",
        resolution="live_target_attach",
        command=(),
        probe_url="http://127.0.0.1:5001/",
        scenario_urls=("http://127.0.0.1:5001/",),
        detected_targets=(
            LiveTarget(
                pid=321,
                runtime="python",
                kind="uvicorn",
                command=f"uvicorn main:app --app-dir {repo}",
                association="command_path",
                port=5001,
            ),
        ),
        attach_decision=RuntimeAttachDecision(
            outcome="selected",
            reason="live_python_trace_session_detected",
            attach_mode="attach_live_python",
            strategy_id="python.live_trace_session",
            candidate_count=1,
            policy="always",
            approval=RuntimeAttachApproval(
                outcome="approved",
                reason="live_attach_enabled_by_policy",
            ),
            target=LiveTarget(
                pid=321,
                runtime="python",
                kind="uvicorn",
                command=f"uvicorn main:app --app-dir {repo}",
                association="command_path",
                port=5001,
            ),
        ),
    )
    monkeypatch.setattr(
        "repograph.pipeline.runner.resolve_runtime_plan",
        lambda *_args, **_kwargs: plan,
    )
    monkeypatch.setattr(
        "repograph.pipeline.runner_parts.full_runtime.execute_runtime_plan",
        lambda *_args, **_kwargs: RuntimeExecutionResult(
            executed=True,
            executed_mode="managed_python_server",
            chosen_target=RuntimeSessionTarget(
                source="managed_runtime",
                mode="managed_python_server",
                runtime="python",
                kind="managed_runtime_server",
                command=("python", "app.py"),
                probe_url="http://127.0.0.1:8000/health",
                scenario_urls=("/",),
                ready_timeout=10,
            ),
            input_state=DynamicInputInventory(
                trace_file_count=1,
                trace_record_count=4,
                coverage_json_present=False,
                inputs_present=True,
            ),
            attempts=(
                RuntimeExecutionAttempt(
                    phase="primary",
                    mode="attach_live_python",
                    resolution="live_target_attach",
                    outcome="failed",
                    detail="RuntimeError: attach handshake failed",
                ),
                RuntimeExecutionAttempt(
                    phase="fallback",
                    mode="managed_python_server",
                    resolution="managed_runtime_config",
                    outcome="succeeded",
                    trace_file_count=1,
                    trace_record_count=4,
                ),
            ),
            fallback=RuntimeFallbackExecution(
                from_mode="attach_live_python",
                from_resolution="live_target_attach",
                to_mode="managed_python_server",
                to_resolution="managed_runtime_config",
                reason="RuntimeError: attach handshake failed",
                succeeded=True,
            ),
        ),
    )

    with console.capture() as capture:
        run_full_pipeline_with_runtime_overlay(
            RunConfig(
                repo_root=str(repo),
                repograph_dir=str(rg_dir),
                include_git=False,
                full=True,
            )
        )
    output = capture.get()

    health = read_health_json(str(rg_dir))
    assert health is not None
    assert health["dynamic_analysis"]["mode"] == "attach_live_python"
    assert health["dynamic_analysis"]["executed_mode"] == "managed_python_server"
    assert health["dynamic_analysis"]["fallback_execution"]["to_mode"] == "managed_python_server"
    assert health["dynamic_analysis"]["fallback_execution"]["succeeded"] is True
    assert health["dynamic_analysis"]["execution_attempts"][0]["outcome"] == "failed"
    assert health["dynamic_analysis"]["execution_attempts"][1]["outcome"] == "succeeded"
    assert "Runtime mode: managed traced Python server" in output
    assert "Selected mode: live Python attach" in output
    assert "Fallback execution:" in output
    assert "live Python attach -> managed traced Python server" in output
    assert "Attempts:" in output
    assert "primary:live Python attach=failed" in output


def test_run_full_pipeline_with_runtime_overlay_prints_live_target_skip_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from repograph.pipeline.runner_parts.shared import console

    repo, rg_dir = _repo_with_pytest(tmp_path)
    _patch_basic_runtime_runner(monkeypatch)
    monkeypatch.setattr(
        "repograph.pipeline.runner.resolve_runtime_plan",
        lambda *_args, **_kwargs: RuntimePlan(
            mode="none",
            resolution="live_target_detected",
            command=(),
            skip_reason="live_python_target_not_trace_capable",
            fallback_reason="live_python_target_not_trace_capable",
            detected_targets=(
                LiveTarget(
                    pid=321,
                    runtime="python",
                    kind="uvicorn",
                    command=f"uvicorn main:app --app-dir {repo}",
                    association="command_path",
                    port=8000,
                ),
            ),
            attach_decision=RuntimeAttachDecision(
                outcome="unavailable",
                reason="live_python_target_not_trace_capable",
                attach_mode="attach_live_python",
                candidate_count=1,
                target=LiveTarget(
                    pid=321,
                    runtime="python",
                    kind="uvicorn",
                    command=f"uvicorn main:app --app-dir {repo}",
                    association="command_path",
                    port=8000,
                ),
            ),
        ),
    )

    with console.capture() as capture:
        run_full_pipeline_with_runtime_overlay(
            RunConfig(
                repo_root=str(repo),
                repograph_dir=str(rg_dir),
                include_git=False,
                full=True,
            )
        )
    output = capture.get()

    assert "Dynamic Analysis Plan" in output
    assert "Runtime mode: no runtime execution" in output
    assert "Selection: live runtime targets were detected" in output
    assert "Detected live targets: 1" in output
    assert "python uvicorn pid=321 port=8000" in output
    assert "Attach decision: unavailable" in output
    assert "Attach target: python uvicorn pid=321 port=8000" in output
    assert "Attach detail:" in output
    assert "Will skip runtime execution:" in output
    assert "RepoGraph live tracing" in output
    assert "Step 2/3: dynamic analysis will not run." in output
    assert "Dynamic Analysis Result" in output
    assert "Executed: no" in output
    assert "Cleanup: not applicable" in output
    assert "finalizing evidence and exports without runtime overlay inputs" in output


def test_cli_sync_full_dispatches_dynamic_runner(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".repograph").mkdir()
    (repo / ".repograph" / "meta").mkdir()

    with patch("repograph.pipeline.runner.run_full_pipeline_with_runtime_overlay", return_value={"files": 1}) as dynamic_run:
        result = CliRunner().invoke(app, ["sync", str(repo), "--full"])

    assert result.exit_code == 0, result.stdout
    dynamic_run.assert_called_once()


def test_cli_sync_warns_when_repo_venv_exists_but_launcher_uses_other_python(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".repograph").mkdir()
    (repo / ".repograph" / "meta").mkdir()
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").write_text("", encoding="utf-8")
    activate_path = venv_bin / "activate"
    activate_path.write_text("", encoding="utf-8")

    with patch("repograph.surfaces.cli.commands.sync.sys.executable", "/usr/bin/python3"):
        with patch(
            "repograph.pipeline.runner.run_full_pipeline_with_runtime_overlay",
            return_value={"files": 1},
        ) as dynamic_run:
            result = CliRunner().invoke(app, ["sync", str(repo), "--full"])

    assert result.exit_code == 0, result.stdout
    compact_output = _compact_terminal_output(result.stdout)
    assert _compact_terminal_output("Repo-local .venv detected") in compact_output
    assert _compact_terminal_output(
        "Dynamic analysis will use the current interpreter"
    ) in compact_output
    assert _compact_terminal_output(_repo_venv_activate_hint(str(repo))) in compact_output
    dynamic_run.assert_called_once()


def test_cli_sync_full_prompts_before_live_attach(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".repograph").mkdir()
    (repo / ".repograph" / "meta").mkdir()
    (repo / ".repograph" / "settings.json").write_text(
        '{"sync_runtime_attach_policy": "prompt"}',
        encoding="utf-8",
    )

    def _fake_dynamic_run(config: RunConfig) -> dict[str, int]:
        assert config.runtime_attach_policy == "prompt"
        assert config.runtime_attach_approval_resolver is not None
        approval = config.runtime_attach_approval_resolver(
            RuntimeAttachDecision(
                outcome="selected",
                reason="live_python_trace_session_detected",
                attach_mode="attach_live_python",
                strategy_id="python.live_trace_session",
                candidate_count=1,
                policy="prompt",
                target=LiveTarget(
                    pid=321,
                    runtime="python",
                    kind="uvicorn",
                    command=f"uvicorn main:app --app-dir {repo}",
                    association="command_path",
                    port=8000,
                ),
            )
        )
        assert approval.outcome == "approved"
        assert approval.reason == "operator_approved_live_attach"
        return {"files": 1}

    with patch(
        "repograph.pipeline.runner.run_full_pipeline_with_runtime_overlay",
        side_effect=_fake_dynamic_run,
    ) as dynamic_run:
        result = CliRunner().invoke(app, ["sync", str(repo), "--full"], input="y\n")

    assert result.exit_code == 0, result.stdout
    assert "Live attach candidate detected:" in result.stdout
    assert "Attach dynamic analysis to this running server?" in result.stdout
    dynamic_run.assert_called_once()


def test_service_sync_full_uses_runtime_overlay_and_passes_attach_policy(tmp_path: Path) -> None:
    from repograph.services import RepoGraphService

    repo = tmp_path / "repo"
    repo.mkdir()
    rg_dir = repo / ".repograph"
    rg_dir.mkdir()

    seen: dict[str, object] = {}

    def _fake_dynamic_run(config: RunConfig) -> dict[str, int]:
        seen["policy"] = config.runtime_attach_policy
        seen["resolver"] = config.runtime_attach_approval_resolver
        return {"files": 1}

    with patch(
        "repograph.pipeline.runner.run_full_pipeline_with_runtime_overlay",
        side_effect=_fake_dynamic_run,
    ) as dynamic_run:
        with patch("repograph.pipeline.runner.run_full_pipeline") as full_run:
            with patch("repograph.pipeline.runner.run_incremental_pipeline") as inc_run:
                with RepoGraphService(str(repo), repograph_dir=str(rg_dir)) as svc:
                    stats = svc.sync(full=True, attach_policy="never")

    assert stats == {"files": 1}
    assert seen["policy"] == "never"
    assert seen["resolver"] is None
    dynamic_run.assert_called_once()
    full_run.assert_not_called()
    inc_run.assert_not_called()


def test_cli_sync_full_respects_auto_dynamic_analysis_setting(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".repograph").mkdir()
    (repo / ".repograph" / "meta").mkdir()
    (repo / ".repograph" / "settings.json").write_text(
        '{"auto_dynamic_analysis": false}',
        encoding="utf-8",
    )

    with patch("repograph.pipeline.runner.run_full_pipeline", return_value={"files": 1}) as full_run:
        with patch("repograph.pipeline.runner.run_full_pipeline_with_runtime_overlay") as dynamic_run:
            result = CliRunner().invoke(app, ["sync", str(repo), "--full"])

    assert result.exit_code == 0, result.stdout
    full_run.assert_called_once()
    dynamic_run.assert_not_called()


def test_status_renders_attach_details_for_live_target_fallback(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    rg_dir = repo / ".repograph"
    meta_dir = rg_dir / "meta"
    meta_dir.mkdir(parents=True)
    (meta_dir / "health.json").write_text(
        (
            "{"
            '"status": "ok",'
            '"sync_mode": "full_with_runtime_overlay",'
            '"generated_at": "2026-04-03T00:00:00Z",'
            '"call_edges_total": 12,'
            '"dynamic_analysis": {'
            '"requested": true,'
            '"executed": true,'
            '"mode": "traced_tests",'
            '"resolution": "pyproject_tests_dir",'
            '"fallback_reason": "multiple_live_targets_detected",'
            '"attach_outcome": "ambiguous",'
            '"attach_reason": "multiple_live_targets_detected",'
            '"attach_mode": "none",'
            '"attach_candidate_count": 2,'
            '"trace_file_count": 1,'
            '"overlay_persisted_functions": 3,'
            '"pytest_exit_code": 0'
            '}'
            "}"
        ),
        encoding="utf-8",
    )

    class _DummyStore:
        def get_stats(self) -> dict[str, int]:
            return {"files": 1, "functions": 1}

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "repograph.surfaces.cli.commands.sync._cli_command_session",
        lambda *args, **kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        "repograph.surfaces.cli.commands.sync._get_root_and_store",
        lambda path: (str(repo), _DummyStore()),
    )

    result = CliRunner().invoke(app, ["status", str(repo)], color=False)

    assert result.exit_code == 0, result.stdout
    assert "Attach" in result.stdout
    assert "status=ambiguous" in result.stdout
    assert "multiple live runtime targets were" in result.stdout
    assert "could not choose one safe automatic attach target" in result.stdout


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


def test_cli_sync_rejects_removed_full_with_tests_alias(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".repograph").mkdir()
    (repo / ".repograph" / "meta").mkdir()

    result = CliRunner().invoke(app, ["sync", str(repo), "--full-with-tests"], color=False)

    assert result.exit_code == 2
    compact_output = _compact_terminal_output(result.output)
    assert _compact_terminal_output("No such option") in compact_output
    assert _compact_terminal_output("--full-with-tests") in compact_output


def test_full_pipeline_applies_coverage_overlay_without_runtime_traces(tmp_path: Path) -> None:
    from repograph.graph_store.store import GraphStore
    from repograph.services import RepoGraphService
    from repograph.pipeline.runner import run_full_pipeline

    repo = tmp_path / "repo"
    repo.mkdir()
    rg_dir = repo / ".repograph"
    (repo / "main.py").write_text(
        "def covered_function():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    (repo / "coverage.json").write_text(
        (
            '{'
            '"files": {'
            '"main.py": {'
            '"executed_lines": [2],'
            '"missing_lines": []'
            '}'
            '}'
            '}'
        ),
        encoding="utf-8",
    )

    stats = run_full_pipeline(
        RunConfig(
            repo_root=str(repo),
            repograph_dir=str(rg_dir),
            include_git=False,
            full=True,
        )
    )
    assert stats["functions"] >= 1

    store = GraphStore(str(rg_dir / "graph.db"))
    store.initialize_schema()
    try:
        rows = store.query(
            "MATCH (f:Function {qualified_name: 'covered_function'}) RETURN f.is_covered"
        )
        assert rows and rows[0][0] is True
    finally:
        store.close()

    health = read_health_json(str(rg_dir))
    assert health is not None
    assert health["dynamic_analysis"]["mode"] == "existing_inputs"
    assert health["dynamic_analysis"]["requested"] is True
    assert health["dynamic_analysis"]["executed"] is True
    assert health["dynamic_analysis"]["coverage_json_present"] is True
    assert health["dynamic_analysis"]["coverage_overlay_applied"] is True
    assert health["dynamic_analysis"]["runtime_overlay_applied"] is False
    assert health["analysis_readiness"]["coverage_json_present"] is True
    assert health["analysis_readiness"]["coverage_overlay_applied"] is True
    assert health["analysis_readiness"]["runtime_overlay_applied"] is False

    with RepoGraphService(str(repo), repograph_dir=str(rg_dir)) as svc:
        status = svc.status()
    assert status["health"]["analysis_readiness"]["coverage_overlay_applied"] is True


def test_full_pipeline_can_skip_dynamic_inputs_for_static_only_semantics(tmp_path: Path) -> None:
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import run_full_pipeline

    repo = tmp_path / "repo"
    repo.mkdir()
    rg_dir = repo / ".repograph"
    (repo / "main.py").write_text(
        "def covered_function():\n"
        "    return 1\n",
        encoding="utf-8",
    )
    (repo / "coverage.json").write_text(
        (
            '{'
            '"files": {'
            '"main.py": {'
            '"executed_lines": [2],'
            '"missing_lines": []'
            '}'
            '}'
            '}'
        ),
        encoding="utf-8",
    )

    stats = run_full_pipeline(
        RunConfig(
            repo_root=str(repo),
            repograph_dir=str(rg_dir),
            include_git=False,
            full=True,
            allow_dynamic_inputs=False,
        )
    )
    assert stats["functions"] >= 1

    store = GraphStore(str(rg_dir / "graph.db"))
    store.initialize_schema()
    try:
        rows = store.query(
            "MATCH (f:Function {qualified_name: 'covered_function'}) RETURN f.is_covered"
        )
        assert rows and rows[0][0] in (False, None)
    finally:
        store.close()

    health = read_health_json(str(rg_dir))
    assert health is not None
    assert health["dynamic_analysis"]["mode"] == "none"
    assert health["dynamic_analysis"]["requested"] is False
    assert health["dynamic_analysis"]["executed"] is False
    assert health["dynamic_analysis"]["skipped_reason"] == "dynamic_inputs_disabled"
    assert health["dynamic_analysis"]["coverage_json_present"] is True
    assert health["dynamic_analysis"]["coverage_overlay_applied"] is False
    assert health["analysis_readiness"]["coverage_json_present"] is True
    assert health["analysis_readiness"]["coverage_overlay_applied"] is False
    assert health["analysis_readiness"]["runtime_overlay_applied"] is False
