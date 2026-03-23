"""Ephemeral runtime tracing helpers for one-shot dynamic syncs.

Unlike ``repograph trace install``, these helpers do not write tracked files
into the repository.

For pytest commands the tracer is injected as an ephemeral plugin module
passed via ``-p <module>``.  The plugin activates only in
``pytest_sessionstart`` (after collection) so interpreter startup and
collection noise are never traced, and subprocesses spawned by tests do not
inherit tracing because they do not pass ``-p``.

For non-pytest commands the legacy ``sitecustomize.py`` fallback is used, which
starts tracing at interpreter startup via ``PYTHONPATH`` injection.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import IO, Any

from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="runtime")

# ---------------------------------------------------------------------------
# pytest plugin bootstrap (preferred path)
# ---------------------------------------------------------------------------

# Module name written to the temp dir and loaded via ``-p <name>``.
_PLUGIN_MODULE_NAME = "_repograph_ephemeral_trace"

_PYTEST_PLUGIN_TEMPLATE = """\
\"\"\"Ephemeral RepoGraph trace plugin — auto-generated, do not edit.\"\"\"
from __future__ import annotations


def pytest_configure(config):
    from repograph.runtime.tracer import SysTracer as _SysTracer

    class _RepoGraphEphemeralPlugin:
        def __init__(self):
            self._tracer = None

        def pytest_sessionstart(self, session):
            self._tracer = _SysTracer(
                repo_root={repo_root!r},
                repograph_dir={repograph_dir!r},
                session_name={session_name!r},
            )
            self._tracer.start()

        def pytest_sessionfinish(self, session, exitstatus):
            if self._tracer:
                self._tracer.stop()
                self._tracer = None

    if not config.pluginmanager.has_plugin("repograph_ephemeral"):
        config.pluginmanager.register(_RepoGraphEphemeralPlugin(), "repograph_ephemeral")
"""

# ---------------------------------------------------------------------------
# sitecustomize fallback (non-pytest commands)
# ---------------------------------------------------------------------------

_SITECUSTOMIZE_TEMPLATE = """\
import atexit as _atexit
from repograph.runtime.tracer import SysTracer as _SysTracer

