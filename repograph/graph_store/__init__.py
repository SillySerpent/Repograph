"""Graph store public surface.

Import :class:`~repograph.graph_store.store.GraphStore` for all database
operations. The component mixin classes are internal implementation details
and should not be imported directly by callers outside this package.
"""
from __future__ import annotations

from repograph.graph_store.store import GraphStore

__all__ = ["GraphStore"]
