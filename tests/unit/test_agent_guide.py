"""Tests for agent_guide generator (repo-summary and doc-index helpers)."""
from __future__ import annotations

import os
import shutil
import pytest

from repograph.plugins.exporters.agent_guide.generator import (
    _extract_doc_index,
    _extract_repo_summary,
)


# ---------------------------------------------------------------------------
# _extract_repo_summary
# ---------------------------------------------------------------------------

class TestExtractRepoSummary:
    def test_reads_readme_first_paragraph(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "# MyTrader\n\nAn algorithmic trading system for BTC/USDT on Bitunix.\n"
        )
        result = _extract_repo_summary(str(tmp_path))
        assert "algorithmic trading" in result

    def test_skips_heading_only_blocks(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "# MyTrader\n\n## Overview\n\nThis system does real-time order execution.\n"
        )
        result = _extract_repo_summary(str(tmp_path))
        # Should get the paragraph under Overview, not the heading
        assert "real-time order execution" in result

    def test_skips_badge_lines(self, tmp_path):
        (tmp_path / "README.md").write_text(
            "# Project\n\n"
            "![Build](https://img.shields.io/badge/build-passing)\n\n"
            "A production trading bot.\n"
        )
        result = _extract_repo_summary(str(tmp_path))
        assert "trading bot" in result
        assert "shields.io" not in result

    def test_falls_back_to_docs_ai_repo_map(self, tmp_path):
        docs_ai = tmp_path / "docs" / "ai"
        docs_ai.mkdir(parents=True)
        (docs_ai / "REPO_MAP.md").write_text(
            "# Repo Map\n\nThis repo is a live algo trading system.\n"
        )
        result = _extract_repo_summary(str(tmp_path))
        assert "algo trading" in result

    def test_returns_empty_when_no_readme(self, tmp_path):
        result = _extract_repo_summary(str(tmp_path))
        assert result == ""

    def test_truncates_long_paragraphs(self, tmp_path):
        long_text = "x " * 400   # 800 chars
        (tmp_path / "README.md").write_text(f"# Title\n\n{long_text}\n")
        result = _extract_repo_summary(str(tmp_path))
        assert len(result) <= 600

    def test_appends_list_block_when_paragraph_ends_with_colon(self, tmp_path):
        """A paragraph ending with ':' followed by a bullet list must include both."""
        readme = (
            "# My Project\n\n"
            "This repo is a trading engine with:\n\n"
            "- paper trading\n"
            "- champion + challenger bots\n"
            "- SQLite-backed analytics\n"
        )
        (tmp_path / "README.md").write_text(readme)
        result = _extract_repo_summary(str(tmp_path))
        assert "trading engine with:" in result
        assert "paper trading" in result, f"List items missing from summary: {result!r}"
        assert "champion" in result, f"List items missing from summary: {result!r}"

    def test_does_not_append_non_list_block(self, tmp_path):
        """A plain paragraph following the first must not be appended."""
        readme = (
            "# Title\n\n"
            "First paragraph here.\n\n"
            "Second paragraph that should not appear.\n"
        )
        (tmp_path / "README.md").write_text(readme)
        result = _extract_repo_summary(str(tmp_path))
        assert "First paragraph" in result
        assert "Second paragraph" not in result

    def test_appends_star_list_block(self, tmp_path):
        """* list markers (not just -) must also trigger the append."""
        readme = (
            "# X\n\n"
            "Features include:\n\n"
            "* async engine\n"
            "* websocket support\n"
        )
        (tmp_path / "README.md").write_text(readme)
        result = _extract_repo_summary(str(tmp_path))
        assert "async engine" in result

    def test_handles_unreadable_file_gracefully(self, tmp_path):
        readme = tmp_path / "README.md"
        readme.write_text("# A\n\nsome content\n")
        # Make unreadable
        readme.chmod(0o000)
        try:
            result = _extract_repo_summary(str(tmp_path))
            # Should not raise — falls back silently
            assert isinstance(result, str)
        finally:
            readme.chmod(0o644)


# ---------------------------------------------------------------------------
# _extract_doc_index
# ---------------------------------------------------------------------------

