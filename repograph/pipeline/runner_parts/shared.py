"""Shared runner support for observability, console output, and cleanup.

These helpers are intentionally cross-cutting. They keep the orchestration
modules focused on sequencing work instead of repeating phase-span, warning,
and teardown policy in every coordinator.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from rich.console import Console

from repograph.observability import get_logger, set_obs_context, span
from repograph.observability._context import get_context_var

console = Console()
logger = get_logger(__name__, subsystem="pipeline")

__all__ = [
    "console",
    "logger",
    "close_store_quietly",
    "ensure_scheduler_bootstrapped",
    "handle_optional_phase_failure",
    "phase_scope",
]


@contextmanager
def phase_scope(phase: str, **metadata: Any) -> Iterator[Any]:
    """Attach phase context and emit one meaningful observability span."""
    prev_phase = get_context_var("phase")
    set_obs_context(phase=phase)
    try:
        with span(phase, subsystem="pipeline", **metadata) as span_ctx:
            yield span_ctx
    finally:
        set_obs_context(phase=prev_phase or "")


def handle_optional_phase_failure(
    config: Any,
    phase: str,
    exc: BaseException,
) -> None:
    """Apply the runner-wide strict/continue-on-error policy for optional work."""
    logger.warning(
        "optional phase failed",
        phase=phase,
        exc_type=type(exc).__name__,
        exc_msg=str(exc),
        strict=config.strict,
        continue_on_error=config.continue_on_error,
    )
    if config.strict:
        raise exc
    if not config.continue_on_error:
        raise RuntimeError(
            f"{phase} failed; pass --continue-on-error to tolerate optional errors: {exc}"
        ) from exc
    console.print(f"[yellow]Warning: {phase} failed: {exc}[/]")


def ensure_scheduler_bootstrapped() -> None:
    """Bootstrap plugin scheduler on the main thread before parallel parse."""
    from repograph.plugins.lifecycle import get_hook_scheduler

    get_hook_scheduler()


def close_store_quietly(store: Any | None) -> None:
    """Close a GraphStore-like object without turning cleanup into the root error."""
    if store is None:
        return
    try:
        store.close()
    except Exception as close_exc:
        logger.warning("store.close() failed during cleanup", exc_msg=str(close_exc))

