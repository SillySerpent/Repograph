"""Unit tests for Phase 3 parse — HAS_METHOD edge ordering fix (IMP-07).

Verifies that HAS_METHOD edges are created correctly even when the class and
its methods are defined in the same file.  The bug was that the edge insertion
happened before the Class node was upserted, causing the MATCH to find nothing.

INVARIANT: Uses a real temporary GraphStore (KuzuDB) via run_full_pipeline on
a tiny fixture — no mocking of the graph layer, because the bug was at the DB
interaction level.
"""
from __future__ import annotations

import os
import shutil
import tempfile

import pytest


_FIXTURE_SRC = '''\
"""Fixture for HAS_METHOD ordering test."""


class MyService:
    """A simple service with an init that takes typed params."""

    def __init__(self, config: dict, helper: "HelperClass") -> None:
        self._config = config
        self._helper = helper

    def run(self) -> None:
        pass

    def stop(self) -> None:
        pass


class HelperClass:
    def __init__(self, value: int) -> None:
        self._value = value

    def compute(self) -> int:
        return self._value * 2
'''


def _build_repo(tmp: str) -> None:
    with open(os.path.join(tmp, "service.py"), "w") as f:
        f.write(_FIXTURE_SRC)


def _run_pipeline(repo: str) -> "GraphStore":  # type: ignore[name-defined]
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


@pytest.mark.integration
def test_has_method_edges_exist_after_sync() -> None:
    """After a full pipeline run, HAS_METHOD edges must exist for class methods."""
    repo = tempfile.mkdtemp()
    try:
        _build_repo(repo)
        store = _run_pipeline(repo)
        rows = store.query(
            "MATCH (c:Class)-[:HAS_METHOD]->(f:Function) RETURN c.name, f.name"
        )
        store.close()
        assert rows, "Expected HAS_METHOD edges but found none"
        pairs = {(r[0], r[1]) for r in rows}
        assert ("MyService", "__init__") in pairs
        assert ("MyService", "run") in pairs
        assert ("MyService", "stop") in pairs
        assert ("HelperClass", "__init__") in pairs
        assert ("HelperClass", "compute") in pairs
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.integration
def test_constructor_deps_returns_parameters() -> None:
    """constructor_deps must return typed parameters once HAS_METHOD edges exist."""
    repo = tempfile.mkdtemp()
    try:
        _build_repo(repo)
        store = _run_pipeline(repo)
        result = store.get_constructor_deps("MyService")
        store.close()
        assert result.get("class") == "MyService"
        assert "error" not in result, f"Unexpected error: {result.get('error')}"
        params = result.get("parameters", [])
        assert len(params) == 2, f"Expected 2 params, got {params}"
        param_names = [p["name"] for p in params]
        assert "config" in param_names
        assert "helper" in param_names
        # Type annotations should be extracted from signature
        config_p = next(p for p in params if p["name"] == "config")
        assert config_p["type"] == "dict", f"Expected 'dict', got {config_p['type']!r}"
    finally:
        shutil.rmtree(repo, ignore_errors=True)


@pytest.mark.integration
def test_constructor_deps_unknown_class_returns_empty() -> None:
    """constructor_deps on an unknown class should return gracefully."""
    repo = tempfile.mkdtemp()
    try:
        _build_repo(repo)
        store = _run_pipeline(repo)
        result = store.get_constructor_deps("DoesNotExist")
        store.close()
        # Should return an error dict, not raise
        assert result.get("class") == "DoesNotExist"
        assert result.get("parameters") == [] or "error" in result
    finally:
        shutil.rmtree(repo, ignore_errors=True)
