"""sys.settrace-based call tracer for RepoGraph dynamic analysis.

Usage (standalone — no pytest required)
-----------------------------------------
    from repograph.runtime.tracer import SysTracer

    with SysTracer(repo_root="/path/to/repo", repograph_dir="/path/to/.repograph"):
        # run code under trace
        your_function()

    # Trace file is now at .repograph/runtime/trace_<timestamp>.jsonl

Usage via pytest plugin
------------------------
    # In conftest.py:
    from repograph.runtime.tracer import install_pytest_plugin
    install_pytest_plugin()

    # Then run:
    pytest --repograph-trace

Implementation notes
---------------------
- Uses sys.settrace which works at the Python interpreter level.
- Filters to repo-relative files only (ignores stdlib, site-packages).
- Writes JSONL incrementally — each call is flushed immediately so traces
  survive interrupted test runs.
- Thread-safe: each thread gets its own settrace via threading.settrace.
- Overhead: typically 2–5× slower than uninstrumented code. Use on test
  suites, not production workloads.
"""
from __future__ import annotations

import inspect
import os
import sys
import time
import threading
from collections.abc import Callable
from pathlib import Path
from types import FrameType, TracebackType
from typing import TYPE_CHECKING, Any, TypeAlias, cast

from repograph.runtime.live_session import (
    ActiveTraceSession,
    clear_live_trace_session,
    register_live_trace_session,
)
from repograph.runtime.trace_format import (
    make_session_record,
    trace_dir,
    live_trace_dir,
)
from repograph.runtime.trace_filters import TraceFilter
from repograph.runtime.trace_policy import TracePolicy
from repograph.runtime.trace_writer import TraceWriter
from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="runtime")

if TYPE_CHECKING:
    from _typeshed import TraceFunction
else:
    TraceFunction: TypeAlias = Callable[[FrameType, str, object], object]


def _set_thread_trace(callback: TraceFunction | None) -> None:
    """Set the threading module trace hook.

    ``threading.settrace(None)`` is the correct runtime behavior for clearing
    the hook, but some Pylance stub sets still type the parameter as
    non-optional. Keep the compatibility cast isolated at the stdlib boundary.
    """
    threading.settrace(cast(Any, callback))


