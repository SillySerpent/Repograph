"""REFERENCE ONLY — not registered in production.

How to implement a demand analyzer plugin
-----------------------------------------
1. Subclass ``DemandAnalyzerPlugin`` (alias ``AnalyzerPlugin``).
2. Set ``kind="demand_analyzer"``, ``id="demand_analyzer.<name>"``, ``hooks=("on_analysis",)``.
3. ``analyze`` is invoked from service/API paths with ``service`` or similar kwargs.
4. Register: append to ``DEMAND_ANALYZER_ORDER`` in ``discovery.py``.

See ``plugins/demand_analyzers/duplicates/plugin.py``.
"""
from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest


class ExampleDemandAnalyzerPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.example_reference",
        name="Example demand analyzer (reference)",
        kind="demand_analyzer",
        description="Reference stub — not used in production.",
        requires=("symbols",),
        produces=("findings.example",),
        hooks=("on_analysis",),
    )

    def analyze(self, **kwargs: Any) -> list[dict]:
        return []


def build_plugin() -> ExampleDemandAnalyzerPlugin:
    return ExampleDemandAnalyzerPlugin()
