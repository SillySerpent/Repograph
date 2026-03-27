"""JSONL file sinks for structured log records.

Architecture
------------
A single background :class:`_LogWriter` thread dequeues :class:`LogRecord`
dicts and writes them to the appropriate JSONL files.  The main thread only
enqueues records (O(1), never blocks on file I/O).

On :func:`shutdown_sinks` the queue is flushed before the writer thread exits.

Subsystem routing
-----------------
Each record carries a ``subsystem`` field.  Records are routed to:

- ``all.jsonl``           — every record
- ``errors.jsonl``        — level >= ERROR (40)
- ``<subsystem>.jsonl``   — if ``subsystem_files=True`` and subsystem is known

Known subsystem file names::

    pipeline, plugins, parsers, graph_store, runtime,
    services, cli, mcp, setup, incremental, config

Records from unknown subsystems go to ``all.jsonl`` and ``errors.jsonl`` only.
"""
from __future__ import annotations

import json
import os
import queue
import threading
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SENTINEL = object()  # poison pill to stop the writer thread

KNOWN_SUBSYSTEMS = frozenset(
    {
        "pipeline",
        "plugins",
        "parsers",
        "graph_store",
        "runtime",
        "services",
        "cli",
        "mcp",
        "setup",
        "incremental",
        "config",
        "observability",
    }
)

# ---------------------------------------------------------------------------
# SinkManager
# ---------------------------------------------------------------------------


class SinkManager:
    """Manages open JSONL file handles and routes log records.

    Instantiated once per run by :func:`repograph.observability.init_observability`.
    Not intended to be used directly — use :func:`route_record` instead.
    """

    def __init__(self, run_dir: Path, *, subsystem_files: bool = True) -> None:
        self._run_dir = run_dir
        self._subsystem_files = subsystem_files
        self._queue: queue.Queue[dict[str, Any] | object] = queue.Queue()
        self._handles: dict[str, Any] = {}  # name → file object
        self._thread: threading.Thread | None = None
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Create log directory, open file handles, start writer thread."""
        if self._started:
            return
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._handles["all"] = open(self._run_dir / "all.jsonl", "a", encoding="utf-8", buffering=1)
        self._handles["errors"] = open(self._run_dir / "errors.jsonl", "a", encoding="utf-8", buffering=1)
        if self._subsystem_files:
            for sub in KNOWN_SUBSYSTEMS:
                self._handles[sub] = open(
                    self._run_dir / f"{sub}.jsonl", "a", encoding="utf-8", buffering=1
                )
        self._thread = threading.Thread(
            target=self._writer_loop,
            name="repograph-obs-writer",
            daemon=True,
        )
        self._thread.start()
        self._started = True

    def shutdown(self, timeout: float = 5.0) -> None:
        """Flush the queue and close all file handles."""
        if not self._started:
            return
        self._queue.put(_SENTINEL)
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        for handle in self._handles.values():
            try:
                handle.flush()
                handle.close()
            except OSError:
                pass
        self._handles.clear()
        self._started = False

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def route(self, record: dict[str, Any]) -> None:
        """Enqueue a log record for async file writing (never blocks)."""
        if self._started:
            self._queue.put_nowait(record)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _writer_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                break
            self._write(item)  # type: ignore[arg-type]

    def _write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, default=str) + "\n"
        # Always write to all.jsonl
        self._safe_write("all", line)
        # Write to errors.jsonl for ERROR/CRITICAL
        if record.get("level_no", 0) >= 40:
            self._safe_write("errors", line)
        # Route to subsystem file
        subsystem = record.get("subsystem")
        if subsystem and subsystem in KNOWN_SUBSYSTEMS and self._subsystem_files:
            self._safe_write(subsystem, line)

    def _safe_write(self, name: str, line: str) -> None:
        handle = self._handles.get(name)
        if handle is not None:
            try:
                handle.write(line)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Module-level active sink (set by init_observability)
# ---------------------------------------------------------------------------

_active_sink: SinkManager | None = None


def get_active_sink() -> SinkManager | None:
    return _active_sink


def set_active_sink(sink: SinkManager | None) -> None:
    global _active_sink
    _active_sink = sink


def route_record(record: dict[str, Any]) -> None:
    """Route a log record to the active sink (no-op if not initialised)."""
    if _active_sink is not None:
        _active_sink.route(record)


def update_latest_symlink(log_dir: Path, run_id: str) -> None:
    """Update ``log_dir/latest`` to point to the current run directory."""
    latest = log_dir / "latest"
    target = log_dir / run_id
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink(missing_ok=True)
        os.symlink(target, latest)
    except OSError:
        pass  # symlink creation is best-effort (e.g. Windows without privileges)
