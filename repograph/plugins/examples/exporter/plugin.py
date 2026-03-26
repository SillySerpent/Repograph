"""REFERENCE ONLY — not registered in production.

How to implement an exporter plugin
-----------------------------------
1. Subclass ``ExporterPlugin``.
2. Set ``kind="exporter"``, ``hooks=("on_export",)``.
3. Implement ``export(store=..., repograph_dir=..., config=..., **kwargs)`` and write
   artefacts under ``repograph_dir`` (often ``meta/``). Return a small summary dict.
4. Register: append to ``EXPORTER_ORDER`` in ``discovery.py`` (order can matter for UX).

See ``plugins/exporters/summary/plugin.py``.
"""
from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import ExporterPlugin, PluginManifest


class ExampleExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.example_reference",
        name="Example exporter (reference)",
        kind="exporter",
        description="Reference stub — not used in production.",
        requires=("symbols",),
        produces=("artifacts.example",),
        hooks=("on_export",),
        order=9999,
    )

    def export(self, store: Any = None, repograph_dir: str = "", **kwargs: Any) -> dict[str, Any]:
        return {"kind": "example", "path": "", "written": 0}


def build_plugin() -> ExampleExporterPlugin:
    return ExampleExporterPlugin()