class SysTracer:
    """Context manager that traces Python calls to a JSONL file.

    Parameters
    ----------
    repo_root:
        Absolute path to the repository root.  Only calls from files
        under this path are recorded.
    repograph_dir:
        Path to ``.repograph/``.  Trace files are written to
        ``<repograph_dir>/runtime/``.
    include_stdlib:
        When True, also trace calls from the standard library.  Defaults
        to False (very noisy).
    session_name:
        Optional prefix for the trace file name.  Defaults to ``"trace"``.
    """

    def __init__(
        self,
        repo_root: str | Path,
        repograph_dir: str | Path,
        include_stdlib: bool = False,
        session_name: str = "trace",
        trace_policy: TracePolicy | None = None,
        *,
        trace_subdir: str = "",
        publish_live_session: bool = False,
    ) -> None:
        self.repo_root = str(Path(repo_root).resolve())
        self.repograph_dir = str(Path(repograph_dir).resolve())
        self.include_stdlib = include_stdlib
        self.session_name = session_name
        self.trace_policy = trace_policy or TracePolicy()
        self.trace_subdir = trace_subdir.strip().strip("/\\")
        self.publish_live_session = publish_live_session
        self._writer: TraceWriter | None = None
        self._filter = TraceFilter(self.trace_policy)
        self._path: Path | None = None
        self._lock = threading.Lock()
        self._prev_sys_trace: TraceFunction | None = None
        self._prev_thread_trace: TraceFunction | None = None

    def __enter__(self) -> "SysTracer":
        self.start()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        self.stop()

    def start(self) -> None:
        """Begin tracing."""
        out_dir = (
            live_trace_dir(self.repograph_dir)
            if self.trace_subdir == "live"
            else trace_dir(self.repograph_dir) / self.trace_subdir
            if self.trace_subdir
            else trace_dir(self.repograph_dir)
        )
        self._writer = TraceWriter(
            out_dir,
            self.session_name,
            self.trace_policy,
            single_file=True,
        )
        self._writer.open()
        self._path = self._writer.path

        # Write session header
        self._write({
            **make_session_record(self.repo_root),
            "policy": self.trace_policy.as_dict(),
        })
        if self.publish_live_session and self._path is not None:
            register_live_trace_session(
                self.repograph_dir,
                ActiveTraceSession(
                    pid=os.getpid(),
                    repo_root=self.repo_root,
                    trace_path=str(self._path),
                    started_at=time.time(),
                    session_name=self.session_name,
                    python_version=sys.version.split()[0],
                ),
            )

        self._prev_sys_trace = cast(TraceFunction | None, sys.gettrace())
        self._prev_thread_trace = cast(TraceFunction | None, threading.gettrace())
        sys.settrace(self._trace_fn)
        _set_thread_trace(self._trace_fn)

    def stop(self) -> None:
        """Stop tracing and flush the output file."""
        sys.settrace(self._prev_sys_trace)
        _set_thread_trace(self._prev_thread_trace)
        if self.publish_live_session:
            clear_live_trace_session(self.repograph_dir, os.getpid())
        if self._writer:
            with self._lock:
                self._write({
                    "kind": "session_end",
                    "ts": time.time(),
                    "written_records": self._writer.stats.written_records,
                    "dropped_records": self._writer.stats.dropped_records,
                    "dropped_by_reason": dict(sorted(self._writer.stats.dropped_by_reason.items())),
                    "rotated_files": self._writer.stats.rotated_files,
                })
                self._writer.close()
                self._writer = None

    @property
    def trace_path(self) -> Path | None:
        """Path to the written trace file (available after start())."""
        return self._path

    # ------------------------------------------------------------------
    # sys.settrace callback
    # ------------------------------------------------------------------

    def _trace_fn(
        self,
        frame: FrameType,
        event: str,
        arg: object,
    ) -> TraceFunction | None:
        del arg
        if event != "call":
            # Returning None here tells CPython not to install a local trace
            # function on this frame.  The global trace (sys.settrace) is still
            # self._trace_fn, so new call events continue to arrive normally.
            # Returning self._trace_fn instead would install a local trace on
            # every frame, causing line/return/exception callbacks on every
            # executed line — dramatically inflating CPU and memory usage.
            return None

        filename = frame.f_code.co_filename
        if not filename:
            return None

        # Only trace files inside repo_root
        try:
            rel = os.path.relpath(filename, self.repo_root)
        except ValueError:
            return None

        if rel.startswith("..") or rel.startswith("/"):
            return None

        # Skip non-source files (frozen modules, C extensions, etc.)
        if not filename.endswith(".py"):
            return None

        if not self.include_stdlib:
            if "site-packages" in filename or filename.startswith(sys.prefix):
                return None

        # Build qualified name from frame
        fn_name = frame.f_code.co_qualname if hasattr(frame.f_code, "co_qualname") else frame.f_code.co_name
        module = frame.f_globals.get("__name__", "")
        qualified = f"{module}.{fn_name}" if module else fn_name

        # Get caller info
        caller_frame = frame.f_back
        caller_qn = ""
        if caller_frame:
            caller_name = (
                caller_frame.f_code.co_qualname
                if hasattr(caller_frame.f_code, "co_qualname")
                else caller_frame.f_code.co_name
            )
            caller_mod = caller_frame.f_globals.get("__name__", "")
            caller_qn = f"{caller_mod}.{caller_name}" if caller_mod else caller_name

        record = {
            "kind": "call",
            "ts": time.time(),
            "fn": qualified,
            "file": rel.replace("\\", "/"),
            "line": frame.f_lineno,
            "caller": caller_qn,
        }
        decision = self._filter.allow(file_path=record["file"], qualified_name=qualified)
        if not decision.accepted:
            if self._writer:
                self._writer.stats.drop(decision.reason or "filtered")
            return None
        self._write(record)
        return None

    def _write(self, record: dict[str, Any]) -> None:
        if not self._writer:
            return
        self._writer.write(record)


