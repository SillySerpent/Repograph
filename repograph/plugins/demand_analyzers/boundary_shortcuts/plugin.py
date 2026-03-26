from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest
from repograph.plugins.rules import get_rule_pack_config

class BoundaryShortcutsAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.boundary_shortcuts",
        name="Boundary shortcuts analyzer",
        kind="demand_analyzer",
        description="Aggregates likely cross-layer shortcut rule packs such as UI/API directly reaching DB or domain layers.",
        requires=("repo_files",),
        produces=("findings.boundary_shortcuts",),
        hooks=("on_analysis",),
        aliases=("analyzer.boundary_shortcuts",),
    )

    def analyze(self, **kwargs: Any):
        service = kwargs.get("service")
        if service is None:
            return []
        cfg = get_rule_pack_config(service)
        findings = []
        for plugin_id in cfg.enabled_for_family("boundary_shortcuts"):
            findings.extend(service.run_analyzer_plugin(f"demand_analyzer.{plugin_id}"))
        return findings

def build_plugin() -> BoundaryShortcutsAnalyzerPlugin:
    return BoundaryShortcutsAnalyzerPlugin()
