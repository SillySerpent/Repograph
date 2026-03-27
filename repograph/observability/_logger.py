"""StructuredLogger factory and JSONL logging handler.

This module bridges Python's stdlib :mod:`logging` with RepoGraph's structured
observability layer.  It does **not** replace or interfere with the Rich-based
console output in ``repograph.utils.logging``.

Usage::

    from repograph.observability import get_logger

    logger = get_logger(__name__)           # module-level, cheap
    logger.info("phase started", phase="p04", file_count=42)
    logger.warning("resolution degraded", degraded=True, exc=exc)

Subsystem inference
-------------------
The subsystem is derived from the module name automatically:

    repograph.pipeline.*     → pipeline
    repograph.plugins.*      → plugins
    repograph.graph_store.*  → graph_store
    (etc.)

You can override with ``get_logger(__name__, subsystem="custom")``.
"""
from __future__ import annotations

import datetime
import logging
import sys
import traceback
from typing import Any

from repograph.observability._context import get_obs_context
from repograph.observability._sinks import route_record

# ---------------------------------------------------------------------------
# Subsystem inference
# ---------------------------------------------------------------------------

_SUBSYSTEM_MAP: list[tuple[str, str]] = [
    ("repograph.pipeline", "pipeline"),
    ("repograph.plugins.parsers", "parsers"),
    ("repograph.plugins", "plugins"),
    ("repograph.graph_store", "graph_store"),
    ("repograph.runtime", "runtime"),
    ("repograph.services", "services"),
    ("repograph.interactive", "cli"),
    ("repograph.mcp", "mcp"),
    ("repograph.diagnostics", "setup"),
    ("repograph.config", "config"),
    ("repograph.observability", "observability"),
]


def _infer_subsystem(module_name: str) -> str:
    for prefix, subsystem in _SUBSYSTEM_MAP:
        if module_name.startswith(prefix):
            return subsystem
    return "core"


# ---------------------------------------------------------------------------
# JSONL handler
# ---------------------------------------------------------------------------


class _JsonlHandler(logging.Handler):
    """Logging handler that serialises records to JSONL and routes to sinks."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ctx = get_obs_context()
            exc_type = exc_msg = exc_tb = None
            if record.exc_info and record.exc_info[0] is not None:
                exc_type = record.exc_info[0].__name__
                exc_msg = str(record.exc_info[1])
                exc_tb = "".join(traceback.format_exception(*record.exc_info)).strip()

            # Extra fields attached by StructuredLogger.log()
            extra: dict[str, Any] = getattr(record, "_obs_extra", {})

            entry: dict[str, Any] = {
                "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "level": record.levelname,
                "level_no": record.levelno,
                "msg": record.getMessage(),
                "subsystem": extra.pop("subsystem", None) or ctx.get("subsystem") or _infer_subsystem(record.name),
                "component": record.name,
                "operation": extra.pop("operation", None),
                "run_id": ctx.get("run_id"),
                "command_id": ctx.get("command_id"),
                "span_id": ctx.get("span_id"),
                "phase": extra.pop("phase", None) or ctx.get("phase"),
                "plugin_id": extra.pop("plugin_id", None) or ctx.get("plugin_id"),
                "hook": extra.pop("hook", None) or ctx.get("hook"),
                "duration_ms": extra.pop("duration_ms", None),
                "path": extra.pop("path", None),
                "symbol": extra.pop("symbol", None),
                "exc_type": exc_type,
                "exc_msg": exc_msg,
                "exc_tb": exc_tb,
                "degraded": extra.pop("degraded", None),
                "partial_result": extra.pop("partial_result", None),
            }
            # Merge any remaining extra fields
            entry.update(extra)
            route_record(entry)
        except Exception:  # noqa: BLE001 — handler must never raise
            self.handleError(record)


# ---------------------------------------------------------------------------
# StructuredLogger
# ---------------------------------------------------------------------------


class StructuredLogger:
    """Thin wrapper around a stdlib logger that supports keyword-extra enrichment.

    All keyword arguments passed to ``info()``, ``warning()``, etc. are added
    to the JSONL record alongside the structured context.  They do **not**
    appear in the Rich console output (which only shows the message string).

    This class is intentionally lightweight — it delegates to stdlib logging
    for level filtering, handler dispatch, and propagation.
    """

    __slots__ = ("_logger", "_subsystem")

    def __init__(self, name: str, subsystem: str | None = None) -> None:
        self._logger = logging.getLogger(name)
        self._subsystem = subsystem or _infer_subsystem(name)

    # ------------------------------------------------------------------
    # Core log methods
    # ------------------------------------------------------------------

    def debug(self, msg: str, **extra: Any) -> None:
        self._log(logging.DEBUG, msg, extra)

    def info(self, msg: str, **extra: Any) -> None:
        self._log(logging.INFO, msg, extra)

    def warning(self, msg: str, **extra: Any) -> None:
        self._log(logging.WARNING, msg, extra)

    # alias
    warn = warning

    def error(self, msg: str, **extra: Any) -> None:
        self._log(logging.ERROR, msg, extra)

    def critical(self, msg: str, **extra: Any) -> None:
        self._log(logging.CRITICAL, msg, extra)

    def exception(self, msg: str, **extra: Any) -> None:
        """Log at ERROR with current exception info."""
        extra["_exc_info"] = True
        self._log(logging.ERROR, msg, extra)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _log(self, level: int, msg: str, extra: dict[str, Any]) -> None:
        if not self._logger.isEnabledFor(level):
            return
        exc_info = extra.pop("_exc_info", False)
        extra["subsystem"] = self._subsystem
        record = self._logger.makeRecord(
            self._logger.name,
            level,
            "(unknown)",
            0,
            msg,
            (),
            sys.exc_info() if exc_info else None,
        )
        record._obs_extra = extra  # type: ignore[attr-defined]
        self._logger.handle(record)

    @property
    def name(self) -> str:
        return self._logger.name

    def isEnabledFor(self, level: int) -> bool:
        return self._logger.isEnabledFor(level)


# ---------------------------------------------------------------------------
# Handler registration (called once by init_observability)
# ---------------------------------------------------------------------------

_jsonl_handler: _JsonlHandler | None = None


def install_jsonl_handler(min_level: str = "DEBUG") -> None:
    """Attach the JSONL handler to the root ``repograph`` logger (idempotent)."""
    global _jsonl_handler
    if _jsonl_handler is not None:
        return
    handler = _JsonlHandler()
    handler.setLevel(getattr(logging, min_level.upper(), logging.DEBUG))
    rg_root = logging.getLogger("repograph")
    rg_root.addHandler(handler)
    if not rg_root.level or rg_root.level > logging.DEBUG:
        rg_root.setLevel(logging.DEBUG)
    _jsonl_handler = handler


def remove_jsonl_handler() -> None:
    """Remove the JSONL handler (called on shutdown)."""
    global _jsonl_handler
    if _jsonl_handler is None:
        return
    rg_root = logging.getLogger("repograph")
    rg_root.removeHandler(_jsonl_handler)
    _jsonl_handler = None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_logger(name: str, subsystem: str | None = None) -> StructuredLogger:
    """Return a :class:`StructuredLogger` for the given module name.

    Safe to call before :func:`init_observability` — logging will still route
    through stdlib (and any console handlers already attached), but will not
    write JSONL files until the sink is active.

    Args:
        name:      Typically ``__name__`` of the calling module.
        subsystem: Override the inferred subsystem label.
    """
    return StructuredLogger(name, subsystem=subsystem)
