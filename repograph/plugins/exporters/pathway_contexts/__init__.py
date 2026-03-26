"""Pathway-context exporter package.

Canonical home of context budgeting, formatting, and generation logic.
"""

from .plugin import build_plugin, PathwayContextsExporterPlugin

__all__ = ["build_plugin", "PathwayContextsExporterPlugin"]
