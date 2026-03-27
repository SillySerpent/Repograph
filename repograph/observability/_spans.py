"""Span-based instrumentation for tracing meaningful operations.

Use spans to bracket important work units — pipeline phases, plugin dispatches,
store operations, file parses.  Do **not** apply spans to every trivial function;
instrument only operations that are meaningful to trace and diagnose.

Usage as a context manager::

    from repograph.observability import span

    with span("parse_file", path=str(file_path), subsystem="parsers") as s:
        result = parser.parse(file_path)
        s.add_metadata(function_count=len(result.functions))

Usage as a decorator::

    from repograph.observability import span

    @span("upsert_function", subsystem="graph_store")
    def upsert_function(self, fn: FunctionNode) -> None:
        ...

Spans automatically:
- Generate a unique ``span_id`` and set it on the current context
- Log ``operation_start`` on entry (DEBUG)
- Log ``operation_end`` on success with ``duration_ms`` (DEBUG)
- Log ``operation_failed`` on exception with full traceback (ERROR)
- Restore the parent ``span_id`` on exit (nesting support)
"""
from __future__ import annotations

import functools
import time
import traceback as _traceback
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Generator, TypeVar

from repograph.observability._context import get_context_var, set_obs_context
from repograph.observability._logger import get_logger

F = TypeVar("F", bound=Callable[..., Any])

_span_logger = get_logger("repograph.observability.spans", subsystem="observability")


class SpanContext:
    """Mutable metadata carrier for an active span.

    Returned by the ``span()`` context manager; call :meth:`add_metadata` to
    attach extra fields that will appear in the ``operation_end`` record.
    """

    __slots__ = ("_meta",)

    def __init__(self) -> None:
        self._meta: dict[str, Any] = {}

    def add_metadata(self, **kwargs: Any) -> None:
        """Attach additional metadata to this span's end record."""
        self._meta.update(kwargs)


@contextmanager
def span(
    operation: str,
    *,
    subsystem: str | None = None,
    **metadata: Any,
) -> Generator[SpanContext, None, None]:
    """Context manager that traces an operation with start/end/failure records.

    Args:
        operation: Short name for this operation, e.g. ``"parse_file"``.
        subsystem: Override the subsystem label for this span's records.
        **metadata: Additional metadata included in start/end records.

    Yields:
        :class:`SpanContext` — call ``.add_metadata()`` to attach result data.
    """
    span_id = uuid.uuid4().hex[:12]
    parent_span_id = get_context_var("span_id")
    set_obs_context(span_id=span_id)
    if subsystem:
        set_obs_context(subsystem=subsystem)

    ctx = SpanContext()
    _span_logger.debug(
        f"[span] {operation} start",
        operation=operation,
        **metadata,
    )
    t0 = time.perf_counter()
    try:
        yield ctx
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        _span_logger.debug(
            f"[span] {operation} end",
            operation=operation,
            duration_ms=duration_ms,
            **{**metadata, **ctx._meta},
        )
    except Exception as exc:
        # Capture exception details here in the except block — sys.exc_info()
        # is not reliably available from nested function calls inside a
        # @contextmanager generator's except clause, so we extract explicitly.
        duration_ms = round((time.perf_counter() - t0) * 1000, 2)
        exc_tb_str = "".join(_traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
        _span_logger.error(
            f"[span] {operation} failed: {type(exc).__name__}: {exc}",
            operation=operation,
            duration_ms=duration_ms,
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
            exc_tb=exc_tb_str,
            **metadata,
        )
        raise
    finally:
        # Restore parent span_id (or clear if no parent)
        set_obs_context(span_id=parent_span_id or "")
        if subsystem:
            # Clear the subsystem override — caller's subsystem was set before
            # this span; we don't restore it because set_obs_context uses
            # ContextVar which is copy-on-write — the parent frame's value is
            # unaffected in Python's ContextVar model for the same thread.
            pass


def span_decorator(
    operation: str,
    *,
    subsystem: str | None = None,
    **metadata: Any,
) -> Callable[[F], F]:
    """Decorator form of :func:`span`.

    The decorated function's positional and keyword arguments are not
    automatically added to the span metadata to avoid leaking sensitive data.
    Pass static ``metadata`` kwargs to the decorator itself for labelling.

    Usage::

        @span_decorator("upsert_function", subsystem="graph_store")
        def upsert_function(self, fn: FunctionNode) -> None:
            ...
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(operation, subsystem=subsystem, **metadata):
                return fn(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator
