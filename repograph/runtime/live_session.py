"""Live-session registry for long-running RepoGraph-traced Python processes.

RepoGraph cannot safely inject ``sys.settrace`` into an arbitrary running
Python process. The supported live-attach path therefore requires a process
that is already running with RepoGraph tracing active. Those processes publish
small session marker files here so orchestration can detect when a repo-scoped
live target is genuinely trace-capable.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from repograph.runtime.trace_format import live_session_dir

__all__ = [
    "ActiveTraceSession",
    "clear_live_trace_session",
    "list_live_trace_sessions",
    "read_live_trace_session",
    "register_live_trace_session",
]


@dataclass(frozen=True)
class ActiveTraceSession:
    """Registry record for one RepoGraph-traced live Python process."""

    pid: int
    repo_root: str
    trace_path: str
    started_at: float
    session_name: str
    tracer: str = "repograph.systrace"
    python_version: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> ActiveTraceSession | None:
        if not data:
            return None
        pid = data.get("pid")
        trace_path = str(data.get("trace_path") or "").strip()
        if pid in (None, "") or not trace_path:
            return None
        return cls(
            pid=int(pid),
            repo_root=str(data.get("repo_root") or ""),
            trace_path=trace_path,
            started_at=float(data.get("started_at") or 0.0),
            session_name=str(data.get("session_name") or "live"),
            tracer=str(data.get("tracer") or "repograph.systrace"),
            python_version=str(data.get("python_version") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pid": self.pid,
            "repo_root": self.repo_root,
            "trace_path": self.trace_path,
            "started_at": self.started_at,
            "session_name": self.session_name,
            "tracer": self.tracer,
        }
        if self.python_version:
            payload["python_version"] = self.python_version
        return payload


def _session_path(repograph_dir: str | Path, pid: int) -> Path:
    return live_session_dir(repograph_dir) / f"{int(pid)}.json"


def register_live_trace_session(
    repograph_dir: str | Path,
    session: ActiveTraceSession,
) -> Path:
    """Persist a live-session marker and return the marker path."""
    session_dir = live_session_dir(repograph_dir)
    session_dir.mkdir(parents=True, exist_ok=True)
    path = _session_path(repograph_dir, session.pid)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(session.to_dict(), fh, indent=2)
        fh.write("\n")
    return path


def clear_live_trace_session(repograph_dir: str | Path, pid: int) -> None:
    """Remove a live-session marker if it exists."""
    path = _session_path(repograph_dir, pid)
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def read_live_trace_session(
    repograph_dir: str | Path,
    pid: int,
) -> ActiveTraceSession | None:
    """Load one live-session marker by PID."""
    path = _session_path(repograph_dir, pid)
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:
        return None
    return ActiveTraceSession.from_mapping(payload)


def list_live_trace_sessions(repograph_dir: str | Path) -> tuple[ActiveTraceSession, ...]:
    """Return every readable live-session marker under ``.repograph/runtime/live_sessions``."""
    session_dir = live_session_dir(repograph_dir)
    if not session_dir.is_dir():
        return ()
    sessions: list[ActiveTraceSession] = []
    for path in sorted(session_dir.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            continue
        session = ActiveTraceSession.from_mapping(payload)
        if session is None:
            continue
        if not os.path.isabs(session.trace_path):
            continue
        sessions.append(session)
    return tuple(sessions)
