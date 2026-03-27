"""ObservableMixin — optional logger/span access for long-lived service objects.

**Usage is intentionally restricted.**  Only attach this mixin to classes that:
- Are long-lived (persist across multiple operations)
- Manage significant state (e.g. database connections, service state)
- Benefit from a stable ``self.logger`` and ``self.span()`` binding

Do **not** use this mixin for:
- Short-lived helpers, utilities, or value objects
- Plugin implementations (use ``get_logger(__name__)`` directly)
- Pipeline phases (use module-level loggers)

Appropriate users in this codebase:
- ``GraphStore`` and its mixin bases
- ``RepoGraphService``

All other code should use the module-level pattern::

    from repograph.observability import get_logger, span
    logger = get_logger(__name__)
"""
from __future__ import annotations

from typing import Any, Generator

from repograph.observability._context import set_obs_context
from repograph.observability._logger import StructuredLogger, get_logger
from repograph.observability._spans import span as _span_cm, SpanContext


class ObservableMixin:
    """Provides ``self.logger`` and ``self.span()`` to long-lived service objects.

    The ``subsystem`` class attribute controls the subsystem label for all
    log records emitted through this mixin.  Override in subclasses::

        class GraphStore(ObservableMixin, ...):
            _obs_subsystem = "graph_store"
    """

    _obs_subsystem: str = ""  # Override in subclass; inferred from class name if empty

    @property
    def logger(self) -> StructuredLogger:
        """Return the structured logger for this instance (created lazily)."""
        attr = "_obs_logger"
        lg: StructuredLogger | None = self.__dict__.get(attr)
        if lg is None:
            name = f"{type(self).__module__}.{type(self).__name__}"
            sub = self._obs_subsystem or None
            lg = get_logger(name, subsystem=sub)
            object.__setattr__(self, attr, lg)
        return lg

    def span(self, operation: str, **metadata: Any) -> Any:
        """Return a context manager tracing the given operation.

        Usage::

            with self.span("close_connection", db_path=self._db_path):
                self._conn.close()
        """
        sub = self._obs_subsystem or None
        return _span_cm(operation, subsystem=sub, **metadata)
