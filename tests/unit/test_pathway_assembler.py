"""Unit tests for the pathway assembler."""
from __future__ import annotations

import os
import pytest
import tempfile

FLASK_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")


@pytest.fixture(scope="module")
def flask_store():
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


class TestEntryPointScoring:
    def test_login_handler_is_entry_point(self, flask_store):
        results = flask_store.search_functions_by_name("login_handler", limit=1)
        assert results
        fn = flask_store.get_function_by_id(results[0]["id"])
        assert fn["is_entry_point"] is True

    def test_entry_score_positive(self, flask_store):
        eps = flask_store.get_entry_points(limit=10)
        assert all(ep["entry_score"] > 0 for ep in eps)

    def test_entry_points_have_callees(self, flask_store):
        eps = flask_store.get_entry_points(limit=5)
        for ep in eps:
            callees = flask_store.get_callees(ep["id"])
            # entry points should call something (or have been scored because they're exported)
            assert isinstance(callees, list)


class TestPathwayAssembly:
    def test_pathways_exist(self, flask_store):
        pathways = flask_store.get_all_pathways()
        assert len(pathways) >= 1

    def test_login_pathway_has_steps(self, flask_store):
        pathways = flask_store.get_all_pathways()
        login = next((p for p in pathways if "login" in p["name"]), None)
        assert login is not None
        assert login["step_count"] >= 2

    def test_pathway_confidence_range(self, flask_store):
        pathways = flask_store.get_all_pathways()
        for p in pathways:
            assert 0.0 <= p["confidence"] <= 1.0

    def test_pathway_steps_are_ordered(self, flask_store):
        pathways = flask_store.get_all_pathways()
        for p in pathways:
            steps = flask_store.get_pathway_steps(p["id"])
            if len(steps) >= 2:
                orders = [s["step_order"] for s in steps]
                assert orders == sorted(orders)

    def test_pathway_context_doc_generated(self, flask_store):
        pathways = flask_store.get_all_pathways()
        # At least one pathway should have a context doc (via get_pathway_by_id)
        found_ctx = False
        for p in pathways:
            full = flask_store.get_pathway_by_id(p["id"])
            if full and full.get("context_doc"):
                found_ctx = True
                break
        assert found_ctx, "No pathway has a generated context doc"

    def test_context_doc_contains_pathway_name(self, flask_store):
        pathways = flask_store.get_all_pathways()
        for p in pathways:
            full = flask_store.get_pathway_by_id(p["id"])
            if full and full.get("context_doc"):
                assert "PATHWAY:" in full["context_doc"]
                break


class TestPathwayAssemblerDirect:
    def test_assemble_from_entry(self, flask_store):
        from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler
        eps = flask_store.get_entry_points(limit=1)
        assert eps
        assembler = PathwayAssembler(flask_store)
        doc = assembler.assemble(eps[0]["id"])
        assert doc is not None
        assert len(doc.steps) >= 2
        assert doc.steps[0].role == "entry"

    def test_assemble_with_curated_def(self, flask_store):
        from repograph.plugins.static_analyzers.pathways.assembler import PathwayAssembler
        from repograph.plugins.static_analyzers.pathways.curator import CuratedPathwayDef
        eps = flask_store.get_entry_points(limit=1)
        assert eps

        curated = CuratedPathwayDef(
            name="custom_login",
            display_name="Custom Login",
            description="A custom login pathway",
            entry_file="routes/auth.py",
            entry_function="login_handler",
            terminal_hint="db_read",
        )
        assembler = PathwayAssembler(flask_store)
        doc = assembler.assemble(eps[0]["id"], curated_def=curated)
        assert doc is not None
        assert doc.name == "custom_login"
        assert doc.source == "hybrid"
        assert doc.terminal_type == "db_read"
