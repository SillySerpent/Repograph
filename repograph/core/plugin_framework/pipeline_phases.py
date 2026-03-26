"""Protocol for optional pipeline phases (after graph build, before hooks)."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from repograph.core.models import ParsedFile
from repograph.graph_store.store import GraphStore


@runtime_checkable
class PipelinePhasePlugin(Protocol):
    """Optional phase inserted when ``RunConfig.experimental_phase_plugins`` is True."""

    phase_id: str

    def run(
        self,
        *,
        store: GraphStore,
        parsed: list[ParsedFile],
        repo_root: str,
        repograph_dir: str,
        config: Any,
    ) -> None:
        ...
