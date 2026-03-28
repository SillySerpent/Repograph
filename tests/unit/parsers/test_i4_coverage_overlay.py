"""Tests for Block I4 — pytest-cov coverage overlay plugin."""
from __future__ import annotations

import json
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fn(fn_id: str, name: str, file_path: str, line_start: int = 1, line_end: int = 10):
    from repograph.core.models import FunctionNode
    return FunctionNode(
        id=fn_id, name=name, qualified_name=name,
        file_path=file_path, line_start=line_start, line_end=line_end,
        signature=f"def {name}()", docstring=None,
        is_method=False, is_async=False, is_exported=True,
        decorators=[], param_names=[], return_type=None, source_hash="x",
    )


def _open_store(tmp_path: Path, db_name: str = "g.db"):
    from repograph.graph_store.store import GraphStore
    store = GraphStore(str(tmp_path / db_name))
    store.initialize_schema()
    return store


def _write_coverage_json(tmp_path: Path, data: dict) -> str:
    p = tmp_path / "coverage.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def _coverage_json(file_path: str, executed: list[int], missing: list[int] | None = None) -> dict:
    return {
        "meta": {"version": "7.0.0"},
        "files": {
            file_path: {
                "executed_lines": executed,
                "missing_lines": missing or [],
            }
        },
    }


# ---------------------------------------------------------------------------
# I4.1 apply_coverage_json — basic correctness
# ---------------------------------------------------------------------------


def test_covered_function_marked_is_covered_true(tmp_path):
    """A function whose body lines are all executed must have is_covered=True."""
    from repograph.plugins.dynamic_analyzers.coverage_overlay.plugin import apply_coverage_json

    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/a::foo", "foo", "app/a.py", line_start=1, line_end=5)
    store.upsert_function(fn)

    cov_path = _write_coverage_json(
        tmp_path,
        _coverage_json("app/a.py", executed=[2, 3, 4, 5]),
    )
    stats = apply_coverage_json(store, coverage_json_path=cov_path)

    rows = store.query("MATCH (f:Function {id: $id}) RETURN f.is_covered", {"id": fn.id})
    assert rows and rows[0][0] is True, "Function with covered body must have is_covered=True"
    assert stats["covered"] == 1
    assert stats["total"] == 1
    store.close()


def test_uncovered_function_marked_is_covered_false(tmp_path):
    """A function whose body lines are all missing must have is_covered=False."""
    from repograph.plugins.dynamic_analyzers.coverage_overlay.plugin import apply_coverage_json

    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/a::foo", "foo", "app/a.py", line_start=10, line_end=20)
    store.upsert_function(fn)

    cov_path = _write_coverage_json(
        tmp_path,
        _coverage_json("app/a.py", executed=[1, 2, 3], missing=list(range(11, 21))),
    )
    stats = apply_coverage_json(store, coverage_json_path=cov_path)

    rows = store.query("MATCH (f:Function {id: $id}) RETURN f.is_covered", {"id": fn.id})
    assert rows and rows[0][0] is False, "Function with uncovered body must have is_covered=False"
    assert stats["uncovered"] == 1
    store.close()


def test_multiple_functions_correctly_classified(tmp_path):
    """Two functions in the same file are classified independently."""
    from repograph.plugins.dynamic_analyzers.coverage_overlay.plugin import apply_coverage_json

    store = _open_store(tmp_path)
    fn1 = _make_fn("fn::app/a::covered", "covered", "app/a.py", line_start=1, line_end=5)
    fn2 = _make_fn("fn::app/a::uncovered", "uncovered", "app/a.py", line_start=10, line_end=15)
    store.upsert_function(fn1)
    store.upsert_function(fn2)

    cov_path = _write_coverage_json(
        tmp_path,
        _coverage_json("app/a.py", executed=[2, 3, 4, 5]),
    )
    stats = apply_coverage_json(store, coverage_json_path=cov_path)

    rows = {
        r[0]: r[1]
        for r in store.query(
            "MATCH (f:Function) WHERE f.id IN $ids RETURN f.id, f.is_covered",
            {"ids": [fn1.id, fn2.id]},
        )
    }
    assert rows.get(fn1.id) is True, "covered function must have is_covered=True"
    assert rows.get(fn2.id) is False, "uncovered function must have is_covered=False"
    assert stats["covered"] == 1
    assert stats["uncovered"] == 1
    store.close()


