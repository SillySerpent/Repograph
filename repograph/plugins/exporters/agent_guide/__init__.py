"""Agent-guide exporter package.

Canonical home of agent-guide generation logic.
"""

from .plugin import build_plugin, AgentGuideExporterPlugin

__all__ = ["build_plugin", "AgentGuideExporterPlugin"]
