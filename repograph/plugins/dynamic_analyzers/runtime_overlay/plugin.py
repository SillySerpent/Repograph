"""Runtime overlay dynamic analyzer plugin.

Consumes JSONL call traces produced by any jsonl_call_trace tracer and
overlays their findings onto the static graph.

Plugin contract
---------------
  kind:          dynamic_analyzer
  hook:          on_traces_collected
  trace_formats: jsonl_call_trace
  input:         trace_dir (Path), store (GraphStore)
  output:        list[dict] findings

Example
-------
    # After running: pytest --repograph-trace
    # Then: repograph sync
    # → on_traces_collected fires → this plugin runs → findings merged
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from repograph.core.plugin_framework import DynamicAnalyzerPlugin, PluginManifest
from repograph.runtime.overlay import overlay_traces, persist_runtime_overlay_to_store
from repograph.runtime.trace_format import TRACE_FORMAT
from repograph.utils import logging as rg_log


class RuntimeOverlayDynamicPlugin(DynamicAnalyzerPlugin):
    """Overlays JSONL call traces onto the static call graph.

    Detects:
    - Functions marked dead statically but observed live at runtime
    - Dynamic call edges not visible to static analysis
    - Most-called functions (useful for performance hotspot hints)
    """

    manifest = PluginManifest(
        id="dynamic_analyzer.runtime_overlay",
        name="Runtime overlay analyzer",
        kind="dynamic_analyzer",
        description=(
            "Consumes JSONL call traces and overlays observed-live "
            "and dynamic-edge findings onto the static graph."
        ),
        requires=("static_graph",),
        produces=("findings.dynamic_overlay", "findings.observed_live"),
        hooks=("on_traces_collected",),
        trace_formats=(TRACE_FORMAT,),
    )

    def analyze_traces(
        self,
        trace_dir: Path,
        store: Any,
        **kwargs: Any,
    ) -> list[dict]:
        """Consume traces and return structured findings."""
        repo_root = kwargs.get("repo_root", "")
        report = overlay_traces(trace_dir, store, repo_root=repo_root)
        n_persisted = persist_runtime_overlay_to_store(store, report)
        if n_persisted:
            rg_log.success(
                f"Runtime observations merged into graph: {n_persisted} function(s) "
                f"(runtime_observed + dead flags cleared where applicable)"
            )
        return report.get("findings", [])

    def full_report(
        self,
        trace_dir: Path,
        store: Any,
        repo_root: str = "",
    ) -> dict:
        """Return the complete overlay report (not just findings).

        Called by the CLI ``repograph dynamic report`` command and by
        RepoGraphService.runtime_overlay_report().
        """
        return overlay_traces(trace_dir, store, repo_root=repo_root)


def build_plugin() -> RuntimeOverlayDynamicPlugin:
    return RuntimeOverlayDynamicPlugin()
