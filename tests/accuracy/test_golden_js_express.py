"""Golden expectations for the ``js_express`` fixture (JS pipeline regression)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.accuracy


def test_js_express_stable_surface(js_express_store) -> None:
    """Key JS symbols and graph shape aligned with integration tests."""
    stats = js_express_store.get_stats()
    assert stats["files"] >= 4

    fns = js_express_store.get_all_functions()
    names = {f["name"] for f in fns}
    assert {"loginHandler", "searchEndpoint", "validateCredentials"}.issubset(names)

    edges = js_express_store.get_all_call_edges()
    assert len(edges) >= 1

    pathways = js_express_store.get_all_pathways()
    assert len(pathways) >= 1
