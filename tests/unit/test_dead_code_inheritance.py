"""Dead-code inheritance hints — generic graph fixtures."""
from __future__ import annotations

from typing import cast

from repograph.graph_store.store import GraphStore
from repograph.plugins.static_analyzers.dead_code.plugin import (
    method_may_be_invoked_via_superclass_chain,
)


def test_no_crash_on_empty_qualified_name() -> None:
    assert not method_may_be_invoked_via_superclass_chain(
        {"qualified_name": ""}, cast(GraphStore, _FakeStore())
    )


class _FakeStore:
    def get_all_classes(self):
        return []

    def get_all_functions(self):
        return []

    def query(self, *a, **k):
        return []
