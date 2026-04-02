"""FastMCP ``create_server`` wiring (optional ``mcp`` extra)."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.requires_mcp]

FLASK_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")


@pytest.fixture(scope="module")
def flask_service():
    pytest.importorskip("mcp")
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    from repograph.services import RepoGraphService

    with tempfile.TemporaryDirectory() as tmp:
        rg_dir = os.path.join(tmp, ".repograph")
        config = RunConfig(
            repo_root=os.path.abspath(FLASK_FIXTURE),
            repograph_dir=rg_dir,
            include_git=False,
            full=True,
        )
        run_full_pipeline(config)
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        svc = RepoGraphService(repo_path=os.path.abspath(FLASK_FIXTURE), repograph_dir=rg_dir)
        yield svc


def test_create_server_registers_tools(flask_service) -> None:
    from repograph.surfaces.mcp.server import create_server

    mcp = create_server(flask_service)
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert "impact" in names
    assert "trace_variable" in names


def test_impact_tool_shape(flask_service) -> None:
    from repograph.surfaces.mcp.server import create_server

    mcp = create_server(flask_service)
    raw = asyncio.run(mcp.call_tool("impact", {"symbol": "validate_credentials", "min_confidence": 0.5}))
    assert isinstance(raw, list) and raw
    first = raw[0]
    text = getattr(first, "text", None)
    assert isinstance(text, str), f"unexpected tool result item: {first!r}"
    payload = json.loads(text)
    assert "will_break" in payload
    assert "may_break" in payload
    assert "warnings" in payload
    assert isinstance(payload["will_break"], list)
    assert isinstance(payload["may_break"], list)


def test_trace_variable_schema_no_pathway_only_arg(flask_service) -> None:
    from repograph.surfaces.mcp.server import create_server

    mcp = create_server(flask_service)
    tools = asyncio.run(mcp.list_tools())
    tv = next(t for t in tools if t.name == "trace_variable")
    props = (tv.inputSchema or {}).get("properties") or {}
    assert "variable_name" in props
    assert "pathway" not in props
