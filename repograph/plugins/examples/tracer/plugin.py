"""REFERENCE ONLY — not registered in production.

How to implement a tracer plugin
--------------------------------
1. Subclass ``TracerPlugin``.
2. Set ``kind="tracer"``, ``hooks=("on_tracer_install", "on_tracer_collect")``.
3. Set ``manifest.trace_format`` to a single token; dynamic analyzers list the same
   token in ``trace_formats`` to consume output.
4. ``install(repo_root, trace_dir, **kwargs)`` — write instrumentation config; return
   metadata dict.
5. ``collect(trace_dir, **kwargs)`` — return ``list[Path]`` of trace files produced.
6. Register via ``register_tracer`` in ``tracers/_registry.py`` (built-ins are
   explicit here because one tracer ships from ``dynamic_analyzers/coverage_tracer``).

See ``plugins/dynamic_analyzers/coverage_tracer/plugin.py``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from repograph.core.plugin_framework import PluginManifest, TracerPlugin


class ExampleTracerPlugin(TracerPlugin):
    manifest = PluginManifest(
        id="tracer.example_reference",
        name="Example tracer (reference)",
        kind="tracer",
        description="Reference stub — not used in production.",
        hooks=("on_tracer_install", "on_tracer_collect"),
        trace_format="example_trace",
    )

    def install(self, repo_root: Path, trace_dir: Path, **kwargs: Any) -> dict:
        return {"format": self.manifest.trace_format, "repo_root": str(repo_root)}

    def collect(self, trace_dir: Path, **kwargs: Any) -> list[Path]:
        return []


def build_plugin() -> ExampleTracerPlugin:
    return ExampleTracerPlugin()
