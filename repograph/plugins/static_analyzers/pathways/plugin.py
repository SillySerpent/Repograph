"""Pathway builder static analyzer.

Pathway construction used to live as a hardcoded runner helper. Moving it here
makes pathway assembly part of the plugin-owned post-build graph enrichment
layer.
"""
from __future__ import annotations

from repograph.core.plugin_framework import PluginManifest, StaticAnalyzerPlugin
from repograph.graph_store.store import GraphStore
from repograph.utils import logging as rg_log
from .assembler import PathwayAssembler
from .curator import PathwayCurator


def run_pathway_build(store: GraphStore, repo_root: str) -> list[dict]:
    store.clear_pathways()
    curator = PathwayCurator(repo_root)
    assembler = PathwayAssembler(store)
    used: set[str] = set()
    built: list[dict] = []

    for ep in store.get_entry_points(limit=50):
        fn_name = ep.get("qualified_name", "").split(":")[-1]
        curated = curator.get_by_entry_function(fn_name)
        try:
            doc = assembler.assemble(ep["id"], curated_def=curated, used_names=used)
            if doc is None:
                continue
            store.upsert_pathway(doc)
            for step in doc.steps:
                store.insert_step_in_pathway(step.function_id, doc.id, step.order, step.role)
            for thread in doc.variable_threads:
                for step_order, function_id, variable_id in thread.steps:
                    try:
                        store.insert_var_in_pathway_edge(variable_id, doc.id, thread.name, step_order)
                    except Exception as exc:
                        rg_log.warn_once(
                            f"pathways: failed to record variable thread edge for {thread.name!r}: {exc}"
                        )
            built.append({
                "id": doc.id,
                "name": doc.name,
                "display_name": doc.display_name,
                "entry_function": doc.entry_function,
                "step_count": len(doc.steps),
                "confidence": doc.confidence,
                "source": doc.source,
            })
        except Exception as exc:
            entry_name = ep.get("qualified_name") or ep.get("name") or ep.get("id", "?")
            rg_log.warn_once(f"pathways: failed building pathway for {entry_name}: {exc}")
    # Lazy import avoids circular import: p10 → pathways package → this module.
    from repograph.pipeline.phases.p10_processes import append_pytest_coverage_pathways

    append_pytest_coverage_pathways(store)
    return built


class PathwayBuilderPlugin(StaticAnalyzerPlugin):
    manifest = PluginManifest(
        id="static_analyzer.pathways",
        name="Pathway builder",
        kind="static_analyzer",
        description="Builds Pathway nodes and pathway edges after entry-point scoring.",
        requires=("entry_points",),
        produces=("graph.pathways",),
        hooks=("on_graph_built",),
        order=100,
    )

    def analyze(self, store: GraphStore | None = None, repo_path: str = "", **kwargs):
        if store is None:
            service = kwargs.get("service")
            if service is None:
                return []
            return service.pathways(
                min_confidence=kwargs.get("min_confidence", 0.0),
                include_tests=kwargs.get("include_tests", False),
            )
        return run_pathway_build(store, repo_path)


def build_plugin() -> PathwayBuilderPlugin:
    return PathwayBuilderPlugin()
