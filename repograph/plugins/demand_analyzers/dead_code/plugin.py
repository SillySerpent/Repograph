from __future__ import annotations

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest


# NOTE: canonical definition — demand-side wrapper that delegates to RepoGraphService.dead_code().
# Distinct from static_analyzers/dead_code/plugin.py::DeadCodeAnalyzerPlugin (StaticAnalyzerPlugin,
# fires on_graph_built and performs the actual detection logic).
class DeadCodeDemandPlugin(DemandAnalyzerPlugin):
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
            raise ValueError("DeadCodeDemandPlugin requires service=")
        return service.dead_code(min_tier=min_tier)


def build_plugin() -> DeadCodeDemandPlugin:
    return DeadCodeDemandPlugin()
