"""Regression: typed-local ``obj.method`` vs same-named import (Phase 5)."""
from __future__ import annotations

import os
import shutil

import pytest

FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "fixtures", "name_collision")
)


def _full_run(repo: str, rg_dir: str):
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    return run_full_pipeline(
        RunConfig(
            repo_root=repo,
            repograph_dir=rg_dir,
            include_git=False,
            include_embeddings=False,
            full=True,
        )
    )


def test_typed_local_method_wins_over_same_named_import(tmp_path):
    """``w.flush()`` must resolve to Widget.flush, not imported ``flush``."""
    repo = str(tmp_path / "repo")
    rg_dir = str(tmp_path / ".repograph")
    shutil.copytree(FIXTURE, repo)

    _full_run(repo, rg_dir)

    from repograph.graph_store.store import GraphStore

    store = GraphStore(os.path.join(rg_dir, "graph.db"))
    store.initialize_schema()

    rows = store.query(
        "MATCH (caller:Function {name: 'run'})-[e:CALLS]->(callee:Function) "
        "WHERE callee.name = 'flush' "
        "RETURN callee.qualified_name, callee.file_path, e.reason "
        "ORDER BY callee.file_path"
    )
    store.close()

    quals = {r[0] for r in rows}
    assert "Widget.flush" in quals, f"expected Widget.flush in callees, got {quals}"
    worker_hits = [r for r in rows if r[1].endswith("worker.py")]
    method_hits = [r for r in rows if r[1].endswith("app.py")]
    assert worker_hits, "expected imported worker.flush to be called"
    assert all(r[2] == "import_resolved" for r in worker_hits), worker_hits
    assert method_hits, "expected Widget.flush to be called"
    # Attribute call may be method_call (single candidate in file) or typed_local
    assert all(r[2] != "import_resolved" for r in method_hits), method_hits
