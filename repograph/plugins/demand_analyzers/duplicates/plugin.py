from __future__ import annotations

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest


class DuplicateAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.duplicates",
        name="Duplicate analyzer",
        kind="demand_analyzer",
        description="Demand-side analyzer for duplicate symbol findings.",
        requires=("symbols",),
        produces=("findings.duplicates",),
        hooks=("on_analysis",),
        aliases=("analyzer.duplicates",),
    )

    def analyze(self, **kwargs):
        service = kwargs.get("service")
        min_severity = kwargs.get("min_severity", "medium")
        if service is None:
            raise ValueError("DuplicateAnalyzerPlugin requires service=")
        return service.duplicates(min_severity=min_severity)


def build_plugin() -> DuplicateAnalyzerPlugin:
    return DuplicateAnalyzerPlugin()
