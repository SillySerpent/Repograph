"""Context propagation for structured observability.

Uses :mod:`contextvars` so that context set in a calling frame is visible to
callee frames in the same thread/async task without explicit argument passing.

**Thread safety:** ``ContextVar`` values are *not* automatically inherited by
new threads — each thread starts with empty context.  When spawning worker
threads (see Block H parallel parsing), call :func:`copy_context` and run the
worker inside ``ctx.run(worker_fn)`` so the parent context propagates.

Usage::

    from repograph.observability._context import set_obs_context, get_obs_context

    set_obs_context(phase="p04_imports", run_id="a1b2c3d4")
    ctx = get_obs_context()  # {"phase": "p04_imports", "run_id": "a1b2c3d4", ...}
"""
from __future__ import annotations

from contextvars import ContextVar, copy_context
from typing import Any

# ---------------------------------------------------------------------------
# Individual context variables
# ---------------------------------------------------------------------------

_run_id: ContextVar[str] = ContextVar("obs_run_id", default="")
_command_id: ContextVar[str] = ContextVar("obs_command_id", default="")
_span_id: ContextVar[str] = ContextVar("obs_span_id", default="")
_subsystem: ContextVar[str] = ContextVar("obs_subsystem", default="")
_phase: ContextVar[str] = ContextVar("obs_phase", default="")
_plugin_id: ContextVar[str] = ContextVar("obs_plugin_id", default="")
_hook: ContextVar[str] = ContextVar("obs_hook", default="")

_ALL_VARS: dict[str, ContextVar[str]] = {
    "run_id": _run_id,
    "command_id": _command_id,
    "span_id": _span_id,
    "subsystem": _subsystem,
    "phase": _phase,
    "plugin_id": _plugin_id,
    "hook": _hook,
}


def set_obs_context(**kwargs: str) -> None:
    """Set one or more context variables for the current thread/task.

    Only keys present in ``_ALL_VARS`` are accepted; unknown keys are silently
    ignored to avoid hard failures in call sites that pass extra metadata.
    """
    for key, value in kwargs.items():
        var = _ALL_VARS.get(key)
        if var is not None:
            var.set(value)


def get_obs_context() -> dict[str, Any]:
    """Return a snapshot of all context variables as a plain dict.

    Values that are still at their default (empty string) are included as
    ``None`` so the JSONL schema stays stable.
    """
    return {
        key: (var.get() or None)
        for key, var in _ALL_VARS.items()
    }


def get_context_var(name: str) -> str:
    """Return the current value of a single named context variable."""
    var = _ALL_VARS.get(name)
    return var.get() if var is not None else ""


def make_thread_context():
    """Return the current :class:`contextvars.Context` for use in worker threads.

    Usage in ThreadPoolExecutor::

        ctx = make_thread_context()
        future = executor.submit(ctx.run, worker_fn, *args)
    """
    return copy_context()
