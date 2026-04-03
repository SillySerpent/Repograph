"""Coverage metric wording and full_report wiring."""
from __future__ import annotations

import os
import shutil

import pytest

from repograph.graph_store.store_queries_entrypoints import (
    ENTRY_POINT_TEST_COVERAGE_DEFINITION,
)

FLASK_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
)


@pytest.fixture(scope="module")
def flask_rg(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cov_sem")
    repo = str(tmp / "repo")
    rg_dir = str(tmp / ".repograph")
    shutil.copytree(FLASK_FIXTURE, repo)
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    run_full_pipeline(
        RunConfig(
            repo_root=repo,
            repograph_dir=rg_dir,
            include_git=False,
            full=True,
        )
    )
    from repograph.surfaces.api import RepoGraph

    with RepoGraph(repo, repograph_dir=rg_dir) as rg:
        yield rg


class TestCoverageSemantics:
    def test_constant_non_empty(self):
        assert "CALLS" in ENTRY_POINT_TEST_COVERAGE_DEFINITION
        assert "is_test" in ENTRY_POINT_TEST_COVERAGE_DEFINITION

    def test_full_report_has_definition_and_list(self, flask_rg):
        report = flask_rg.full_report(max_pathways=2, max_dead=2)
        assert report["coverage_definition"] == ENTRY_POINT_TEST_COVERAGE_DEFINITION
        assert isinstance(report["test_coverage"], list)

    def test_api_property_matches(self, flask_rg):
        assert flask_rg.coverage_definition == ENTRY_POINT_TEST_COVERAGE_DEFINITION
