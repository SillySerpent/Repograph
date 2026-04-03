from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from repograph.runtime.live_session import ActiveTraceSession, register_live_trace_session
from repograph.runtime.orchestration import (
    describe_attach_outcome,
    describe_attach_policy,
    LiveTarget,
    describe_live_target,
    describe_runtime_mode,
    describe_runtime_reason,
    describe_runtime_resolution,
    describe_trace_collection,
    detect_live_targets,
    dynamic_input_state,
    resolve_runtime_plan,
)
from repograph.runtime.session import RuntimeAttachApproval


def test_resolve_runtime_plan_prefers_config_override(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    rg_dir = repo / ".repograph"
    rg_dir.mkdir(parents=True)
    (rg_dir / "settings.json").write_text(
        '{"sync_test_command": ["custom-test", "--fast"]}',
        encoding="utf-8",
    )

    plan = resolve_runtime_plan(str(repo))

    assert plan.mode == "traced_tests"
    assert plan.resolution == "config_override"
    assert plan.command == ("custom-test", "--fast")
    assert plan.skip_reason == ""
    assert plan.detected_targets == ()


def test_resolve_runtime_plan_autodetects_pyproject_tests_dir(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )

    plan = resolve_runtime_plan(str(repo))

    assert plan.mode == "traced_tests"
    assert plan.resolution == "pyproject_tests_dir"
    assert plan.command[-1] == "tests"
    assert plan.detected_targets == ()


def test_resolve_runtime_plan_returns_none_without_signal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    plan = resolve_runtime_plan(str(repo))

    assert plan.mode == "none"
    assert plan.command == ()
    assert plan.skip_reason == "no_pytest_signal"
    assert plan.detected_targets == ()


def test_detect_live_targets_finds_repo_scoped_python_and_node_servers(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    repo_root = str(repo.resolve())

    targets = detect_live_targets(
        repo_root,
        process_rows=[
            (101, f"python {repo_root}/app.py --port 5001"),
            (202, f"node {repo_root}/frontend/server.js --port 3000"),
            (303, "python /tmp/other_repo/app.py --port 9999"),
        ],
    )

    assert len(targets) == 2
    assert [(target.runtime, target.kind, target.port) for target in targets] == [
        ("node", "node_server_script", 3000),
        ("python", "python_server_script", 5001),
    ]


def test_detect_live_targets_ignores_internal_repograph_runtime_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    repo_root = str(repo.resolve())

    targets = detect_live_targets(
        repo_root,
        process_rows=[
            (
                101,
                f"python {repo_root}/.repograph/runtime_launchers/managed/server.py --port 5001",
            ),
            (202, f"python {repo_root}/run.py --port 5002"),
        ],
    )

    assert len(targets) == 1
    assert targets[0].pid == 202
    assert targets[0].port == 5002


def test_detect_live_targets_uses_wide_process_listing(monkeypatch, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    seen: dict[str, object] = {}

    def _fake_run(command, *, capture_output, text, check):
        seen["command"] = command
        assert capture_output is True
        assert text is True
        assert check is True
        return SimpleNamespace(stdout="")

    monkeypatch.setattr("repograph.runtime.orchestration.subprocess.run", _fake_run)

    targets = detect_live_targets(str(repo.resolve()))

    assert targets == ()
    assert seen["command"] == ["ps", "-axww", "-o", "pid=", "-o", "command="]


def test_resolve_runtime_plan_records_live_targets_when_falling_back_to_tests(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo_root = str(repo.resolve())
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )

    plan = resolve_runtime_plan(
        repo_root,
        process_rows=[(101, f"python {repo_root}/app.py --port 5001")],
    )

    assert plan.mode == "traced_tests"
    assert plan.resolution == "pyproject_tests_dir"
    assert plan.fallback_reason == "live_python_target_not_trace_capable"
    assert len(plan.detected_targets) == 1
    assert plan.detected_targets[0].port == 5001
    assert plan.attach_decision.outcome == "unavailable"
    assert plan.attach_decision.attach_mode == "attach_live_python"
    assert plan.attach_decision.target is not None
    assert plan.attach_decision.target.port == 5001


def test_resolve_runtime_plan_selects_live_session_target_when_command_lacks_repo_path(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo_root = str(repo.resolve())
    rg_dir = repo / ".repograph"
    rg_dir.mkdir(parents=True)
    live_trace = rg_dir / "runtime" / "live" / "sitecustomize.jsonl"
    live_trace.parent.mkdir(parents=True)
    live_trace.write_text('{"kind":"session"}\n', encoding="utf-8")
    register_live_trace_session(
        str(rg_dir),
        ActiveTraceSession(
            pid=101,
            repo_root=repo_root,
            trace_path=str(live_trace),
            started_at=1.0,
            session_name="sitecustomize",
            python_version="3.12.4",
        ),
    )

    plan = resolve_runtime_plan(
        repo_root,
        repograph_dir=str(rg_dir),
        process_rows=[(101, "python run.py --port 5001")],
        attach_policy="always",
    )

    assert plan.mode == "attach_live_python"
    assert plan.resolution == "live_target_attach"
    assert plan.attach_decision.outcome == "selected"
    assert plan.attach_decision.target is not None
    assert plan.attach_decision.target.pid == 101
    assert plan.attach_decision.target.association == "live_session"
    assert plan.attach_decision.target.port == 5001
    assert plan.probe_url == "http://127.0.0.1:5001/"


def test_resolve_runtime_plan_selects_attachable_live_python_target(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo_root = str(repo.resolve())
    rg_dir = repo / ".repograph"
    rg_dir.mkdir(parents=True)
    live_trace = rg_dir / "runtime" / "live" / "sitecustomize.jsonl"
    live_trace.parent.mkdir(parents=True)
    live_trace.write_text('{"kind":"session"}\n', encoding="utf-8")
    register_live_trace_session(
        str(rg_dir),
        ActiveTraceSession(
            pid=101,
            repo_root=repo_root,
            trace_path=str(live_trace),
            started_at=1.0,
            session_name="sitecustomize",
            python_version="3.12.4",
        ),
    )

    plan = resolve_runtime_plan(
        repo_root,
        repograph_dir=str(rg_dir),
        process_rows=[(101, f"uvicorn main:app --app-dir {repo_root} --port 5001")],
        attach_policy="always",
    )

    assert plan.mode == "attach_live_python"
    assert plan.resolution == "live_target_attach"
    assert plan.command == ()
    assert plan.probe_url == "http://127.0.0.1:5001/"
    assert plan.scenario_urls == ("http://127.0.0.1:5001/",)
    assert plan.attach_decision.outcome == "selected"
    assert plan.attach_decision.reason == "live_python_trace_session_detected"
    assert plan.attach_decision.policy == "always"
    assert plan.attach_decision.approval.outcome == "approved"
    assert plan.attach_decision.target is not None
    assert plan.attach_decision.target.pid == 101


def test_resolve_runtime_plan_coalesces_duplicate_selected_live_python_processes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo_root = str(repo.resolve())
    rg_dir = repo / ".repograph"
    rg_dir.mkdir(parents=True)
    (rg_dir / "settings.json").write_text(
        '{"sync_runtime_probe_url": "http://127.0.0.1:5001/"}',
        encoding="utf-8",
    )
    live_trace = rg_dir / "runtime" / "live" / "sitecustomize.jsonl"
    live_trace.parent.mkdir(parents=True)
    live_trace.write_text('{"kind":"session"}\n', encoding="utf-8")
    register_live_trace_session(
        str(rg_dir),
        ActiveTraceSession(
            pid=101,
            repo_root=repo_root,
            trace_path=str(live_trace),
            started_at=1.0,
            session_name="sitecustomize",
            python_version="3.12.4",
        ),
    )
    register_live_trace_session(
        str(rg_dir),
        ActiveTraceSession(
            pid=202,
            repo_root=repo_root,
            trace_path=str(live_trace),
            started_at=2.0,
            session_name="sitecustomize",
            python_version="3.12.4",
        ),
    )

    plan = resolve_runtime_plan(
        repo_root,
        repograph_dir=str(rg_dir),
        process_rows=[
            (101, f"python {repo_root}/run.py"),
            (202, f"python {repo_root}/run.py"),
        ],
        attach_policy="always",
    )

    assert plan.mode == "attach_live_python"
    assert plan.resolution == "live_target_attach"
    assert plan.attach_decision.outcome == "selected"
    assert plan.attach_decision.candidate_count == 2
    assert plan.attach_decision.target is not None
    assert plan.attach_decision.target.pid == 202
    assert plan.attach_decision.approval.outcome == "approved"
    assert plan.probe_url == "http://127.0.0.1:5001/"


def test_resolve_runtime_plan_falls_back_when_operator_declines_live_attach(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo_root = str(repo.resolve())
    rg_dir = repo / ".repograph"
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    rg_dir.mkdir(parents=True)
    live_trace = rg_dir / "runtime" / "live" / "sitecustomize.jsonl"
    live_trace.parent.mkdir(parents=True)
    live_trace.write_text('{"kind":"session"}\n', encoding="utf-8")
    register_live_trace_session(
        str(rg_dir),
        ActiveTraceSession(
            pid=101,
            repo_root=repo_root,
            trace_path=str(live_trace),
            started_at=1.0,
            session_name="sitecustomize",
            python_version="3.12.4",
        ),
    )

    plan = resolve_runtime_plan(
        repo_root,
        repograph_dir=str(rg_dir),
        process_rows=[(101, f"uvicorn main:app --app-dir {repo_root} --port 5001")],
        attach_policy="prompt",
        attach_approval_resolver=lambda _decision: RuntimeAttachApproval(
            outcome="declined",
            reason="live_attach_declined",
        ),
    )

    assert plan.mode == "traced_tests"
    assert plan.resolution == "pyproject_tests_dir"
    assert plan.fallback_reason == "live_attach_declined"
    assert plan.attach_decision.outcome == "selected"
    assert plan.attach_decision.approval.outcome == "declined"
    assert plan.attach_decision.approval.reason == "live_attach_declined"


def test_resolve_runtime_plan_prefers_managed_runtime_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    rg_dir = repo / ".repograph"
    rg_dir.mkdir(parents=True)
    (rg_dir / "settings.json").write_text(
        (
            "{"
            '"sync_runtime_server_command": ["python", "app.py"],'
            '"sync_runtime_probe_url": "http://127.0.0.1:8000/health",'
            '"sync_runtime_scenario_urls": ["/", "/health"],'
            '"sync_runtime_scenario_driver_command": ["python", "tools/runtime_driver.py"],'
            '"sync_runtime_ready_timeout": 9'
            "}"
        ),
        encoding="utf-8",
    )

    plan = resolve_runtime_plan(str(repo))

    assert plan.mode == "managed_python_server"
    assert plan.resolution == "managed_runtime_config"
    assert plan.command == ("python", "app.py")
    assert plan.probe_url == "http://127.0.0.1:8000/health"
    assert plan.scenario_urls == ("/", "/health")
    assert plan.scenario_driver_command == ("python", "tools/runtime_driver.py")
    assert plan.ready_timeout == 9


def test_resolve_runtime_plan_falls_back_when_managed_runtime_probe_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    rg_dir = repo / ".repograph"
    (repo / "tests").mkdir(parents=True)
    rg_dir.mkdir(parents=True)
    (repo / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (rg_dir / "settings.json").write_text(
        '{"sync_runtime_server_command": ["python", "app.py"]}',
        encoding="utf-8",
    )

    plan = resolve_runtime_plan(str(repo))

    assert plan.mode == "traced_tests"
    assert plan.resolution == "pyproject_tests_dir"
    assert plan.fallback_reason == "managed_runtime_missing_probe_url"


def test_resolve_runtime_plan_reports_live_target_skip_when_no_tests_exist(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    repo_root = str(repo.resolve())

    plan = resolve_runtime_plan(
        repo_root,
        process_rows=[(404, f"uvicorn main:app --app-dir {repo_root} --port 8000")],
    )

    assert plan.mode == "none"
    assert plan.command == ()
    assert plan.resolution == "live_target_detected"
    assert plan.skip_reason == "live_python_target_not_trace_capable"
    assert len(plan.detected_targets) == 1
    assert plan.detected_targets[0].kind == "uvicorn"
    assert plan.attach_decision.outcome == "unavailable"
    assert plan.attach_decision.target is not None
    assert plan.attach_decision.target.kind == "uvicorn"


def test_resolve_runtime_plan_marks_multiple_live_targets_as_ambiguous(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo_root = str(repo.resolve())
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "test_app.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )

    plan = resolve_runtime_plan(
        repo_root,
        process_rows=[
            (101, f"uvicorn main:app --app-dir {repo_root} --port 8000"),
            (202, f"python {repo_root}/scripts/server.py --port 5001"),
        ],
    )

    assert plan.mode == "traced_tests"
    assert plan.resolution == "pyproject_tests_dir"
    assert plan.fallback_reason == "multiple_live_targets_detected"
    assert len(plan.detected_targets) == 2
    assert plan.attach_decision.outcome == "ambiguous"
    assert plan.attach_decision.candidate_count == 2
    assert plan.attach_decision.target is None


def test_dynamic_input_state_reports_coverage_json_without_traces(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    rg_dir = repo / ".repograph"
    rg_dir.mkdir(parents=True)
    (repo / "coverage.json").write_text("{}", encoding="utf-8")

    inputs = dynamic_input_state(str(repo), str(rg_dir))

    assert inputs.trace_file_count == 0
    assert inputs.trace_record_count == 0
    assert inputs.coverage_json_present is True
    assert inputs.inputs_present is True


def test_runtime_descriptors_explain_mode_resolution_and_reason() -> None:
    assert describe_runtime_mode("traced_tests") == "traced tests"
    assert describe_attach_outcome("unsupported") == "unsupported"
    assert describe_attach_policy("prompt") == "prompt"
    assert describe_attach_outcome("unavailable") == "unavailable"
    assert (
        describe_runtime_resolution("pyproject_tests_dir")
        == "pyproject.toml pytest config with tests/ directory"
    )
    assert (
        describe_runtime_reason("live_python_target_not_trace_capable")
        == "the detected live Python runtime is not running with RepoGraph live tracing, "
        "so automatic attach could not safely collect evidence from it"
    )
    assert (
        describe_trace_collection("attach_live_python")
        == "reuse a RepoGraph-traced live Python process and capture only the current attach delta"
    )


def test_describe_live_target_includes_runtime_kind_pid_and_port() -> None:
    target = LiveTarget(
        pid=321,
        runtime="python",
        kind="uvicorn",
        command="uvicorn main:app",
        association="command_path",
        port=8000,
    )

    assert describe_live_target(target) == "python uvicorn pid=321 port=8000"
