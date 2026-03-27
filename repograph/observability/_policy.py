"""No-silent-failure policy helpers.

These are the canonical replacements for every ``except Exception: pass``
pattern in the codebase.  They ensure that degraded/partial paths are always
visible in the structured log, even when execution is allowed to continue.

**Rules:**

- ``log_degraded`` — execution continues in a known-partial state.  Use for
  expected failure modes that are handled gracefully (e.g. a missing node
  during relationship insertion, an importer file that no longer exists).
  Emits at WARNING.

- ``log_swallowed`` — an unexpected exception was caught for robustness, but
  should be highly visible.  Emits at ERROR.  Use sparingly — if an exception
  can happen, handle it properly; only swallow when truly necessary.

Neither helper re-raises the exception — that is the caller's responsibility
if re-raise is appropriate.

Usage::

    from repograph.observability import log_degraded, log_swallowed

    try:
        store.insert_edge(...)
    except KuzuMissingNodeError as exc:
        log_degraded(
            logger, "missing node during edge insert — skipping",
            exc=exc,
            partial_result="edge skipped",
            from_id=edge.from_id,
            to_id=edge.to_id,
        )
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from repograph.observability._logger import StructuredLogger


def log_degraded(
    logger: "StructuredLogger",
    msg: str,
    *,
    exc: Exception | None = None,
    partial_result: str | None = None,
    **context: Any,
) -> None:
    """Log a WARNING indicating degraded/partial execution.

    Args:
        logger:         The calling module's :class:`StructuredLogger`.
        msg:            Human-readable description of what was degraded.
        exc:            The caught exception, if any (included in record).
        partial_result: Description of what partial work was done/returned.
        **context:      Additional key-value context fields for the record.
    """
    kwargs: dict[str, Any] = {
        "degraded": True,
        "partial_result": partial_result,
        **context,
    }
    if exc is not None:
        # Include exception type and message without a full traceback for
        # degraded paths (expected failures).  Use log_swallowed for
        # unexpected exceptions where the traceback is valuable.
        kwargs["exc_type"] = type(exc).__name__
        kwargs["exc_msg"] = str(exc)
    logger.warning(msg, **kwargs)


def log_swallowed(
    logger: "StructuredLogger",
    msg: str,
    exc: Exception,
    **context: Any,
) -> None:
    """Log an ERROR for an unexpected exception that was caught for robustness.

    This emits at ERROR level with a full traceback in the JSONL record.
    The record will appear in both ``all.jsonl`` and ``errors.jsonl``.

    Args:
        logger:  The calling module's :class:`StructuredLogger`.
        msg:     Human-readable description of what was swallowed.
        exc:     The caught exception (traceback included automatically).
        **context: Additional key-value context fields.
    """
    kwargs: dict[str, Any] = {
        "degraded": True,
        "_exc_info": True,
        **context,
    }
    logger.error(f"{msg}: {type(exc).__name__}: {exc}", **kwargs)
