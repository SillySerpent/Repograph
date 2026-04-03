from __future__ import annotations

import json
import os
from pathlib import Path

from repograph.runtime.live_session import (
    ActiveTraceSession,
    list_live_trace_sessions,
    read_live_trace_session,
)
from repograph.runtime.attach import find_attach_strategy_for_target
from repograph.runtime.orchestration import LiveTarget
from repograph.runtime.tracer import SysTracer


def test_trace_call_can_publish_and_clear_a_live_session(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repograph_dir = repo_root / ".repograph"
    repo_root.mkdir()
    repograph_dir.mkdir()
    tracer = SysTracer(
        repo_root=str(repo_root),
        repograph_dir=str(repograph_dir),
        session_name="sitecustomize",
        trace_subdir="live",
        publish_live_session=True,
    )
    tracer.start()
    try:
        session = read_live_trace_session(str(repograph_dir), os.getpid())
        assert session is not None
        assert "/runtime/live/" in session.trace_path
    finally:
        tracer.stop()
    sessions = list_live_trace_sessions(str(repograph_dir))
    assert sessions == ()


def test_read_live_session_roundtrip_from_mapping(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repograph_dir = repo_root / ".repograph"
    live_sessions = repograph_dir / "runtime" / "live_sessions"
    live_sessions.mkdir(parents=True)
    trace_path = repograph_dir / "runtime" / "live" / "sitecustomize.jsonl"
    trace_path.parent.mkdir(parents=True)
    trace_path.write_text('{"kind":"session"}\n', encoding="utf-8")
    session = ActiveTraceSession(
        pid=123,
        repo_root=str(repo_root),
        trace_path=str(trace_path),
        started_at=1.0,
        session_name="sitecustomize",
        python_version="3.12.4",
    )
    (live_sessions / "123.json").write_text(
        json.dumps(session.to_dict(), indent=2),
        encoding="utf-8",
    )

    loaded = read_live_trace_session(str(repograph_dir), 123)

    assert loaded == session


def test_live_python_attach_strategy_is_registered_for_python_targets() -> None:
    strategy = find_attach_strategy_for_target(
        LiveTarget(
            pid=123,
            runtime="python",
            kind="uvicorn",
            command="uvicorn main:app",
            association="command_path",
            port=8000,
        )
    )

    assert strategy is not None
    assert strategy.strategy_id == "python.live_trace_session"
    assert strategy.mode == "attach_live_python"
