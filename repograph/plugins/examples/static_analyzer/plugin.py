"""REFERENCE ONLY — not registered in production.

How to implement a static analyzer plugin
-----------------------------------------
1. Subclass ``StaticAnalyzerPlugin``.
2. Set ``kind="static_analyzer"``, ``hooks=("on_graph_built",)``.
3. Declare ``requires`` / ``produces`` capability tokens (see existing analyzers).
4. Implement ``analyze(**kwargs)`` — typically ``store`` is a ``GraphStore``. Return
   a list of finding dicts with at least ``kind`` and ``severity``.
5. Use ``manifest.after`` / ``before`` / ``order`` to order relative to other analyzers.
6. Register: append to ``STATIC_ANALYZER_ORDER`` in ``discovery.py`` and add tests.

See ``plugins/static_analyzers/dead_code/plugin.py``.
"""
from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import PluginManifest, StaticAnalyzerPlugin


class ExampleStaticAnalyzerPlugin(StaticAnalyzerPlugin):
    manifest = PluginManifest(
        id="static_analyzer.example_reference",
        name="Example static analyzer (reference)",
        kind="static_analyzer",
        description="Reference stub — not used in production.",
        requires=("symbols",),
        produces=("findings.example",),
        hooks=("on_graph_built",),
        order=9999,
    )

    def analyze(self, **kwargs: Any) -> list[dict]:
        return []


def build_plugin() -> ExampleStaticAnalyzerPlugin:
    return ExampleStaticAnalyzerPlugin()
