"""Unit tests for shared pathway BFS and cross-language filtering."""
from __future__ import annotations

from repograph.plugins.static_analyzers.pathways.pathway_bfs import (
    bfs_pathway_function_ids,
    language_family,
    should_skip_cross_language_step,
)


def test_language_family() -> None:
    assert language_family("src/a.py") == "python"
    assert language_family("x.ts") == "web"
    assert language_family("x.jsx") == "web"


def test_should_skip_cross_language_python_to_js() -> None:
    assert should_skip_cross_language_step("a.py", "static/x.js") is True
    assert should_skip_cross_language_step("a.py", "b.py") is False


def test_bfs_skips_js_from_python_entry() -> None:
    functions_by_id = {
        "a": {"id": "a", "file_path": "entry.py"},
        "b": {"id": "b", "file_path": "child.py"},
        "j": {"id": "j", "file_path": "bundle.js"},
    }
    outgoing = {
        "a": [
            {"to": "b", "confidence": 1.0},
            {"to": "j", "confidence": 0.99},
        ],
        "b": [],
        "j": [],
    }
    steps = bfs_pathway_function_ids(
        "a",
        outgoing,
        functions_by_id,
        "entry.py",
    )
    assert "j" not in steps
    assert "b" in steps
