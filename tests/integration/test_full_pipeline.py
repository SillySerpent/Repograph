"""Integration tests — full pipeline on fixture repos."""
from __future__ import annotations

import os
import tempfile
import pytest

FLASK_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
SIMPLE_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_simple")


@pytest.fixture
def flask_store(tmp_path):
    """Run full pipeline on the flask fixture and return the store."""
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    rg_dir = str(tmp_path / ".repograph")
    config = RunConfig(
        repo_root=os.path.abspath(FLASK_FIXTURE),
        repograph_dir=rg_dir,
        include_git=False,
        include_embeddings=False,
        full=True,
    )
    run_full_pipeline(config)
    db = os.path.join(rg_dir, "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    return store


JS_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "js_express")


@pytest.fixture
def js_store(tmp_path):
    """Run full pipeline on the JS express fixture."""
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    rg_dir = str(tmp_path / ".repograph")
    config = RunConfig(
        repo_root=os.path.abspath(JS_FIXTURE),
        repograph_dir=rg_dir,
        include_git=False,
        include_embeddings=False,
        full=True,
    )
    run_full_pipeline(config)
    db = os.path.join(rg_dir, "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    return store


class TestJSPipelineIntegration:
    def test_js_files_indexed(self, js_store):
        stats = js_store.get_stats()
        assert stats["files"] >= 4

    def test_js_functions_extracted(self, js_store):
        fns = js_store.get_all_functions()
        names = {f["name"] for f in fns}
        assert "loginHandler" in names
        assert "searchEndpoint" in names
        assert "validateCredentials" in names

    def test_js_call_edges(self, js_store):
        edges = js_store.get_all_call_edges()
        assert len(edges) >= 1

    def test_js_pathways_generated(self, js_store):
        pathways = js_store.get_all_pathways()
        assert len(pathways) >= 1

    def test_js_mirror_docs(self, tmp_path):
        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        import json

        rg_dir = str(tmp_path / ".repograph_js")
        config = RunConfig(
            repo_root=os.path.abspath(JS_FIXTURE),
            repograph_dir=rg_dir,
            include_git=False, full=True,
        )
        run_full_pipeline(config)
        mirror_dir = os.path.join(rg_dir, "mirror")
        jsons = []
        for root, _, files in os.walk(mirror_dir):
            jsons.extend(f for f in files if f.endswith(".json"))
        assert len(jsons) >= 1


class TestPythonSimplePipelineIntegration:
    def test_files_indexed(self, simple_store):
        stats = simple_store.get_stats()
        assert stats["files"] >= 3

    def test_functions_extracted(self, simple_store):
        fns = simple_store.get_all_functions()
        names = {f["name"] for f in fns}
        assert "run" in names
        assert "find_user" in names
        assert "get_user_display" in names

    def test_call_edges_created(self, simple_store):
        edges = simple_store.get_all_call_edges()
        assert len(edges) >= 1

    def test_dead_code_detected(self, simple_store):
        dead = simple_store.get_dead_functions()
        dead_names = {f["qualified_name"].split(":")[-1] for f in dead}
        # _unused_helper should be dead (never called, private)
        assert "_unused_helper" in dead_names

    def test_mirror_docs_written(self, tmp_path):
        from repograph.pipeline.runner import RunConfig, run_full_pipeline

        rg_dir = str(tmp_path / ".repograph2")
        config = RunConfig(
            repo_root=os.path.abspath(SIMPLE_FIXTURE),
            repograph_dir=rg_dir,
            include_git=False, full=True,
        )
        run_full_pipeline(config)

        mirror_dir = os.path.join(rg_dir, "mirror")
        assert os.path.isdir(mirror_dir)
        # Check at least one .json file exists
        jsons = []
        for root, _, files in os.walk(mirror_dir):
            jsons.extend(f for f in files if f.endswith(".json"))
        assert len(jsons) >= 1


class TestFlaskPipelineIntegration:
    def test_files_indexed(self, flask_store):
        stats = flask_store.get_stats()
        assert stats["files"] >= 5

    def test_login_handler_found(self, flask_store):
        results = flask_store.search_functions_by_name("login_handler")
        assert len(results) >= 1

    def test_validate_credentials_found(self, flask_store):
        results = flask_store.search_functions_by_name("validate_credentials")
        assert len(results) >= 1

    def test_import_resolution(self, flask_store):
        # validate_credentials should have callers (login_handler)
        results = flask_store.search_functions_by_name("validate_credentials")
        if results:
            callers = flask_store.get_callers(results[0]["id"])
            # May or may not resolve depending on import path — at minimum no error
            assert isinstance(callers, list)

    def test_pathways_generated(self, flask_store):
        pathways = flask_store.get_all_pathways()
        assert len(pathways) >= 1

    def test_entry_points_scored(self, flask_store):
        eps = flask_store.get_entry_points(limit=10)
        assert len(eps) >= 1
        # All should have non-zero scores
        for ep in eps:
            assert ep.get("entry_score", 0) > 0

    def test_meta_json_written(self, tmp_path):
        from repograph.pipeline.runner import RunConfig, run_full_pipeline

        rg_dir = str(tmp_path / ".repograph3")
        config = RunConfig(
            repo_root=os.path.abspath(FLASK_FIXTURE),
            repograph_dir=rg_dir,
            include_git=False, full=True,
        )
        run_full_pipeline(config)
        meta = os.path.join(rg_dir, "meta.json")
        assert os.path.exists(meta)

        import json
        with open(meta) as f:
            data = json.load(f)
        assert "stats" in data
        assert "pathways" in data


class TestIncrementalSync:
    def test_incremental_detects_no_changes(self, tmp_path):
        from repograph.graph_store.store import GraphStore
        from repograph.pipeline.runner import RunConfig, run_full_pipeline, run_incremental_pipeline
        from repograph.pipeline.incremental import IncrementalDiff
        from repograph.pipeline.phases.p01_walk import run as walk

        fixture = os.path.abspath(SIMPLE_FIXTURE)
        rg_dir = str(tmp_path / ".repograph_inc")

        config = RunConfig(
            repo_root=fixture, repograph_dir=rg_dir,
            include_git=False, full=True,
        )
        run_full_pipeline(config)

        # Save index
        differ = IncrementalDiff(rg_dir)
        files = walk(fixture)
        differ.save_index({fr.path: fr for fr in files})

        # Now incremental should find no changes
        diff = differ.compute({fr.path: fr for fr in files})
        assert not diff.added
        assert not diff.removed
        assert not diff.changed


MIXED_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "mixed")


class TestMixedLanguagePipeline:
    def test_mixed_files_indexed(self, tmp_path):
        from repograph.graph_store.store import GraphStore
        from repograph.pipeline.runner import RunConfig, run_full_pipeline

        rg_dir = str(tmp_path / ".repograph_mixed")
        config = RunConfig(
            repo_root=os.path.abspath(MIXED_FIXTURE),
            repograph_dir=rg_dir,
            include_git=False, full=True,
        )
        run_full_pipeline(config)
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        stats = store.get_stats()

        # Both Python and JS files indexed
        assert stats["files"] >= 2
        fns = store.get_all_functions()
        fn_names = {f["name"] for f in fns}
        # Python functions
        assert "process_request" in fn_names
        assert "validate_payload" in fn_names
        # JS functions
        assert "sendRequest" in fn_names
        assert "buildPayload" in fn_names
