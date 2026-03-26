"""Pathways plugin package.

Canonical home of pathway scoring, traversal, curation, assembly, and
description generation.
"""

from .plugin import build_plugin, PathwayBuilderPlugin

__all__ = ["build_plugin", "PathwayBuilderPlugin"]
