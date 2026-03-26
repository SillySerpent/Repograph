from __future__ import annotations

from repograph.core.plugin_framework import ExporterPlugin, PluginManifest
from repograph.graph_store.store import GraphStore
from .generator import generate_agent_guide


class AgentGuideExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.agent_guide",
        name="Agent guide exporter",
        kind="exporter",
        description="Writes AGENT_GUIDE.md from indexed repo knowledge and pathway context.",
        requires=("artifacts.pathway_contexts",),
        produces=("artifacts.agent_guide",),
        hooks=("on_export",),
        order=240,
        after=("exporter.pathway_contexts", "exporter.modules", "exporter.invariants"),
    )

    def export(self, store: GraphStore | None = None, repograph_dir: str = "", config=None, **kwargs):
        if store is None or not repograph_dir:
            return {"kind": "agent_guide", "path": ""}
        repo_root = getattr(config, "repo_root", "") if config is not None else ""
        text = generate_agent_guide(store, repo_root, repograph_dir)
        return {"kind": "agent_guide", "path": f"{repograph_dir}/AGENT_GUIDE.md", "length": len(text)}


def build_plugin() -> AgentGuideExporterPlugin:
    return AgentGuideExporterPlugin()