def test_function_not_in_coverage_file_marked_false(tmp_path):
    """A function whose file is absent from coverage.json gets is_covered=False."""
    from repograph.plugins.dynamic_analyzers.coverage_overlay.plugin import apply_coverage_json

    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/b::func", "func", "app/b.py", line_start=1, line_end=5)
    store.upsert_function(fn)

    # coverage.json only covers app/a.py, not app/b.py
    cov_path = _write_coverage_json(
        tmp_path,
        _coverage_json("app/a.py", executed=[1, 2, 3]),
    )
    stats = apply_coverage_json(store, coverage_json_path=cov_path)

    rows = store.query("MATCH (f:Function {id: $id}) RETURN f.is_covered", {"id": fn.id})
    assert rows and rows[0][0] is False, (
        "Function in uncovered file must have is_covered=False"
    )
    store.close()


def test_coverage_pct_in_stats(tmp_path):
    """Stats dict must include coverage_pct as a float 0–100."""
    from repograph.plugins.dynamic_analyzers.coverage_overlay.plugin import apply_coverage_json

    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/a::foo", "foo", "app/a.py", line_start=1, line_end=5)
    store.upsert_function(fn)

    cov_path = _write_coverage_json(
        tmp_path,
        _coverage_json("app/a.py", executed=[2, 3, 4, 5]),
    )
    stats = apply_coverage_json(store, coverage_json_path=cov_path)

    assert "coverage_pct" in stats
    assert 0.0 <= stats["coverage_pct"] <= 100.0
    store.close()


def test_empty_coverage_json_no_crash(tmp_path):
    """An empty files dict in coverage.json must return safely without raising."""
    from repograph.plugins.dynamic_analyzers.coverage_overlay.plugin import apply_coverage_json

    store = _open_store(tmp_path)
    cov_path = _write_coverage_json(tmp_path, {"meta": {}, "files": {}})
    stats = apply_coverage_json(store, coverage_json_path=cov_path)

    assert stats["total"] == 0
    store.close()


def test_partial_body_coverage_counts_as_covered(tmp_path):
    """A function with at least one executed body line counts as covered."""
    from repograph.plugins.dynamic_analyzers.coverage_overlay.plugin import apply_coverage_json

    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/a::partial", "partial", "app/a.py", line_start=1, line_end=10)
    store.upsert_function(fn)

    # Only line 5 is executed — still counts as covered
    cov_path = _write_coverage_json(
        tmp_path,
        _coverage_json("app/a.py", executed=[5]),
    )
    apply_coverage_json(store, coverage_json_path=cov_path)

    rows = store.query("MATCH (f:Function {id: $id}) RETURN f.is_covered", {"id": fn.id})
    assert rows and rows[0][0] is True, (
        "Partial coverage (≥1 executed body line) must count as covered"
    )
    store.close()


# ---------------------------------------------------------------------------
# I4.2 plugin via on_traces_collected hook
# ---------------------------------------------------------------------------


def test_plugin_analyze_with_coverage_json(tmp_path):
    """CoverageOverlayPlugin.analyze() must process coverage.json when present."""
    from repograph.plugins.dynamic_analyzers.coverage_overlay.plugin import CoverageOverlayPlugin

    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/a::foo", "foo", "app/a.py", line_start=1, line_end=5)
    store.upsert_function(fn)

    cov_path = _write_coverage_json(
        tmp_path,
        _coverage_json("app/a.py", executed=[2, 3, 4, 5]),
    )
    plugin = CoverageOverlayPlugin()
    result = plugin.analyze(
        store=store,
        repo_root=str(tmp_path),
        coverage_json_path=cov_path,
    )

    assert "coverage_stats" in result
    assert result["coverage_stats"]["covered"] == 1
    store.close()


def test_plugin_analyze_missing_coverage_json_returns_empty(tmp_path):
    """plugin.analyze() with no coverage.json must return {} without raising."""
    from repograph.plugins.dynamic_analyzers.coverage_overlay.plugin import CoverageOverlayPlugin

    store = _open_store(tmp_path)
    plugin = CoverageOverlayPlugin()
    result = plugin.analyze(store=store, repo_root=str(tmp_path))
    assert result == {}
    store.close()


# ---------------------------------------------------------------------------
# I4.3 schema migration: is_covered column exists after initialize_schema
# ---------------------------------------------------------------------------


def test_is_covered_column_added_by_migration(tmp_path):
    """initialize_schema() must add the is_covered column (v1.7 migration)."""
    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/a::foo", "foo", "app/a.py")
    store.upsert_function(fn)
    store.update_function_coverage(fn.id, is_covered=True)
    rows = store.query("MATCH (f:Function {id: $id}) RETURN f.is_covered", {"id": fn.id})
    assert rows and rows[0][0] is True
    store.close()
