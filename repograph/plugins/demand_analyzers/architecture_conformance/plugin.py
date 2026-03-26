from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest


class ArchitectureConformanceAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.architecture_conformance",
        name="Architecture conformance analyzer",
        kind="demand_analyzer",
        description="Aggregates contract and boundary rule families into the Meridian-facing conformance surface.",
        requires=("repo_files",),
        produces=("findings.architecture_conformance",),
        hooks=("on_analysis",),
        aliases=("analyzer.architecture_conformance",),
    )

    def analyze(self, **kwargs: Any):
        service = kwargs.get("service")
        if service is None:
            return []
        contract = service.run_analyzer_plugin("demand_analyzer.contract_rules")
        shortcuts = service.run_analyzer_plugin("demand_analyzer.boundary_shortcuts")
        return [*contract, *shortcuts]


def build_plugin() -> ArchitectureConformanceAnalyzerPlugin:
    return ArchitectureConformanceAnalyzerPlugin()
