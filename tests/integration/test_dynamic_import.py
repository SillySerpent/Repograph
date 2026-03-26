"""RG-01: inline ``from M import f`` inside functions creates CALLS edges."""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "dynamic_import"
)


@pytest.mark.integration
def test_inline_import_not_flagged_dead() -> None:
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    repo = tempfile.mkdtemp()
    rg = os.path.join(repo, ".repograph")
    os.makedirs(rg, exist_ok=True)
    try:
        for name in ("caller.py", "callee.py"):
            shutil.copy2(os.path.join(FIXTURE, name), os.path.join(repo, name))

        run_full_pipeline(
            RunConfig(
                repo_root=repo,
                repograph_dir=rg,
                include_git=False,
                include_embeddings=False,
                full=True,
            )
        )

        store = GraphStore(os.path.join(rg, "graph.db"))
        store.initialize_schema()
        rows = store.query(
            "MATCH (c:Function)-[e:CALLS]->(d:Function {name: 'imported_fn'}) "
            "RETURN c.name, e.reason"
        )
        store.close()
        assert rows, "expected CALLS edge to imported_fn"
        reasons = {r[1] for r in rows}
        assert "inline_import" in reasons or "import_resolved" in reasons or "direct_call" in reasons
    finally:
        shutil.rmtree(repo, ignore_errors=True)
