"""Regression test: RepoGraph entry points when analysing its own package."""
from __future__ import annotations

import os
import shutil

import pytest

REPOGRAPH_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture(scope="module")
def self_rg(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("self_analysis")
    repo = str(tmp / "repograph")
    shutil.copytree(
        REPOGRAPH_SRC,
        repo,
        ignore=shutil.ignore_patterns(".repograph", "__pycache__", "*.egg-info"),
    )
    rg_dir = os.path.join(repo, ".repograph")
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    run_full_pipeline(
        RunConfig(
            repo_root=repo,
            repograph_dir=rg_dir,
            include_git=False,
            full=True,
        )
    )
    from repograph.api import RepoGraph

    rg = RepoGraph(repo, repograph_dir=rg_dir)
    yield rg
    rg.close()


class TestSelfEntryPoints:
    def test_run_full_pipeline_is_in_top_entry_points(self, self_rg):
        eps = self_rg.entry_points(limit=50)
        names = [ep["qualified_name"].split(".")[-1] for ep in eps]
        assert "run_full_pipeline" in names, (
            f"run_full_pipeline missing from entry points: {names[:15]}"
        )

    def test_pipeline_phase_run_not_above_orchestrator(self, self_rg):
        eps = self_rg.entry_points(limit=50)
        orchestrator_rank = next(
            (
                i
                for i, ep in enumerate(eps)
                if ep["qualified_name"].endswith("run_full_pipeline")
            ),
            999,
        )
        phase_run_ranks = [
            i
            for i, ep in enumerate(eps)
            if ep["qualified_name"].endswith(".run")
            and "phases" in ep.get("file_path", "")
        ]
        if phase_run_ranks:
            assert orchestrator_rank < min(phase_run_ranks), (
                "run_full_pipeline must rank above individual phase run() functions"
            )
