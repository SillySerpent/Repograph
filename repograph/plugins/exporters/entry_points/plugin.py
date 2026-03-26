from __future__ import annotations

from typing import Any

from repograph.core.evidence import CAP_ENTRY_POINTS, SOURCE_STATIC, evidence_tag
from repograph.core.plugin_framework import ExporterPlugin, PluginManifest


class EntryPointsExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.entry_points",
        name="Entry points exporter",
        kind="exporter",
        description="Compatibility exporter wrapper for entry-point ranking results.",
        requires=(CAP_ENTRY_POINTS,),
        produces=(evidence_tag(CAP_ENTRY_POINTS, SOURCE_STATIC).kind,),
        hooks=("on_export",),
        order=160,
    )

    def export(self, **kwargs: Any) -> dict[str, Any]:
        service = kwargs.get("service")
        limit = kwargs.get("limit", 20)
        if service is not None:
            out = service.entry_points(limit=limit)
            return out if isinstance(out, dict) else {"data": out}
        store = kwargs.get("store")
        if store is None:
            return {"data": []}
        return {"data": store.get_entry_points(limit=limit)}


def build_plugin() -> EntryPointsExporterPlugin:
    return EntryPointsExporterPlugin()
