"""Shared pytest configuration for RepoGraph tests (fixtures only).

If ``.repograph/conftest.py`` was written by ``repograph trace install``, pytest
loads it and starts/stops :class:`~repograph.runtime.tracer.SysTracer` for the
whole session (see the generated file’s docstring). This module does not install
tracing; normal RepoGraph runtime capture happens through ``repograph sync --full``.
Run ``repograph trace install`` only when you intentionally want a manual traced
pytest session, or delete ``.repograph/conftest.py`` to remove it.
"""
from __future__ import annotations

import os

import pytest

PYTHON_SIMPLE_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "fixtures", "python_simple"),
)
PYTHON_FLASK_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "fixtures", "python_flask"),
)
JS_EXPRESS_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "fixtures", "js_express"),
)
STRAYRATZ_FIXTURE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "fixtures", "StrayRatz"),
)


@pytest.fixture
def python_simple_fixture_dir() -> str:
    """Absolute path to ``tests/fixtures/python_simple``."""
    return PYTHON_SIMPLE_FIXTURE


@pytest.fixture
def simple_store(tmp_path):
    """Run full pipeline on ``python_simple`` and return an open :class:`GraphStore`."""
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    rg_dir = str(tmp_path / ".repograph")
    config = RunConfig(
        repo_root=PYTHON_SIMPLE_FIXTURE,
        repograph_dir=rg_dir,
        include_git=False,
        include_embeddings=False,
        full=True,
    )
    run_full_pipeline(config)
    db = os.path.join(rg_dir, "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    yield store
    store.close()


@pytest.fixture
def flask_store(tmp_path):
    """Run full pipeline on ``python_flask`` and return an open :class:`GraphStore`."""
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    rg_dir = str(tmp_path / ".repograph")
    config = RunConfig(
        repo_root=PYTHON_FLASK_FIXTURE,
        repograph_dir=rg_dir,
        include_git=False,
        include_embeddings=False,
        full=True,
    )
    run_full_pipeline(config)
    db = os.path.join(rg_dir, "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    yield store
    store.close()


@pytest.fixture
def js_express_store(tmp_path):
    """Run full pipeline on ``js_express`` and return an open :class:`GraphStore`."""
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    rg_dir = str(tmp_path / ".repograph")
    config = RunConfig(
        repo_root=JS_EXPRESS_FIXTURE,
        repograph_dir=rg_dir,
        include_git=False,
        include_embeddings=False,
        full=True,
    )
    run_full_pipeline(config)
    db = os.path.join(rg_dir, "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    yield store
    store.close()


@pytest.fixture
def strayratz_fixture_dir() -> str:
    """Absolute path to ``tests/fixtures/StrayRatz``."""
    return STRAYRATZ_FIXTURE


@pytest.fixture
def strayratz_store(tmp_path):
    """Run full pipeline on ``StrayRatz`` and return an open :class:`GraphStore`."""
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    rg_dir = str(tmp_path / ".repograph")
    config = RunConfig(
        repo_root=STRAYRATZ_FIXTURE,
        repograph_dir=rg_dir,
        include_git=False,
        include_embeddings=False,
        full=True,
    )
    run_full_pipeline(config)
    db = os.path.join(rg_dir, "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    yield store
    store.close()
