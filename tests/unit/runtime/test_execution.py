from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from repograph.runtime.execution import (
    apply_runtime_plan_metadata,
    build_dynamic_analysis_state,
    execute_runtime_plan,
)
from repograph.runtime.live_session import ActiveTraceSession, register_live_trace_session
from repograph.runtime.orchestration import LiveTarget, RuntimePlan
from repograph.runtime.session import (
    DynamicInputInventory,
    RuntimeAttachApproval,
    RuntimeAttachDecision,
)
from tests.support import allocate_free_port


def _pid_exists(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_apply_runtime_plan_metadata_sets_detected_targets() -> None:
    payload = build_dynamic_analysis_state()
    apply_runtime_plan_metadata(
        payload,
        RuntimePlan(
            mode="traced_tests",
            resolution="config_override",
            command=("python", "-m", "pytest"),
        ),
    )

    assert payload["mode"] == "traced_tests"
    assert payload["resolution"] == "config_override"
    assert payload["test_command"] == ["python", "-m", "pytest"]


def test_execute_runtime_plan_combines_http_and_driver_actions(monkeypatch, tmp_path) -> None:
    traced_process = SimpleNamespace(
        pid=321,
        process=SimpleNamespace(pid=321, poll=lambda: None, returncode=0),
        command=("python", "app.py"),
        bootstrap_dir=str(tmp_path / "bootstrap"),
        stdout_path=str(tmp_path / "stdout.log"),
        stderr_path=str(tmp_path / "stderr.log"),
    )

    monkeypatch.setattr(
        "repograph.runtime.execution.spawn_command_under_trace",
        lambda *args, **kwargs: traced_process,
    )
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
        "repograph.runtime.execution.run_scenario_driver",
        lambda *args, **kwargs: {
            "command": ["python", "tools/runtime_driver.py"],
            "ok": True,
            "exit_code": 0,
            "stdout_preview": "ok",
            "stderr_preview": "",
            "timeout_seconds": 5.0,
        },
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.stop_command_under_trace",
        lambda _traced: {"pid": 321, "stopped": True, "forced_kill": False},
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.dynamic_input_state",
        lambda *_args, **_kwargs: DynamicInputInventory(
            trace_file_count=1,
            trace_record_count=7,
            coverage_json_present=False,
            inputs_present=True,
        ),
    )

    result = execute_runtime_plan(
        RuntimePlan(
            mode="managed_python_server",
            resolution="managed_runtime_config",
            command=("python", "app.py"),
            probe_url="http://127.0.0.1:8000/health",
            scenario_urls=("/", "/health"),
            scenario_driver_command=("python", "tools/runtime_driver.py"),
            ready_timeout=5,
        ),
        repo_root=str(tmp_path),
        repograph_dir=str(tmp_path / ".repograph"),
        strict=False,
    )

    assert result.executed is True
    assert result.scenario_actions.kind == "combined"
    assert result.scenario_actions.planned_count == 3
    assert result.scenario_actions.successful_count == 3
    assert result.scenario_actions.driver is not None
    assert result.scenario_actions.driver.ok is True
    assert result.chosen_target is not None
    assert result.chosen_target.scenario_driver_command == ("python", "tools/runtime_driver.py")
    assert result.cleanup is not None
    assert result.cleanup.stopped is True
    assert result.input_state.trace_file_count == 1


def test_execute_runtime_plan_warns_on_driver_failure_when_not_strict(monkeypatch, tmp_path) -> None:
    traced_process = SimpleNamespace(
        pid=654,
        process=SimpleNamespace(pid=654, poll=lambda: None, returncode=0),
        command=("python", "app.py"),
        bootstrap_dir=str(tmp_path / "bootstrap"),
        stdout_path=str(tmp_path / "stdout.log"),
        stderr_path=str(tmp_path / "stderr.log"),
    )

    monkeypatch.setattr(
        "repograph.runtime.execution.spawn_command_under_trace",
        lambda *args, **kwargs: traced_process,
    )
    monkeypatch.setattr("repograph.runtime.execution.wait_for_http_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "repograph.runtime.execution.drive_http_scenarios",
        lambda **kwargs: {
            "planned_count": 1,
            "executed_count": 1,
            "successful_count": 1,
            "failed_count": 0,
            "requests": [{"url": "http://127.0.0.1:8000/health", "ok": True, "status_code": 200}],
        },
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.run_scenario_driver",
        lambda *args, **kwargs: {
            "command": ["python", "tools/runtime_driver.py"],
            "ok": False,
            "exit_code": 9,
            "stdout_preview": "",
            "stderr_preview": "boom",
            "timeout_seconds": 5.0,
        },
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.stop_command_under_trace",
        lambda _traced: {"pid": 654, "stopped": True, "forced_kill": False},
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.dynamic_input_state",
        lambda *_args, **_kwargs: DynamicInputInventory(
            trace_file_count=0,
            trace_record_count=0,
            coverage_json_present=False,
            inputs_present=False,
        ),
    )

    result = execute_runtime_plan(
        RuntimePlan(
            mode="managed_python_server",
            resolution="managed_runtime_config",
            command=("python", "app.py"),
            probe_url="http://127.0.0.1:8000/health",
            scenario_urls=("http://127.0.0.1:8000/health",),
            scenario_driver_command=("python", "tools/runtime_driver.py"),
            ready_timeout=5,
        ),
        repo_root=str(tmp_path),
        repograph_dir=str(tmp_path / ".repograph"),
        strict=False,
    )

    assert result.executed is True
    assert result.scenario_actions.failed_count == 1
    assert result.warnings == ("managed runtime scenario driver failed with exit code 9",)


