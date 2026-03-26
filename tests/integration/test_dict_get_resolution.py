"""Regression: ``cfg.get`` must not resolve to ``FlagStore.get``."""
from __future__ import annotations

import os
import shutil

import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "dict_get_collision"
)


@pytest.fixture()
def dict_get_repo(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo / "pkg")
    return str(repo)


def test_cfg_get_not_linked_to_flagstore_get(dict_get_repo, tmp_path):
    from repograph.config import repograph_dir
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    rg = repograph_dir(dict_get_repo)
    cfg = RunConfig(
        repo_root=dict_get_repo,
        repograph_dir=rg,
        include_git=False,
        full=True,
    )
    run_full_pipeline(cfg)

    db_path = os.path.join(rg, "graph.db")
    from repograph.graph_store.store import GraphStore

    store = GraphStore(db_path)
    store.initialize_schema()
    edges = store.get_all_call_edges()
    bad = [
        e for e in edges
        if "FlagStore.get" in e["to"] and "use_cfg_get" in e["from"]
    ]
    assert not bad, f"false positive CALLS cfg.get → FlagStore.get: {bad}"

    good = [e for e in edges if "FlagStore.get" in e["to"] and "use_flag_store" in e["from"]]
    assert good, "expected CALLS from use_flag_store → FlagStore.get"
