"""Reference no-op pipeline phase for SPI validation."""
from __future__ import annotations

from typing import Any

from repograph.core.models import ParsedFile
from repograph.graph_store.store import GraphStore


class NoOpPipelinePhase:
    phase_id = "phase.experimental_no_op"

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


def build_no_op() -> NoOpPipelinePhase:
    return NoOpPipelinePhase()
