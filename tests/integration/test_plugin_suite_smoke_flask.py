"""Plugin smoke on the larger ``python_flask`` fixture (routes, services, tests).

One module-scoped sync; runs demand + export loops to catch regressions that only
appear on multi-file Flask-style trees.
"""
from __future__ import annotations

import os
import shutil

import pytest

from repograph.plugins.discovery import DEMAND_ANALYZER_ORDER, EXPORTER_ORDER

pytestmark = [pytest.mark.integration, pytest.mark.plugin]

_ROOT = os.path.dirname(os.path.dirname(__file__))
_PYTHON_FLASK = os.path.abspath(os.path.join(_ROOT, "fixtures", "python_flask"))


@pytest.fixture(scope="module")
def plugin_smoke_flask_repo(tmp_path_factory):
    from repograph.graph_store.store import GraphStore
    from repograph.pipeline.runner import RunConfig, run_full_pipeline

    tmp = tmp_path_factory.mktemp("plugin_smoke_flask")
    repo = str(tmp / "repo")
    shutil.copytree(_PYTHON_FLASK, repo)
    rg_dir = str(tmp / ".repograph")
    run_full_pipeline(
        RunConfig(
            repo_root=repo,
            repograph_dir=rg_dir,
            include_git=False,
            include_embeddings=False,
            full=True,
        )
    )
    db = os.path.join(rg_dir, "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    return repo, rg_dir, store


def test_demand_and_exporters_on_flask_graph(plugin_smoke_flask_repo) -> None:
    repo, rg_dir, _store = plugin_smoke_flask_repo
    from repograph.surfaces.api import RepoGraph

    with RepoGraph(repo, repograph_dir=rg_dir) as rg:
        for name in DEMAND_ANALYZER_ORDER:
            pid = f"demand_analyzer.{name}"
            out = rg.run_analyzer_plugin(pid)
            assert isinstance(out, list), pid
        for name in EXPORTER_ORDER:
            pid = f"exporter.{name}"
            out = rg.run_exporter_plugin(pid)
            assert out is not None, pid
