"""RepoGraph structured observability layer.

This package provides the canonical structured logging infrastructure for the
entire RepoGraph codebase.  It sits **alongside** the Rich-based console output
in ``repograph.utils.logging`` — it does not replace it.

Quick reference
---------------
::

    from repograph.observability import get_logger, span, log_degraded, log_swallowed

    # Module-level logger (cheap, safe before init)
    logger = get_logger(__name__)
    logger.info("phase started", file_count=42)
    logger.warning("resolution degraded", path="src/foo.py")

    # Span-based instrumentation
    with span("parse_file", subsystem="parsers", path=str(fp)) as s:
        result = parser.parse(fp)
        s.add_metadata(function_count=len(result.functions))

    # No-silent-failure policy helpers
    try:
        store.insert_edge(edge)
    except MissingNodeError as exc:
        log_degraded(logger, "missing node — edge skipped", exc=exc)

Bootstrap
---------
Call :func:`init_observability` once at pipeline start::

    from repograph.observability import init_observability, ObservabilityConfig
    from pathlib import Path
    import uuid

    init_observability(ObservabilityConfig(
        log_dir=Path(".repograph/logs"),
        run_id=uuid.uuid4().hex[:8],
    ))

And :func:`shutdown_observability` in a finally block to flush all records.

Log files
---------
Written to ``<log_dir>/<run_id>/``:

- ``all.jsonl``        — every record
- ``errors.jsonl``     — ERROR and CRITICAL only
- ``pipeline.jsonl``   — pipeline subsystem
- ``plugins.jsonl``    — plugin dispatch
- ``parsers.jsonl``    — file parsing
- ``graph_store.jsonl``— store operations
- ``runtime.jsonl``    — dynamic tracing
- ``services.jsonl``   — public service layer
- ``cli.jsonl``        — CLI / interactive
- ``mcp.jsonl``        — MCP server
- ``setup.jsonl``      — bootstrap / doctor
- ``incremental.jsonl``— incremental sync diff
- ``config.jsonl``     — config loading

``<log_dir>/latest`` is a symlink to the most recent run directory.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from repograph.observability._config import ObservabilityConfig
from repograph.observability._context import (
    get_obs_context,
    make_thread_context,
    set_obs_context,
)
from repograph.observability._logger import (
    get_logger,
    install_jsonl_handler,
    remove_jsonl_handler,
)
from repograph.observability._mixin import ObservableMixin
from repograph.observability._policy import log_degraded, log_swallowed
from repograph.observability._sinks import (
    SinkManager,
    get_active_sink,
    route_record,
    set_active_sink,
    update_latest_symlink,
)
from repograph.observability._spans import SpanContext, span, span_decorator

__all__ = [
    # Config
    "ObservabilityConfig",
    # Init / shutdown
    "init_observability",
    "shutdown_observability",
    "ensure_observability_session",
    "is_observability_active",
    "active_run_id",
    "new_run_id",
    # Logger
    "get_logger",
    # Context
    "set_obs_context",
    "get_obs_context",
    "make_thread_context",
    # Spans
    "span",
    "span_decorator",
    "SpanContext",
    # Policy
    "log_degraded",
    "log_swallowed",
    # Mixin
    "ObservableMixin",
]

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_active_config: ObservabilityConfig | None = None


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def new_run_id() -> str:
    """Generate a new short run ID (8-char lowercase hex)."""
    return uuid.uuid4().hex[:8]


def init_observability(config: ObservabilityConfig) -> None:
    """Initialise the structured observability layer for a pipeline run.

    Safe to call multiple times — if already initialised, the existing
    instance is shut down cleanly before the new one starts.

    Args:
        config: :class:`ObservabilityConfig` specifying log directory and run ID.
    """
    global _active_config

    # Shut down any existing sink first
    shutdown_observability()

    _active_config = config
    set_obs_context(run_id=config.run_id)

    if not config.enabled:
        return

    # Create and start the sink manager
    sink = SinkManager(config.run_dir, subsystem_files=config.subsystem_files)
    sink.start()
    set_active_sink(sink)
    update_latest_symlink(config.log_dir, config.run_id)

    # Install the JSONL handler on the repograph root logger
    install_jsonl_handler(min_level=config.min_level)

    # Emit a start record
    logger = get_logger("repograph.observability")
    logger.info(
        "observability initialised",
        run_id=config.run_id,
        log_dir=str(config.log_dir),
    )


def shutdown_observability() -> None:
    """Flush and close the active observability sink.

    Safe to call when not initialised.
    """
    global _active_config

    sink = get_active_sink()
    if sink is not None:
        try:
            logger = get_logger("repograph.observability")
            logger.info("observability shutdown", run_id=_active_config.run_id if _active_config else "")
        except Exception:  # noqa: BLE001
            pass
        sink.shutdown()
        set_active_sink(None)

    remove_jsonl_handler()
    _active_config = None


def is_observability_active() -> bool:
    """Return True when a structured-log session is currently active."""
    return _active_config is not None and get_active_sink() is not None


def active_run_id() -> str | None:
    """Return the current structured-log run id, if any."""
    if _active_config is None:
        return None
    return _active_config.run_id


def ensure_observability_session(
    log_dir: str | Path,
    *,
    run_id: str | None = None,
    command_id: str | None = None,
    min_level: str = "DEBUG",
    subsystem_files: bool = True,
) -> str | None:
    """Start a structured-log session when none is active.

    Returns the created run id when this call started a new session; otherwise
    returns ``None`` and leaves the existing session untouched.
    """
    if _active_config is not None:
        if command_id:
            set_obs_context(command_id=command_id)
        return None

    resolved_run_id = run_id or new_run_id()
    init_observability(
        ObservabilityConfig(
            log_dir=Path(log_dir),
            run_id=resolved_run_id,
            min_level=min_level,
            subsystem_files=subsystem_files,
        )
    )
    if command_id:
        set_obs_context(command_id=command_id)
    return resolved_run_id
