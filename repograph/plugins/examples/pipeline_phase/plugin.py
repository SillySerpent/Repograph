"""REFERENCE ONLY — not registered in production.

How to implement an experimental pipeline phase
-----------------------------------------------
This is **not** a ``RepoGraphPlugin`` and does **not** use the hook scheduler.
It implements the ``PipelinePhasePlugin`` protocol in
``repograph.core.plugin_framework.pipeline_phases``.

1. Provide ``phase_id: str`` and ``run(store=..., parsed=..., repo_root=..., repograph_dir=..., config=...)``.
2. Register instances in ``repograph.plugins.pipeline_phases.registry.iter_pipeline_phases``.
3. Enable with ``RunConfig.experimental_phase_plugins = True`` in API callers.

Production uses this only for advanced extension points; most features should remain
normal plugins under ``on_graph_built`` / ``on_export`` / etc.

See ``plugins/pipeline_phases/no_op/plugin.py`` and ``docs/architecture/PLUGIN_PHASES_AND_HOOKS.md``.
"""
from __future__ import annotations

from typing import Any

from repograph.core.models import ParsedFile
from repograph.graph_store.store import GraphStore


class ExamplePipelinePhase:
    phase_id = "phase.example_reference"

    def run(
        self,
        *,
        store: GraphStore,
        parsed: list[ParsedFile],
        repo_root: str,
        repograph_dir: str,
        config: Any,
    ) -> None:
        del store, parsed, repo_root, repograph_dir, config


def build_plugin() -> ExamplePipelinePhase:
    """Named ``build_plugin`` for symmetry with other examples (not a RepoGraphPlugin)."""
    return ExamplePipelinePhase()
