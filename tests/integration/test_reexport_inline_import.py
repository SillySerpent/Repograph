"""Integration tests for RG-01: dynamic/inline import call edge resolution.

Two scenarios are tested:

1. Simple case (existing): ``from callee import fn`` inside a function body
   creates a CALLS edge and fn is not flagged dead.

2. Re-export case (new): ``from module_a import fn`` where ``fn`` is defined
   in ``module_b`` but re-exported through ``module_a``'s own imports.
   This is the pattern that caused ``_delete_db_dir`` to be incorrectly
   flagged as dead in self-analysis.

INVARIANT: Both tests use real pipeline runs on tiny fixture repos.
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CALLEE_SRC = '''\
"""Defines the function that will be re-exported."""

def the_real_function() -> str:
    return "from callee"
'''

_REEXPORTER_SRC = '''\
"""Re-exports the_real_function from callee — mirrors the store.py/_delete_db_dir pattern."""
from callee import the_real_function  # noqa: F401 — re-export

__all__ = ["the_real_function"]
'''

_CALLER_SRC = '''\
"""Calls the function via the re-exporting module (inline import inside function)."""


def run_task() -> None:
    from reexporter import the_real_function  # inline import, re-exported symbol
    the_real_function()
'''


def _build_reexport_repo(tmp: str) -> None:
    for name, src in [
        ("callee.py", _CALLEE_SRC),
        ("reexporter.py", _REEXPORTER_SRC),
        ("caller.py", _CALLER_SRC),
    ]:
        with open(os.path.join(tmp, name), "w") as f:
            f.write(src)


def _run_pipeline(repo: str):
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    rg = os.path.join(repo, ".repograph")
    os.makedirs(rg, exist_ok=True)
    run_full_pipeline(RunConfig(
        repo_root=repo, repograph_dir=rg,
        include_git=False, include_embeddings=False, full=True,
    ))
    store = GraphStore(os.path.join(rg, "graph.db"))
    store.initialize_schema()
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_direct_inline_import_creates_call_edge() -> None:
    """Simple inline import (from callee import fn; fn()) creates a CALLS edge."""
    repo = tempfile.mkdtemp()
    try:
        # Use the existing dynamic_import fixture
        fixture = os.path.join(
            os.path.dirname(__file__), "..", "fixtures", "dynamic_import"
        )
        for name in ("caller.py", "callee.py"):
            shutil.copy2(os.path.join(fixture, name), os.path.join(repo, name))

        store = _run_pipeline(repo)
        rows = store.query(
            "MATCH (c:Function)-[e:CALLS]->(d:Function {name: 'imported_fn'}) "
            "RETURN c.name, e.reason, e.confidence"
        )
        store.close()
        assert rows, "Expected CALLS edge for direct inline import"
        # Accept any valid resolution reason — Phase 4 writes 'inline_import',
        # Phase 5 may also resolve it as 'import_resolved' or 'direct_call'.
        # The key invariant is that a high-confidence edge exists (>= 0.5).
        reasons = {r[1] for r in rows}
        confs = [r[2] for r in rows]
        assert reasons & {"inline_import", "import_resolved", "direct_call"}, \
            f"Unexpected reasons: {reasons}"
        assert any(c >= 0.5 for c in confs), f"Confidence too low: {confs}"
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.integration
def test_reexport_inline_import_creates_call_edge() -> None:
    """Re-exported symbol reachable via inline import must create a CALLS edge.

    This tests the fix for _delete_db_dir: it lives in store_utils.py but is
    imported (and thus re-exported) through store.py.  The inline import resolver
    must follow one level of re-export to find the actual defining file.
    """
    repo = tempfile.mkdtemp()
    try:
        _build_reexport_repo(repo)
        store = _run_pipeline(repo)
        rows = store.query(
            "MATCH (c:Function)-[:CALLS]->(d:Function {name: 'the_real_function'}) "
            "RETURN c.name, d.name"
        )
        store.close()
        assert rows, (
            "Expected CALLS edge from run_task to the_real_function via re-export chain. "
            "This is the _delete_db_dir pattern."
        )
        callers = {r[0] for r in rows}
        assert "run_task" in callers
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.integration
def test_reexported_function_not_flagged_dead() -> None:
    """A re-exported function that is called via inline import must not be dead."""
    repo = tempfile.mkdtemp()
    try:
        _build_reexport_repo(repo)
        store = _run_pipeline(repo)
        dead = store.get_dead_functions()
        store.close()
        dead_names = {d["qualified_name"] for d in dead}
        assert "the_real_function" not in dead_names, (
            f"the_real_function was incorrectly flagged dead. Dead list: {dead_names}"
        )
    finally:
        shutil.rmtree(repo, ignore_errors=True)
