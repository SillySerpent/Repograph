from __future__ import annotations

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest


class DeadCodeAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.dead_code",
        name="Dead code analyzer",
        kind="demand_analyzer",
        description="Demand-side analyzer for dead-code findings.",
        requires=("call_edges", "symbols"),
        produces=("findings.dead_code",),
        hooks=("on_analysis",),
        aliases=("analyzer.dead_code",),
    )

    def analyze(self, **kwargs):
        service = kwargs.get("service")
        min_tier = kwargs.get("min_tier", "possibly_dead")
        if service is None:
            raise ValueError("DeadCodeAnalyzerPlugin requires service=")
        return service.dead_code(min_tier=min_tier)


def build_plugin() -> DeadCodeAnalyzerPlugin:
    return DeadCodeAnalyzerPlugin()