# ---------------------------------------------------------------------------
# Convenience: run a callable under trace and return the trace path
# ---------------------------------------------------------------------------

def trace_call(
    fn: Callable[..., Any],
    *args: Any,
    repo_root: str,
    repograph_dir: str,
    session_name: str = "trace",
    trace_policy: TracePolicy | None = None,
    trace_subdir: str = "",
    publish_live_session: bool = False,
    **kwargs: Any,
) -> tuple[Any, Path | None]:
    """Run *fn(*args, **kwargs)* under trace. Return (result, trace_path).

    Example
    -------
        result, trace_path = trace_call(
            my_function, arg1, arg2,
            repo_root="/path/to/repo",
            repograph_dir="/path/to/repo/.repograph",
        )
    """
    tracer = SysTracer(
        repo_root=repo_root,
        repograph_dir=repograph_dir,
        session_name=session_name,
        trace_policy=trace_policy,
        trace_subdir=trace_subdir,
        publish_live_session=publish_live_session,
    )
    with tracer:
        result = fn(*args, **kwargs)
    return result, tracer.trace_path


# ---------------------------------------------------------------------------
# pytest plugin integration
# ---------------------------------------------------------------------------

def install_pytest_plugin() -> None:
    """Register the RepoGraph trace plugin with pytest.

    Call from conftest.py:

        from repograph.runtime.tracer import install_pytest_plugin
        install_pytest_plugin()

    Then run tests with::

        pytest --repograph-trace [--repograph-dir .repograph]

    Registration injects ``pytest_configure`` into the caller's module (there is
    no ``pytest.register_plugin_manager`` in current pytest).
    """
    frame = inspect.currentframe()
    if frame is None or frame.f_back is None:
        return
    mod_globals = frame.f_back.f_globals
    if mod_globals.get("_repograph_trace_plugin_registered"):
        return

    class _RepoGraphTracePlugin:
        def __init__(self):
            self.tracer: SysTracer | None = None

        def pytest_addoption(self, parser):
            parser.addoption(
                "--repograph-trace",
                action="store_true",
                default=False,
                help="Collect RepoGraph dynamic call traces during test run.",
            )
            parser.addoption(
                "--repograph-dir",
                default=".repograph",
                help="Path to .repograph directory (default: .repograph).",
            )

        def pytest_sessionstart(self, session):
            if not session.config.getoption("--repograph-trace", default=False):
                return
            repo_root = str(Path.cwd())
            repograph_dir = session.config.getoption("--repograph-dir")
            self.tracer = SysTracer(
                repo_root=repo_root,
                repograph_dir=repograph_dir,
                session_name="pytest",
            )
            self.tracer.start()
            print(f"\n[repograph] Tracing to: {self.tracer.trace_path}")

        def pytest_sessionfinish(self, session, exitstatus):
            if self.tracer:
                self.tracer.stop()
                print(f"\n[repograph] Trace written: {self.tracer.trace_path}")
                self.tracer = None

    _plugin = _RepoGraphTracePlugin()

    def _pytest_configure(config):
        if config.pluginmanager.has_plugin("repograph_trace"):
            return
        config.pluginmanager.register(_plugin, "repograph_trace")

    existing = mod_globals.get("pytest_configure")
    if existing is None:
        mod_globals["pytest_configure"] = _pytest_configure
    else:
        def _pytest_configure_chained(config):
            existing(config)
            _pytest_configure(config)

        mod_globals["pytest_configure"] = _pytest_configure_chained
    mod_globals["_repograph_trace_plugin_registered"] = True
