"""Unit tests for Phase 11b — duplicate symbol detection."""
from __future__ import annotations

import os
import shutil

import pytest


def _full_run(repo: str, rg_dir: str):
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    return run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg_dir,
        include_git=False, include_embeddings=False, full=True,
    ))


def _open_store(rg_dir: str):
    from repograph.graph_store.store import GraphStore
    store = GraphStore(os.path.join(rg_dir, "graph.db"))
    store.initialize_schema()
    return store


class TestDuplicateDetectionLogic:
    """Unit tests against the detection logic directly (no full pipeline)."""

    def test_plugin_contract_functions_are_skipped(self):
        from repograph.plugins.static_analyzers.duplicates.plugin import _find_medium_severity

        rows = _find_medium_severity([
            {
                "id": "a",
                "name": "build_plugin",
                "qualified_name": "build_plugin",
                "signature": "()",
                "file_path": "repograph/plugins/exporters/a/plugin.py",
                "is_dead": False,
            },
            {
                "id": "b",
                "name": "build_plugin",
                "qualified_name": "build_plugin",
                "signature": "()",
                "file_path": "repograph/plugins/exporters/b/plugin.py",
                "is_dead": False,
            },
        ])
        assert rows == []

    def test_identical_body_hash_high_different_hash_medium(self):
        from repograph.plugins.static_analyzers.duplicates.plugin import _find_high_severity

        fn_a = {
            "id": "a", "name": "x", "qualified_name": "x",
            "file_path": "a.py", "source_hash": "h1", "is_dead": False,
        }
        fn_b = {
            "id": "b", "name": "x", "qualified_name": "x",
            "file_path": "b.py", "source_hash": "h2", "is_dead": False,
        }
        high, med = _find_high_severity([fn_a, fn_b], [], None, False)
        assert not high
        assert any(g.reason == "same_qualified_name_different_body" for g in med)

        fn_c = {**fn_b, "id": "c", "source_hash": "h1", "file_path": "c.py"}
        high2, med2 = _find_high_severity([fn_a, fn_c], [], None, False)
        assert any(g.severity == "high" for g in high2)
        assert not med2

    def test_high_severity_same_qualified_name(self, tmp_path):
        """Two files defining new_decision_id → high severity group."""
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "duplicate_symbols")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        store = _open_store(rg_dir)
        groups = store.get_all_duplicate_symbols()
        store.close()

        high_groups = [g for g in groups if g["severity"] == "high"]
        names = {g["name"] for g in high_groups}
        assert "new_decision_id" in names, \
            f"new_decision_id not in high-severity groups: {names}"

    def test_high_severity_is_superseded_when_one_copy_dead(self, tmp_path):
        """The idgen.py copy is never called — must be superseded=True."""
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "duplicate_symbols")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        store = _open_store(rg_dir)
        groups = store.get_all_duplicate_symbols()
        store.close()

        decision_groups = [g for g in groups if g["name"] == "new_decision_id"]
        assert len(decision_groups) >= 1
        # At least one group should be superseded (idgen.py copy is dead)
        assert any(g["is_superseded"] for g in decision_groups), \
            "new_decision_id duplicate should be marked superseded"

    def test_multiple_file_paths_in_group(self, tmp_path):
        """The file_paths list must contain all files where the symbol appears."""
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "duplicate_symbols")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        store = _open_store(rg_dir)
        groups = store.get_all_duplicate_symbols()
        store.close()

        decision_groups = [
            g for g in groups
            if g["name"] == "new_decision_id" and g["severity"] == "high"
        ]
        assert len(decision_groups) >= 1
        assert decision_groups[0].get("reason") == "same_qualified_name_identical_body"
        fps = decision_groups[0]["file_paths"]
        assert len(fps) >= 2, f"Expected 2+ file paths, got: {fps}"

    def test_unique_symbol_not_flagged(self, tmp_path):
        """compute() only exists in engine.py — must not be duplicated."""
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "duplicate_symbols")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        store = _open_store(rg_dir)
        groups = store.get_all_duplicate_symbols()
        store.close()

        # compute is only in engine.py — must not appear as a high-severity dup
        high_names = {g["name"] for g in groups if g["severity"] == "high"}
        assert "compute" not in high_names

    def test_dunder_init_not_flagged(self, tmp_path):
        """__init__ appears everywhere — must never be flagged."""
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        store = _open_store(rg_dir)
        groups = store.get_all_duplicate_symbols()
        store.close()

        all_names = {g["name"] for g in groups}
        assert "__init__" not in all_names, \
            "__init__ must never be flagged as a duplicate"


class TestDuplicatesAPIFiltering:
    """Test the min_severity filter on the public API."""

    def test_min_severity_high_excludes_medium(self, tmp_path):
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "duplicate_symbols")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)
        _full_run(repo, rg_dir)

        from repograph.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            high_only = rg.duplicates(min_severity="high")
            medium_up = rg.duplicates(min_severity="medium")

        for g in high_only:
            assert g["severity"] == "high"
        # medium_up must be a superset of high_only
        high_ids = {g["id"] for g in high_only}
        medium_ids = {g["id"] for g in medium_up}
        assert high_ids.issubset(medium_ids)
