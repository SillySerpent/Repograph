"""Runtime quality dynamic analyzer.

Produces diagnostics about trace resolution quality and volume characteristics.
This complements runtime_overlay persistence without mutating graph state.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from repograph.core.plugin_framework import DynamicAnalyzerPlugin, PluginManifest
from repograph.runtime.overlay import overlay_traces
from repograph.runtime.trace_format import TRACE_FORMAT


class RuntimeQualityDynamicPlugin(DynamicAnalyzerPlugin):
    manifest = PluginManifest(
        id="dynamic_analyzer.runtime_quality",
        name="Runtime quality analyzer",
        kind="dynamic_analyzer",
        description="Reports runtime trace resolution quality and unresolved symbol rates.",
        requires=("static_graph",),
        produces=("findings.runtime_quality",),
        hooks=("on_traces_collected",),
        trace_formats=(TRACE_FORMAT,),
    )

    def analyze_traces(
        self,
        trace_dir: Path,
        store: Any,
        **kwargs: Any,
    ) -> list[dict]:
        repo_root = kwargs.get("repo_root", "")
        report = overlay_traces(trace_dir, store, repo_root=repo_root)
        total = int(report.get("trace_call_records") or 0)
        unresolved = int(report.get("unresolved_trace_calls") or 0)
        resolved = int(report.get("resolved_trace_calls") or 0)
        unresolved_pct = (float(unresolved) / float(total)) if total > 0 else 0.0
        findings: list[dict] = []
        if unresolved_pct >= 0.20 and total >= 100:
            findings.append(
                {
                    "kind": "runtime_resolution_low",
                    "severity": "medium",
                    "description": (
                        "High unresolved runtime call ratio; dynamic traces may not map cleanly "
                        "to graph functions."
                    ),
                    "trace_call_records": total,
                    "resolved_trace_calls": resolved,
                    "unresolved_trace_calls": unresolved,
                    "unresolved_ratio": round(unresolved_pct, 4),
                    "examples": list(report.get("unresolved_examples") or [])[:10],
                }
            )
        return findings


def build_plugin() -> RuntimeQualityDynamicPlugin:
    return RuntimeQualityDynamicPlugin()
