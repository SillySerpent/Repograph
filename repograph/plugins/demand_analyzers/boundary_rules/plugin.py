from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest


class BoundaryRulesAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.boundary_rules",
        name="Boundary rules analyzer",
        kind="demand_analyzer",
        description="Demand-side analyzer that aggregates contract-rule and boundary-shortcut plugin families.",
        requires=("repo_files",),
        produces=("findings.boundary_rules",),
        hooks=("on_analysis",),
        aliases=("analyzer.boundary_rules",),
    )

    def analyze(self, **kwargs: Any):
        service = kwargs.get("service")
        if service is None:
            return []
        contract = service.run_analyzer_plugin("demand_analyzer.contract_rules")
        shortcuts = service.run_analyzer_plugin("demand_analyzer.boundary_shortcuts")
        return [*contract, *shortcuts]


def build_plugin() -> BoundaryRulesAnalyzerPlugin:
    return BoundaryRulesAnalyzerPlugin()
