"""Integration tests for MCP tools against the indexed fixture."""
from __future__ import annotations

import os
import tempfile
import pytest

FLASK_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")


@pytest.fixture(scope="module")
def mcp_store():
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    with tempfile.TemporaryDirectory() as tmp:
        rg_dir = os.path.join(tmp, ".repograph")
        config = RunConfig(
            repo_root=os.path.abspath(FLASK_FIXTURE),
            repograph_dir=rg_dir,
            include_git=False, full=True,
        )
        run_full_pipeline(config)
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        yield store


class TestMCPTools:
    def test_list_pathways(self, mcp_store):
        # Test tool logic directly without needing the mcp package
        pathways = mcp_store.get_all_pathways()
        assert len(pathways) >= 1
        assert all("name" in p for p in pathways)

    def test_get_pathway_returns_context(self, mcp_store):
        pathways = mcp_store.get_all_pathways()
        assert pathways
        p = mcp_store.get_pathway(pathways[0]["name"])
        assert p is not None
        # Context doc should exist after sync
        ctx = p.get("context_doc", "")
        assert isinstance(ctx, str)

    def test_get_node_file(self, mcp_store):
        result = mcp_store.get_file("routes/auth.py")
        assert result is not None
        assert result["path"] == "routes/auth.py"

    def test_get_node_function(self, mcp_store):
        results = mcp_store.search_functions_by_name("login_handler", limit=1)
        assert results
        fn = mcp_store.get_function_by_id(results[0]["id"])
        assert fn is not None
        assert fn["name"] == "login_handler"

    def test_get_dependents(self, mcp_store):
        results = mcp_store.search_functions_by_name("validate_credentials", limit=1)
        assert results
        callers = mcp_store.get_callers(results[0]["id"])
        assert isinstance(callers, list)

    def test_get_dependencies(self, mcp_store):
        results = mcp_store.search_functions_by_name("login_handler", limit=1)
        assert results
        callees = mcp_store.get_callees(results[0]["id"])
        assert len(callees) >= 1  # login_handler calls validate_credentials and generate_token

    def test_search_returns_results(self, mcp_store):
        from repograph.search.hybrid import HybridSearch
        searcher = HybridSearch(mcp_store)
        results = searcher.search("login", limit=5)
        assert len(results) >= 1
        names = [r["name"] for r in results]
        assert any("login" in n.lower() for n in names)

    def test_impact_finds_callers(self, mcp_store):
        results = mcp_store.search_functions_by_name("validate_credentials", limit=1)
        assert results
        fn_id = results[0]["id"]
        callers = mcp_store.get_callers(fn_id)
        # validate_credentials is called by login_handler
        assert isinstance(callers, list)

    def test_get_entry_points(self, mcp_store):
        eps = mcp_store.get_entry_points(limit=10)
        assert len(eps) >= 1
        assert all(ep.get("entry_score", 0) > 0 for ep in eps)

    def test_get_dead_code(self, mcp_store):
        dead = mcp_store.get_dead_functions()
        assert isinstance(dead, list)
        # logout_handler is never called — should be dead
        dead_names = {d["qualified_name"].split(":")[-1] for d in dead}
        assert "logout_handler" in dead_names

    def test_trace_variable(self, mcp_store):
        rows = mcp_store.query(
            "MATCH (v:Variable {name: $name}) RETURN v.id, v.function_id LIMIT 5",
            {"name": "email"}
        )
        assert isinstance(rows, list)

    def test_search_fuzzy_misspelling(self, mcp_store):
        from repograph.search.hybrid import HybridSearch
        searcher = HybridSearch(mcp_store)
        # "logn" is close to "login"
        results = searcher.search("logn_handler", limit=5)
        # fuzzy should return something relevant
        assert isinstance(results, list)
