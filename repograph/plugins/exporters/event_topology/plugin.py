from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import ExporterPlugin, PluginManifest
from repograph.plugins.utils import read_meta_json


class EventTopologyExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.event_topology",
        name="Event topology exporter",
        kind="exporter",
        description="Compatibility exporter wrapper for event topology metadata.",
        requires=("meta.event_topology",),
        produces=("artifacts.event_topology_json",),
        hooks=("on_export",),
        order=140,
    )

    def export(self, **kwargs: Any) -> dict[str, Any]:
        service = kwargs.get("service")
        if service is not None:
            out = service.event_topology()
            return out if isinstance(out, dict) else {"data": out}
        repograph_dir = kwargs.get("repograph_dir") or ""
        if not repograph_dir:
            return {"data": []}
        raw = read_meta_json(repograph_dir, "event_topology.json", [])
        return raw if isinstance(raw, dict) else {"data": raw}


def build_plugin() -> EventTopologyExporterPlugin:
    return EventTopologyExporterPlugin()