_TRACER = _SysTracer(
    repo_root={repo_root!r},
    repograph_dir={repograph_dir!r},
    session_name={session_name!r},
)
_TRACER.start()
_atexit.register(_TRACER.stop)
"""


@dataclass
class TracedProcess:
    """A long-lived subprocess running with ephemeral tracing enabled."""

    process: subprocess.Popen[str]
    command: tuple[str, ...]
    process_group_id: int | None
    bootstrap_dir: str
    stdout_path: str
    stderr_path: str
    _stdout_handle: IO[str] | None = field(repr=False, default=None)
    _stderr_handle: IO[str] | None = field(repr=False, default=None)

    @property
    def pid(self) -> int:
        return int(self.process.pid)

    def close_streams(self) -> None:
        for handle in (self._stdout_handle, self._stderr_handle):
            if handle is not None and not handle.closed:
                handle.close()


def _prepare_trace_bootstrap(
    command: list[str],
    *,
    repo_root: str,
    repograph_dir: str,
    session_name: str,
    bootstrap_dir: Path,
) -> tuple[list[str], dict[str, str]]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{bootstrap_dir}{os.pathsep}{existing}" if existing else str(bootstrap_dir)
    )

    root = Path(repo_root).resolve()
    rg_dir = Path(repograph_dir).resolve()

    if _is_pytest_command(command):
        (bootstrap_dir / f"{_PLUGIN_MODULE_NAME}.py").write_text(
            dedent(
                _PYTEST_PLUGIN_TEMPLATE.format(
                    repo_root=str(root),
                    repograph_dir=str(rg_dir),
                    session_name=session_name,
                )
            ),
            encoding="utf-8",
        )
        return list(command) + ["-p", _PLUGIN_MODULE_NAME], env

    (bootstrap_dir / "sitecustomize.py").write_text(
        dedent(
            _SITECUSTOMIZE_TEMPLATE.format(
                repo_root=str(root),
                repograph_dir=str(rg_dir),
                session_name=session_name,
            )
        ),
        encoding="utf-8",
    )
    return list(command), env


def _temporary_log_file(suffix: str) -> tuple[str, IO[str]]:
    fd, path = tempfile.mkstemp(prefix="repograph-trace-", suffix=suffix)
    return path, os.fdopen(fd, "w+", encoding="utf-8")


def _is_pytest_command(command: list[str]) -> bool:
    """Return True when *command* is recognisably a pytest invocation."""
    for i, part in enumerate(command):
        if part == "-m" and i + 1 < len(command) and command[i + 1] == "pytest":
            return True
        basename = os.path.basename(part)
        if basename in ("pytest", "py.test"):
            return True
    return False


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_group_exists(process_group_id: int | None) -> bool | None:
    if process_group_id is None or not hasattr(os, "killpg"):
        return None
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run_command_under_trace(
    command: list[str],
    *,
    repo_root: str,
    repograph_dir: str,
    session_name: str = "pytest",
) -> subprocess.CompletedProcess[bytes]:
    """Run *command* with ephemeral tracing enabled.

    For pytest commands an ephemeral plugin module is injected via
    ``-p <module>`` so that:

    * Tracing starts in ``pytest_sessionstart`` (after collection), avoiding
      interpreter-startup and bootstrap noise.
    * Subprocess Python processes spawned by tests do not inherit tracing
      because they are not invoked with ``-p``.

    For other commands the legacy ``sitecustomize.py`` approach is used.
    """
    with tempfile.TemporaryDirectory(prefix="repograph-trace-") as td:
        bootstrap_dir = Path(td)
        cmd, env = _prepare_trace_bootstrap(
            command,
            repo_root=repo_root,
            repograph_dir=repograph_dir,
            session_name=session_name,
            bootstrap_dir=bootstrap_dir,
        )
        root = Path(repo_root).resolve()

        _logger.info(
            "ephemeral trace subprocess starting",
            command=" ".join(cmd),
            repo_root=str(root),
            repograph_dir=str(Path(repograph_dir).resolve()),
        )
        result = subprocess.run(cmd, cwd=str(root), env=env)
        _logger.info(
            "ephemeral trace subprocess finished",
            command=" ".join(cmd),
            returncode=int(result.returncode),
        )
        return result


def spawn_command_under_trace(
    command: list[str],
    *,
    repo_root: str,
    repograph_dir: str,
    session_name: str = "runtime_server",
) -> TracedProcess:
    """Spawn a long-lived traced subprocess and keep its bootstrap alive."""
    bootstrap_dir = Path(tempfile.mkdtemp(prefix="repograph-trace-"))
    stdout_path, stdout_handle = _temporary_log_file(".stdout.log")
    stderr_path, stderr_handle = _temporary_log_file(".stderr.log")
    cmd, env = _prepare_trace_bootstrap(
        command,
        repo_root=repo_root,
        repograph_dir=repograph_dir,
        session_name=session_name,
        bootstrap_dir=bootstrap_dir,
    )
    root = Path(repo_root).resolve()
    process = subprocess.Popen(
        cmd,
        cwd=str(root),
        env=env,
        stdout=stdout_handle,
        stderr=stderr_handle,
        stdin=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    process_group_id: int | None = None
    if hasattr(os, "getpgid"):
        try:
            process_group_id = os.getpgid(process.pid)
        except OSError:
            process_group_id = None
    _logger.info(
        "ephemeral traced process started",
        command=" ".join(cmd),
        repo_root=str(root),
        repograph_dir=str(Path(repograph_dir).resolve()),
        pid=int(process.pid),
        process_group_id=process_group_id,
    )
    return TracedProcess(
        process=process,
        command=tuple(cmd),
        process_group_id=process_group_id,
        bootstrap_dir=str(bootstrap_dir),
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        _stdout_handle=stdout_handle,
        _stderr_handle=stderr_handle,
    )


def stop_command_under_trace(
    traced: TracedProcess,
    *,
    terminate_timeout_seconds: float = 5.0,
    kill_timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    """Stop a traced subprocess and clean up its bootstrap artifacts."""
    process = traced.process
    cleanup: dict[str, Any] = {
        "pid": traced.pid,
        "process_group_id": traced.process_group_id,
        "stopped": False,
        "forced_kill": False,
        "returncode": process.poll(),
        "bootstrap_removed": False,
        "pid_alive_after_stop": None,
        "process_group_alive_after_stop": None,
        "stdout_path": traced.stdout_path,
        "stderr_path": traced.stderr_path,
    }

    try:
        if process.poll() is None:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                else:  # pragma: no cover - non-POSIX fallback
                    process.terminate()
                process.wait(timeout=terminate_timeout_seconds)
            except subprocess.TimeoutExpired:
                cleanup["forced_kill"] = True
                if hasattr(os, "killpg"):
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:  # pragma: no cover - non-POSIX fallback
                    process.kill()
                process.wait(timeout=kill_timeout_seconds)
        cleanup["returncode"] = process.returncode
    finally:
        traced.close_streams()
        shutil.rmtree(traced.bootstrap_dir, ignore_errors=True)
        cleanup["bootstrap_removed"] = not Path(traced.bootstrap_dir).exists()
        cleanup["pid_alive_after_stop"] = _pid_exists(traced.pid)
        cleanup["process_group_alive_after_stop"] = _process_group_exists(
            traced.process_group_id
        )
        cleanup["stopped"] = not cleanup["pid_alive_after_stop"] and not bool(
            cleanup["process_group_alive_after_stop"]
        )

    _logger.info(
        "ephemeral traced process stopped",
        pid=int(traced.pid),
        returncode=int(process.returncode) if process.returncode is not None else None,
        forced_kill=bool(cleanup["forced_kill"]),
        pid_alive_after_stop=bool(cleanup["pid_alive_after_stop"]),
        process_group_alive_after_stop=cleanup["process_group_alive_after_stop"],
        bootstrap_removed=bool(cleanup["bootstrap_removed"]),
    )
    return cleanup
