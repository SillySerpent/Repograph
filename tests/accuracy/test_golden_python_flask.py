"""Golden expectations for the ``python_flask`` fixture (regression on routes + services)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.accuracy


def test_python_flask_stable_surface(flask_store) -> None:
    """Symbols and structure we rely on for Flask-style integration demos."""
    stats = flask_store.get_stats()
    assert stats["files"] >= 5

    fns = flask_store.get_all_functions()
    names = {f["name"] for f in fns}
    assert {"login_handler", "validate_credentials", "search_endpoint"}.issubset(names)

    edges = flask_store.get_all_call_edges()
    assert len(edges) >= 1

    pathways = flask_store.get_all_pathways()
    assert len(pathways) >= 1

    eps = flask_store.get_entry_points(limit=5)
    assert len(eps) >= 1
    for ep in eps:
        assert ep.get("entry_score", 0) > 0
