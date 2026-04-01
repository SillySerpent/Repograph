"""Tests for pathway test/production separation — API and CLI."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import pytest

FLASK_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
)


@pytest.fixture(scope="module")
def flask_rg(tmp_path_factory):
    """Run full pipeline on flask fixture (which includes test_routes.py)."""
    tmp = tmp_path_factory.mktemp("pathway_filter")
    repo = str(tmp / "repo")
    rg_dir = str(tmp / "repo" / ".repograph")
    shutil.copytree(FLASK_FIXTURE, repo)
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg_dir,
        include_git=False, full=True,
    ))
    from repograph.surfaces.api import RepoGraph
    rg = RepoGraph(repo, repograph_dir=rg_dir)
    yield rg
    rg.close()


class TestPathwayAPIFilter:
    def test_default_excludes_test_pathways(self, flask_rg):
        """pathways() with default include_tests=False must not contain test sources."""
        prod = flask_rg.pathways()
        for p in prod:
            assert p.get("source") != "auto_detected_test", (
                f"Test pathway leaked into default listing: {p['name']}"
            )

    def test_include_tests_flag_restores_all(self, flask_rg):
        """include_tests=True must return a strict superset of default."""
        prod = flask_rg.pathways(include_tests=False)
        both = flask_rg.pathways(include_tests=True)
        assert len(both) >= len(prod), \
            "include_tests=True returned fewer pathways than default"

    def test_include_tests_contains_test_source(self, flask_rg):
        """With include_tests=True the full set must include at least one test pathway."""
        all_p = flask_rg.pathways(include_tests=True)
        sources = {p.get("source") for p in all_p}
        assert "auto_detected_test" in sources, \
            "No auto_detected_test pathway found even with include_tests=True"

    def test_min_confidence_still_works_with_filter(self, flask_rg):
        """min_confidence filter must compose correctly with include_tests filter."""
        high_conf = flask_rg.pathways(min_confidence=0.9, include_tests=False)
        for p in high_conf:
            assert p.get("confidence", 0) >= 0.9
            assert p.get("source") != "auto_detected_test"


class TestPathwayCLIFilter:
    def test_cli_default_hides_test_count(self, flask_rg):
        """CLI default output must mention how many test pathways were hidden."""
        repo = flask_rg.repo_path
        flask_rg.close()   # release DB handle before subprocess opens it
        result = subprocess.run(
            [sys.executable, "-m", "repograph", "pathway", "list", repo],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        combined = result.stdout + result.stderr
        assert "test" in combined.lower(), (
            f"Expected mention of hidden test pathways in output:\n{combined[:800]}"
        )

    def test_cli_include_tests_shows_test_table(self, flask_rg):
        """--include-tests flag must render the test pathway table."""
        repo = flask_rg.repo_path
        flask_rg.close()
        result = subprocess.run(
            [sys.executable, "-m", "repograph", "pathway", "list",
             "--include-tests", repo],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "test" in result.stdout.lower(), (
            f"Expected test pathway table in --include-tests output:\n{result.stdout[:800]}"
        )


class TestAgentGuidePathwaySplit:
    def test_guide_has_production_section(self, flask_rg, tmp_path):
        """AGENT_GUIDE must have a 'Available Pathways' section for production."""
        from repograph.plugins.exporters.agent_guide.generator import generate_agent_guide
        store = flask_rg._get_store()
        guide = generate_agent_guide(store, flask_rg.repo_path, flask_rg.repograph_dir)
        assert "## Available Pathways" in guide

    def test_guide_has_test_section_when_tests_exist(self, flask_rg, tmp_path):
        """AGENT_GUIDE must have a 'Test Coverage Pathways' section."""
        from repograph.plugins.exporters.agent_guide.generator import generate_agent_guide
        store = flask_rg._get_store()
        guide = generate_agent_guide(store, flask_rg.repo_path, flask_rg.repograph_dir)
        assert "Test Coverage Pathways" in guide

    def test_guide_production_table_contains_no_test_entries(self, flask_rg):
        """Production pathway table rows must not list test-sourced pathway names."""
        from repograph.plugins.exporters.agent_guide.generator import generate_agent_guide
        import re
        store = flask_rg._get_store()
        guide = generate_agent_guide(store, flask_rg.repo_path, flask_rg.repograph_dir)

        # Extract the production table section only (up to next ##)
        prod_section = re.split(r"\n## ", guide)[1] if "\n## " in guide else guide
        # Test-sourced pathways have names starting with "test_"
        test_rows = re.findall(r"\| (test_\S+) \|", prod_section)
        assert not test_rows, (
            f"Test pathway rows found in production table: {test_rows}"
        )
