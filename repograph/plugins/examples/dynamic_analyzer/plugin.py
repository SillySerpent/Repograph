"""REFERENCE ONLY — not registered in production.

How to implement a dynamic analyzer plugin
------------------------------------------
1. Subclass ``DynamicAnalyzerPlugin``.
2. Set ``kind="dynamic_analyzer"``, ``hooks=("on_traces_collected",)``.
3. Set ``manifest.trace_formats`` to tokens that match trace files in
   ``.repograph/runtime/``.
4. Implement ``analyze_traces(trace_dir, store, **kwargs)`` — return finding dicts.
5. Register: append to ``DYNAMIC_ANALYZER_ORDER`` in ``discovery.py``.

Pair with a ``TracerPlugin`` whose ``manifest.trace_format`` appears in your
``trace_formats`` so the overlay pipeline lines up.

See ``plugins/dynamic_analyzers/runtime_overlay/plugin.py``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from repograph.core.plugin_framework import DynamicAnalyzerPlugin, PluginManifest


class ExampleDynamicAnalyzerPlugin(DynamicAnalyzerPlugin):
    manifest = PluginManifest(
        id="dynamic_analyzer.example_reference",
        name="Example dynamic analyzer (reference)",
        kind="dynamic_analyzer",
        description="Reference stub — not used in production.",
        requires=("symbols",),
        produces=("findings.example_runtime",),
        hooks=("on_traces_collected",),
        trace_formats=("example_trace",),
    )

    def analyze_traces(self, trace_dir: Path, store: Any, **kwargs: Any) -> list[dict]:
        return []


def build_plugin() -> ExampleDynamicAnalyzerPlugin:
    return ExampleDynamicAnalyzerPlugin()
