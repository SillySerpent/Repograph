"""Ensure interactive TUI entrypoints import without side effects."""
from __future__ import annotations


def test_interactive_main_module_imports() -> None:
    from repograph.interactive import main as interactive_main

    assert hasattr(interactive_main, "main")


def test_graph_queries_module_imports() -> None:
    from repograph.interactive import graph_queries

    assert graph_queries is not None
