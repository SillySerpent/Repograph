from __future__ import annotations

import inspect

import repograph.core.plugin_framework.pipeline_phases as mod


def test_pipeline_phase_protocol_avoids_runtime_graphstore_import() -> None:
    src = inspect.getsource(mod)
    assert "from repograph.graph_store.store import GraphStore" in src
    assert "if TYPE_CHECKING" in src
