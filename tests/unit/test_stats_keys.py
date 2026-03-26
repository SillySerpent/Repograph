"""Unit tests for get_stats() key naming — no typos, correct plurals."""
from __future__ import annotations

import os
import shutil
import pytest

FLASK_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_flask")
)


@pytest.fixture(scope="module")
def flask_stats(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("stats")
    repo = str(tmp / "repo")
    rg_dir = str(tmp / ".repograph")
    shutil.copytree(FLASK_FIXTURE, repo)
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg_dir,
        include_git=False, full=True,
    ))
    from repograph.graph_store.store import GraphStore
    store = GraphStore(os.path.join(rg_dir, "graph.db"))
    store.initialize_schema()
    stats = store.get_stats()
    store.close()
    return stats


class TestStatKeyNames:
    def test_no_typo_classs(self, flask_stats):
        assert "classs" not in flask_stats, "Typo 'classs' still present"

    def test_no_typo_communitys(self, flask_stats):
        assert "communitys" not in flask_stats, "Typo 'communitys' still present"

    def test_correct_key_classes(self, flask_stats):
        assert "classes" in flask_stats, "'classes' key missing from stats"

    def test_correct_key_communities(self, flask_stats):
        assert "communities" in flask_stats, "'communities' key missing from stats"

    def test_all_expected_keys_present(self, flask_stats):
        expected = {"files", "classes", "variables", "imports",
                    "pathways", "communities", "functions"}
        missing = expected - flask_stats.keys()
        assert not missing, f"Missing stat keys: {missing}"

    def test_all_values_are_non_negative_ints(self, flask_stats):
        for k, v in flask_stats.items():
            assert isinstance(v, int) and v >= 0, \
                f"Stat '{k}' has invalid value: {v!r}"
