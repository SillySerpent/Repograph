"""Tests for entry-caller rollup from superclass methods."""
from __future__ import annotations

from unittest.mock import MagicMock

from repograph.plugins.static_analyzers.dead_code.plugin import (
    _base_method_id as get_in_repo_base_method_id_for_override,
    rollup_override_incoming_callers,
)


def _mock_store_hierarchy() -> MagicMock:
    store = MagicMock()
    store.get_all_functions.return_value = [
        {"id": "base.on_tick", "qualified_name": "Base.on_tick", "file_path": "b.py"},
        {"id": "sub.on_tick", "qualified_name": "Sub.on_tick", "file_path": "s.py"},
    ]
    store.get_all_classes.return_value = [
        {
            "id": "cid_sub",
            "file_path": "s.py",
            "qualified_name": "Sub",
            "name": "Sub",
            "base_names": ["Base"],
        },
        {
            "id": "cid_base",
            "file_path": "b.py",
            "qualified_name": "Base",
            "name": "Base",
            "base_names": [],
        },
    ]
    store.query.return_value = []
    return store


def test_get_base_method_id_via_base_names() -> None:
    store = _mock_store_hierarchy()

    parent = get_in_repo_base_method_id_for_override(
        {"id": "sub.on_tick", "qualified_name": "Sub.on_tick", "file_path": "s.py"},
        store,
    )
    assert parent == "base.on_tick"


def test_rollup_adds_base_callers_to_subclass_override() -> None:
    store = _mock_store_hierarchy()

    caller_counts = {"sub.on_tick": 0, "base.on_tick": 3}
    rollup_override_incoming_callers(store, caller_counts)
    assert caller_counts["sub.on_tick"] == 3
