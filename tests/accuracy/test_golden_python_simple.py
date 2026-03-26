"""Golden expectations for the ``python_simple`` fixture (overlaps integration coverage)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.accuracy


def test_python_simple_stable_surface(simple_store) -> None:
    """Key counts and symbols we rely on for demos and docs."""
    stats = simple_store.get_stats()
    assert stats["files"] >= 3

    fns = simple_store.get_all_functions()
    names = {f["name"] for f in fns}
    assert {"run", "find_user", "get_user_display"}.issubset(names)

    dead = simple_store.get_dead_functions()
    dead_tail = {f["qualified_name"].split(":")[-1] for f in dead}
    assert "_unused_helper" in dead_tail

    edges = simple_store.get_all_call_edges()
    assert len(edges) >= 1