class TestExtractDocIndex:
    def test_finds_markdown_files_in_docs(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "ARCHITECTURE.md").write_text("# Architecture\n...")
        (docs / "QUICKSTART.md").write_text("# Quick Start\n...")
        result = _extract_doc_index(str(tmp_path))
        paths = [r[0] for r in result]
        assert any("ARCHITECTURE.md" in p for p in paths)
        assert any("QUICKSTART.md" in p for p in paths)

    def test_extracts_first_heading(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "OVERVIEW.md").write_text("# System Overview\nDetailed description.\n")
        result = _extract_doc_index(str(tmp_path))
        headings = [r[1] for r in result]
        assert "System Overview" in headings

    def test_handles_subdirectories(self, tmp_path):
        (tmp_path / "docs" / "ai").mkdir(parents=True)
        (tmp_path / "docs" / "human").mkdir(parents=True)
        (tmp_path / "docs" / "ai" / "TECH.md").write_text("# Tech Architecture\n")
        (tmp_path / "docs" / "human" / "GUIDE.md").write_text("# User Guide\n")
        result = _extract_doc_index(str(tmp_path))
        all_paths = [r[0] for r in result]
        assert any("TECH.md" in p for p in all_paths)
        assert any("GUIDE.md" in p for p in all_paths)

    def test_caps_at_20_results(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        for i in range(30):
            (docs / f"doc_{i:02d}.md").write_text(f"# Doc {i}\n")
        result = _extract_doc_index(str(tmp_path))
        assert len(result) <= 20

    def test_returns_empty_when_no_docs_dir(self, tmp_path):
        result = _extract_doc_index(str(tmp_path))
        assert result == []

    def test_ignores_non_markdown_files(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "config.yaml").write_text("key: value\n")
        (docs / "README.md").write_text("# Readme\n")
        result = _extract_doc_index(str(tmp_path))
        paths = [r[0] for r in result]
        assert not any("config.yaml" in p for p in paths)


# ---------------------------------------------------------------------------
# Full guide integration: README summary + doc index appear in output
# ---------------------------------------------------------------------------

FLASK_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
)


@pytest.fixture(scope="module")
def flask_store_for_guide(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("guide")
    repo = str(tmp / "repo")
    rg_dir = str(tmp / "repo" / ".repograph")
    shutil.copytree(FLASK_FIXTURE, repo)
    # Add README and docs
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("# Flask Auth App\n\nA minimal Flask authentication service with JWT tokens.\n")
    docs_dir = os.path.join(repo, "docs")
    os.makedirs(docs_dir)
    with open(os.path.join(docs_dir, "ARCHITECTURE.md"), "w") as f:
        f.write("# Architecture\nTwo-tier: routes + services.\n")
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg_dir,
        include_git=False, full=True,
    ))
    from repograph.graph_store.store import GraphStore
    store = GraphStore(os.path.join(rg_dir, "graph.db"))
    store.initialize_schema()
    yield store, repo, rg_dir
    store.close()


class TestAgentGuideDocSurfacing:
    def test_guide_includes_readme_summary(self, flask_store_for_guide):
        from repograph.plugins.exporters.agent_guide.generator import generate_agent_guide
        store, repo, rg_dir = flask_store_for_guide
        guide = generate_agent_guide(store, repo, rg_dir)
        assert "## About This Repo" in guide
        assert "Flask authentication" in guide

    def test_guide_includes_doc_index_section(self, flask_store_for_guide):
        from repograph.plugins.exporters.agent_guide.generator import generate_agent_guide
        store, repo, rg_dir = flask_store_for_guide
        guide = generate_agent_guide(store, repo, rg_dir)
        assert "## Documentation Index" in guide
        assert "ARCHITECTURE.md" in guide

    def test_guide_omits_about_section_when_no_readme(self, tmp_path):
        """No README → no About section (guide still valid)."""
        from repograph.plugins.exporters.agent_guide.generator import generate_agent_guide
        from repograph.graph_store.store import GraphStore
        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        repo = str(tmp_path / "repo")
        rg_dir = str(tmp_path / "repo" / ".repograph")
        shutil.copytree(FLASK_FIXTURE, repo)
        run_full_pipeline(RunConfig(
            repo_root=repo, repograph_dir=rg_dir,
            include_git=False, full=True,
        ))
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        guide = generate_agent_guide(store, repo, rg_dir)
        store.close()
        # Should not crash and should not have About section
        assert "## How to Navigate" in guide
        assert "## About This Repo" not in guide

    def test_guide_omits_doc_index_when_no_docs(self, tmp_path):
        """No docs/ dir → no Documentation Index section."""
        from repograph.plugins.exporters.agent_guide.generator import generate_agent_guide
        from repograph.graph_store.store import GraphStore
        from repograph.pipeline.runner import RunConfig, run_full_pipeline
        repo = str(tmp_path / "repo2")
        rg_dir = str(tmp_path / "repo2" / ".repograph")
        shutil.copytree(FLASK_FIXTURE, repo)
        run_full_pipeline(RunConfig(
            repo_root=repo, repograph_dir=rg_dir,
            include_git=False, full=True,
        ))
        store = GraphStore(os.path.join(rg_dir, "graph.db"))
        store.initialize_schema()
        guide = generate_agent_guide(store, repo, rg_dir)
        store.close()
        assert "## Documentation Index" not in guide