def test_execute_runtime_plan_attaches_to_live_python_trace_session(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repograph_dir = repo_root / ".repograph"
    live_dir = repograph_dir / "runtime" / "live"
    live_dir.mkdir(parents=True)
    live_trace = live_dir / "sitecustomize.jsonl"
    live_trace.write_text('{"kind":"session"}\n', encoding="utf-8")
    register_live_trace_session(
        str(repograph_dir),
        ActiveTraceSession(
            pid=321,
            repo_root=str(repo_root),
            trace_path=str(live_trace),
            started_at=1.0,
            session_name="sitecustomize",
            python_version="3.12.4",
        ),
    )

    monkeypatch.setattr("repograph.runtime.attach.wait_for_http_ready", lambda *args, **kwargs: None)

    def _fake_http(**kwargs):
        with live_trace.open("a", encoding="utf-8") as fh:
            fh.write('{"kind":"call","fn":"app.index"}\n')
            fh.write('{"kind":"call","fn":"app.health"}\n')
        return {
            "planned_count": 1,
            "executed_count": 1,
            "successful_count": 1,
            "failed_count": 0,
            "requests": [{"url": "http://127.0.0.1:5001/", "ok": True, "status_code": 200}],
        }

    monkeypatch.setattr("repograph.runtime.attach.drive_http_scenarios", _fake_http)

    result = execute_runtime_plan(
        RuntimePlan(
            mode="attach_live_python",
            resolution="live_target_attach",
            command=(),
            probe_url="http://127.0.0.1:5001/",
            scenario_urls=("http://127.0.0.1:5001/",),
            attach_decision=RuntimeAttachDecision(
                outcome="selected",
                attach_mode="attach_live_python",
                strategy_id="python.live_trace_session",
                approval=RuntimeAttachApproval(
                    outcome="approved",
                    reason="operator_approved_live_attach",
                ),
                target=LiveTarget(
                    pid=321,
                    runtime="python",
                    kind="uvicorn",
                    command="uvicorn main:app",
                    association="command_path",
                    port=5001,
                ),
            ),
        ),
        repo_root=str(repo_root),
        repograph_dir=str(repograph_dir),
        strict=True,
    )

    assert result.executed is True
    assert result.chosen_target is not None
    assert result.chosen_target.source == "live_target"
    assert result.chosen_target.pid == 321
    assert result.scenario_actions.successful_count == 1
    assert result.cleanup is None
    assert result.input_state.trace_file_count == 1
    assert result.input_state.trace_record_count == 2
    runtime_files = sorted((repograph_dir / "runtime").glob("attach_live_python_*.jsonl"))
    assert len(runtime_files) == 1
    assert runtime_files[0].read_text(encoding="utf-8").count("\n") == 2


def test_execute_runtime_plan_warns_when_live_attach_yields_no_new_records(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repograph_dir = repo_root / ".repograph"
    live_dir = repograph_dir / "runtime" / "live"
    live_dir.mkdir(parents=True)
    live_trace = live_dir / "sitecustomize.jsonl"
    live_trace.write_text('{"kind":"session"}\n', encoding="utf-8")
    register_live_trace_session(
        str(repograph_dir),
        ActiveTraceSession(
            pid=777,
            repo_root=str(repo_root),
            trace_path=str(live_trace),
            started_at=1.0,
            session_name="sitecustomize",
            python_version="3.12.4",
        ),
    )

    monkeypatch.setattr("repograph.runtime.attach.wait_for_http_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "repograph.runtime.attach.drive_http_scenarios",
        lambda **kwargs: {
            "planned_count": 1,
            "executed_count": 1,
            "successful_count": 1,
            "failed_count": 0,
            "requests": [{"url": "http://127.0.0.1:5001/", "ok": True, "status_code": 200}],
        },
    )

    result = execute_runtime_plan(
        RuntimePlan(
            mode="attach_live_python",
            resolution="live_target_attach",
            command=(),
            probe_url="http://127.0.0.1:5001/",
            scenario_urls=("http://127.0.0.1:5001/",),
            attach_decision=RuntimeAttachDecision(
                outcome="selected",
                attach_mode="attach_live_python",
                strategy_id="python.live_trace_session",
                approval=RuntimeAttachApproval(
                    outcome="approved",
                    reason="operator_approved_live_attach",
                ),
                target=LiveTarget(
                    pid=777,
                    runtime="python",
                    kind="uvicorn",
                    command="uvicorn main:app",
                    association="command_path",
                    port=5001,
                ),
            ),
        ),
        repo_root=str(repo_root),
        repograph_dir=str(repograph_dir),
        strict=False,
    )

    assert result.executed is True
    assert result.input_state.trace_file_count == 0
    assert result.input_state.trace_record_count == 0
    assert result.warnings == (
        "live attach produced no new trace records; the server may not have executed "
        "application code during the attach window",
    )


def test_execute_runtime_plan_falls_back_from_attach_failure_to_managed_runtime(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "repograph.runtime.execution.execute_live_attach",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("attach handshake failed")
        ),
    )
    traced_process = SimpleNamespace(
        pid=654,
        process=SimpleNamespace(pid=654, poll=lambda: None, returncode=0),
        command=("python", "app.py"),
        bootstrap_dir=str(tmp_path / "bootstrap"),
        stdout_path=str(tmp_path / "stdout.log"),
        stderr_path=str(tmp_path / "stderr.log"),
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.spawn_command_under_trace",
        lambda *args, **kwargs: traced_process,
    )
    monkeypatch.setattr("repograph.runtime.execution.wait_for_http_ready", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "repograph.runtime.execution.drive_http_scenarios",
        lambda **kwargs: {
            "planned_count": 1,
            "executed_count": 1,
            "successful_count": 1,
            "failed_count": 0,
            "requests": [{"url": "http://127.0.0.1:8000/", "ok": True, "status_code": 200}],
        },
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.stop_command_under_trace",
        lambda _traced: {"pid": 654, "stopped": True, "forced_kill": False},
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.dynamic_input_state",
        lambda *_args, **_kwargs: DynamicInputInventory(
            trace_file_count=1,
            trace_record_count=9,
            coverage_json_present=False,
            inputs_present=True,
        ),
    )
    primary_plan = RuntimePlan(
        mode="attach_live_python",
        resolution="live_target_attach",
        command=(),
        probe_url="http://127.0.0.1:5001/",
        scenario_urls=("http://127.0.0.1:5001/",),
        attach_decision=RuntimeAttachDecision(
            outcome="selected",
            reason="live_python_trace_session_detected",
            attach_mode="attach_live_python",
            strategy_id="python.live_trace_session",
            approval=RuntimeAttachApproval(
                outcome="approved",
                reason="operator_approved_live_attach",
            ),
            target=LiveTarget(
                pid=321,
                runtime="python",
                kind="uvicorn",
                command="uvicorn main:app",
                association="command_path",
                port=5001,
            ),
        ),
    )
    fallback_plan = RuntimePlan(
        mode="managed_python_server",
        resolution="managed_runtime_config",
        command=("python", "app.py"),
        probe_url="http://127.0.0.1:8000/health",
        scenario_urls=("http://127.0.0.1:8000/",),
        ready_timeout=5,
    )

    result = execute_runtime_plan(
        primary_plan,
        repo_root=str(tmp_path),
        repograph_dir=str(tmp_path / ".repograph"),
        strict=False,
        fallback_plan_resolver=lambda _failed_plan: fallback_plan,
    )

    assert result.executed is True
    assert result.executed_mode == "managed_python_server"
    assert result.fallback is not None
    assert result.fallback.from_mode == "attach_live_python"
    assert result.fallback.to_mode == "managed_python_server"
    assert result.fallback.succeeded is True
    assert result.attempts[0].mode == "attach_live_python"
    assert result.attempts[0].outcome == "failed"
    assert "attach handshake failed" in result.attempts[0].detail
    assert result.attempts[1].mode == "managed_python_server"
    assert result.attempts[1].outcome == "succeeded"
    assert result.scenario_actions.successful_count == 1
    assert result.warnings == ()


def test_execute_runtime_plan_cleans_up_real_managed_server(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repograph_dir = repo_root / ".repograph"
    repograph_dir.mkdir()
    (repo_root / "index.html").write_text("managed runtime ok", encoding="utf-8")
    port = allocate_free_port()

    result = execute_runtime_plan(
        RuntimePlan(
            mode="managed_python_server",
            resolution="managed_runtime_config",
            command=(
                sys.executable,
                "-m",
                "http.server",
                str(port),
                "--bind",
                "127.0.0.1",
            ),
            probe_url=f"http://127.0.0.1:{port}/",
            ready_timeout=10,
        ),
        repo_root=str(repo_root),
        repograph_dir=str(repograph_dir),
        strict=True,
    )

    assert result.executed is True
    assert result.warnings == ()
    assert result.cleanup is not None
    assert result.cleanup.stopped is True
    assert result.cleanup.bootstrap_removed is True
    assert result.cleanup.pid_alive_after_stop is False
    assert result.cleanup.process_group_alive_after_stop is False
    assert _pid_exists(result.cleanup.pid) is False


def test_execute_runtime_plan_still_cleans_up_on_real_driver_failure(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    repograph_dir = repo_root / ".repograph"
    repograph_dir.mkdir()
    (repo_root / "index.html").write_text("managed runtime failure", encoding="utf-8")
    driver_script = repo_root / "driver_failure.py"
    driver_script.write_text(
        "\n".join(
            [
                "import os",
                "import sys",
                "import urllib.request",
                "",
                "with urllib.request.urlopen(os.environ['REPOGRAPH_PROBE_URL'], timeout=2.0):",
                "    pass",
                "sys.exit(7)",
            ]
        ),
        encoding="utf-8",
    )
    port = allocate_free_port()

    result = execute_runtime_plan(
        RuntimePlan(
            mode="managed_python_server",
            resolution="managed_runtime_config",
            command=(
                sys.executable,
                "-m",
                "http.server",
                str(port),
                "--bind",
                "127.0.0.1",
            ),
            probe_url=f"http://127.0.0.1:{port}/",
            scenario_driver_command=(sys.executable, str(driver_script)),
            ready_timeout=10,
        ),
        repo_root=str(repo_root),
        repograph_dir=str(repograph_dir),
        strict=False,
    )

    assert result.executed is True
    assert result.scenario_actions.kind == "driver"
    assert result.scenario_actions.driver is not None
    assert result.scenario_actions.driver.exit_code == 7
    assert result.cleanup is not None
    assert result.cleanup.stopped is True
    assert result.cleanup.bootstrap_removed is True
    assert result.cleanup.pid_alive_after_stop is False
    assert result.cleanup.process_group_alive_after_stop is False
    assert _pid_exists(result.cleanup.pid) is False
    assert result.warnings == ("managed runtime scenario driver failed with exit code 7",)


def test_runtime_execution_result_serializes_session_contract(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "repograph.runtime.execution.run_command_under_trace",
        lambda *args, **kwargs: subprocess.CompletedProcess(["pytest"], 0),
    )
    monkeypatch.setattr(
        "repograph.runtime.execution.dynamic_input_state",
        lambda *_args, **_kwargs: DynamicInputInventory(
            trace_file_count=2,
            trace_record_count=11,
            coverage_json_present=False,
            inputs_present=True,
        ),
    )

    result = execute_runtime_plan(
        RuntimePlan(
            mode="traced_tests",
            resolution="config_override",
            command=("python", "-m", "pytest", "tests"),
        ),
        repo_root=str(tmp_path),
        repograph_dir=str(tmp_path / ".repograph"),
        strict=True,
    )

    payload = result.to_analysis_update()

    assert payload["executed_mode"] == "traced_tests"
    assert payload["chosen_target"]["source"] == "test_command"
    assert payload["chosen_target"]["kind"] == "pytest"
    assert payload["cleanup"]["bootstrap_removed"] is True
    assert payload["trace_file_count"] == 2
    assert payload["trace_record_count"] == 11
    assert payload["execution_attempts"][0]["mode"] == "traced_tests"
    assert payload["execution_attempts"][0]["outcome"] == "succeeded"
