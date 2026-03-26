"""Unit tests for Phase 14 — doc-vs-code symbol cross-check."""
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


class TestDocStaleReferenceDetection:
    """Backtick-quoted symbols that no longer exist must generate warnings."""

    def test_live_symbol_no_warning(self, tmp_path):
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "doc_staleness")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)

        # Run from the repo dir so p14 can resolve paths
        orig = os.getcwd()
        os.chdir(repo)
        try:
            _full_run(repo, rg_dir)
        finally:
            os.chdir(orig)

        store = _open_store(rg_dir)
        warnings = store.get_all_doc_warnings()
        store.close()

        # Live symbols must NOT generate warnings
        live_warned = [w for w in warnings
                       if w["symbol_text"] in ("process_data", "validate_input", "DataProcessor")]
        assert live_warned == [], \
            f"Live symbols generated warnings: {live_warned}"

    def test_clear_and_rerun_is_idempotent(self, tmp_path):
        """Running p14 twice must not duplicate warnings."""
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "doc_staleness")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)

        orig = os.getcwd()
        os.chdir(repo)
        try:
            _full_run(repo, rg_dir)
        finally:
            os.chdir(orig)

        store = _open_store(rg_dir)
        count_first = len(store.get_all_doc_warnings())

        # Re-run phase 14 directly
        from repograph.plugins.exporters.doc_warnings.plugin import run as run_doc_warnings
        run_doc_warnings(store)
        count_second = len(store.get_all_doc_warnings())
        store.close()

        assert count_first == count_second, \
            f"Second run produced different count: {count_first} vs {count_second}"


class TestDocWarningsAPIFilter:
    """Test the severity filter on the public API."""

    def test_doc_warnings_returns_list(self, tmp_path):
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "doc_staleness")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)

        orig = os.getcwd()
        os.chdir(repo)
        try:
            _full_run(repo, rg_dir)
        finally:
            os.chdir(orig)

        from repograph.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            warnings = rg.doc_warnings(severity="high")

        assert isinstance(warnings, list)

    def test_warning_dict_has_required_keys(self, tmp_path):
        """Each warning must contain the documented keys."""
        fixture = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "fixtures", "doc_staleness")
        )
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        shutil.copytree(fixture, repo)

        orig = os.getcwd()
        os.chdir(repo)
        try:
            _full_run(repo, rg_dir)
        finally:
            os.chdir(orig)

        from repograph.api import RepoGraph
        with RepoGraph(repo, repograph_dir=rg_dir) as rg:
            warnings = rg.doc_warnings()

        required_keys = {"doc_path", "line_number", "symbol_text",
                         "warning_type", "severity", "context_snippet"}
        for w in warnings:
            missing = required_keys - set(w.keys())
            assert not missing, f"Warning missing keys: {missing}"


class TestDocCheckerSkipsKnownNoise:
    """Common prose tokens must not generate false-positive warnings."""

    def test_python_keywords_not_flagged(self, tmp_path):
        """True, False, None etc. must be silently skipped."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        os.makedirs(os.path.join(repo, "src"), exist_ok=True)

        # A Python source file with real symbols
        with open(os.path.join(repo, "src", "utils.py"), "w") as f:
            f.write("def helper(): pass\n")

        # A doc that mentions only keywords
        os.makedirs(os.path.join(repo, "docs"), exist_ok=True)
        with open(os.path.join(repo, "docs", "guide.md"), "w") as f:
            f.write("Use `True` or `False`. Never `None`. The `list` type.\n")

        orig = os.getcwd()
        os.chdir(repo)
        try:
            _full_run(repo, rg_dir)
        finally:
            os.chdir(orig)

        store = _open_store(rg_dir)
        warnings = store.get_all_doc_warnings()
        store.close()

        keyword_warned = [w for w in warnings
                          if w["symbol_text"] in ("True", "False", "None", "list")]
        assert keyword_warned == [], \
            f"Keywords generated warnings: {keyword_warned}"

    def test_short_tokens_not_flagged(self, tmp_path):
        """Tokens shorter than 3 chars must be silently skipped."""
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / ".repograph")
        os.makedirs(os.path.join(repo, "src"), exist_ok=True)
        with open(os.path.join(repo, "src", "utils.py"), "w") as f:
            f.write("def helper(): pass\n")
        os.makedirs(os.path.join(repo, "docs"), exist_ok=True)
        with open(os.path.join(repo, "docs", "guide.md"), "w") as f:
            f.write("Use `x` or `fn` or `id`.\n")

        orig = os.getcwd()
        os.chdir(repo)
        try:
            _full_run(repo, rg_dir)
        finally:
            os.chdir(orig)

        store = _open_store(rg_dir)
        warnings = store.get_all_doc_warnings()
        store.close()

        short_warned = [w for w in warnings
                        if len(w["symbol_text"]) < 3]
        assert short_warned == []
