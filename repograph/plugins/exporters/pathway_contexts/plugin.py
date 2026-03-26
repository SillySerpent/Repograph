from __future__ import annotations

from .generator import generate_all_pathway_contexts
from repograph.core.plugin_framework import ExporterPlugin, PluginManifest
from repograph.graph_store.store import GraphStore


class PathwayContextsExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.pathway_contexts",
        name="Pathway context exporter",
        kind="exporter",
        description="Generates context docs for all assembled pathways.",
        requires=("graph.pathways",),
        produces=("artifacts.pathway_contexts",),
        hooks=("on_export",),
        order=230,
        after=("exporter.pathways",),
    )

    def export(self, store: GraphStore | None = None, config=None, **kwargs):
        if store is None:
            service = kwargs.get("service")
            if service is None:
                return {"kind": "pathway_contexts", "count": 0}
            return {"kind": "pathway_contexts", "count": len(service.pathways())}
        max_tokens = getattr(config, "max_context_tokens", 2000) if config is not None else 2000
        count = generate_all_pathway_contexts(store, max_tokens=max_tokens)
        return {"kind": "pathway_contexts", "count": count}


def build_plugin() -> PathwayContextsExporterPlugin:
    return PathwayContextsExporterPlugin()
