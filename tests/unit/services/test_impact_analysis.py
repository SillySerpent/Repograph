"""Tests for Block I1 — change impact scoring service."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fn(fn_id: str, name: str, file_path: str):
    from repograph.core.models import FunctionNode
    return FunctionNode(
        id=fn_id, name=name, qualified_name=name,
        file_path=file_path, line_start=1, line_end=5,
        signature=f"def {name}()", docstring=None,
        is_method=False, is_async=False, is_exported=True,
        decorators=[], param_names=[], return_type=None, source_hash="x",
    )


def _edge(from_id: str, to_id: str, line: int = 1, confidence: float = 0.9):
    from repograph.core.models import CallEdge
    return CallEdge(
        from_function_id=from_id, to_function_id=to_id,
        call_site_line=line, argument_names=[], confidence=confidence, reason="static",
    )


def _open_store(tmp_path: Path, db_name: str = "g.db"):
    from repograph.graph_store.store import GraphStore
    store = GraphStore(str(tmp_path / db_name))
    store.initialize_schema()
    return store


# ---------------------------------------------------------------------------
# I1.1 compute_impact — basic correctness
# ---------------------------------------------------------------------------


def test_compute_impact_empty_paths_returns_empty():
    """compute_impact with no changed paths must return an empty list."""
    from repograph.services.impact_analysis import compute_impact

    store = MagicMock()
    results = compute_impact(store, changed_paths=[])
    assert results == []


def test_compute_impact_direct_changed_functions_at_hop_0(tmp_path):
    """Functions in changed files appear at hop=0."""
    from repograph.services.impact_analysis import compute_impact

    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/a::foo", "foo", "app/a.py")
    store.upsert_function(fn)

    results = compute_impact(store, changed_paths=["app/a.py"])
    assert len(results) >= 1
    direct = [r for r in results if r.hop == 0]
    assert any(r.fn_id == "fn::app/a::foo" for r in direct), (
        "Function in changed file must appear at hop=0"
    )
    store.close()


def test_compute_impact_callers_at_hop_1(tmp_path):
    """Direct callers of changed functions appear at hop=1."""
    from repograph.services.impact_analysis import compute_impact

    store = _open_store(tmp_path)
    callee = _make_fn("fn::app/a::target", "target", "app/a.py")
    caller = _make_fn("fn::app/b::caller", "caller", "app/b.py")
    store.upsert_function(callee)
    store.upsert_function(caller)
    store.insert_call_edge(_edge(caller.id, callee.id, line=10))

    results = compute_impact(store, changed_paths=["app/a.py"])
    hops = {r.fn_id: r.hop for r in results}

    assert "fn::app/a::target" in hops, "Changed function must be in results"
    assert "fn::app/b::caller" in hops, "Direct caller must be in results"
    assert hops["fn::app/b::caller"] == 1, "Direct caller must be at hop=1"
    store.close()


def test_compute_impact_transitive_callers(tmp_path):
    """Transitive callers (hop=2) are included within max_hops."""
    from repograph.services.impact_analysis import compute_impact

    store = _open_store(tmp_path)
    fn_a = _make_fn("fn::app/a::base", "base", "app/a.py")
    fn_b = _make_fn("fn::app/b::middle", "middle", "app/b.py")
    fn_c = _make_fn("fn::app/c::top", "top", "app/c.py")
    store.upsert_function(fn_a)
    store.upsert_function(fn_b)
    store.upsert_function(fn_c)
    store.insert_call_edge(_edge(fn_b.id, fn_a.id, line=5))
    store.insert_call_edge(_edge(fn_c.id, fn_b.id, line=7))

    results = compute_impact(store, changed_paths=["app/a.py"])
    hops = {r.fn_id: r.hop for r in results}

    assert hops.get("fn::app/c::top") == 2, "Two-hop caller must appear at hop=2"
    store.close()


def test_compute_impact_max_hops_limits_traversal(tmp_path):
    """max_hops=1 must stop traversal after direct callers."""
    from repograph.services.impact_analysis import compute_impact

    store = _open_store(tmp_path)
    fn_a = _make_fn("fn::app/a::base", "base", "app/a.py")
    fn_b = _make_fn("fn::app/b::middle", "middle", "app/b.py")
    fn_c = _make_fn("fn::app/c::top", "top", "app/c.py")
    store.upsert_function(fn_a)
    store.upsert_function(fn_b)
    store.upsert_function(fn_c)
    store.insert_call_edge(_edge(fn_b.id, fn_a.id, line=5))
    store.insert_call_edge(_edge(fn_c.id, fn_b.id, line=7))

    results = compute_impact(store, changed_paths=["app/a.py"], max_hops=1)
    fn_ids = {r.fn_id for r in results}

    assert "fn::app/c::top" not in fn_ids, (
        "Two-hop caller must not appear when max_hops=1"
    )
    store.close()


def test_compute_impact_results_sorted_by_score_descending(tmp_path):
    """Results must be sorted by impact_score descending."""
    from repograph.services.impact_analysis import compute_impact

    store = _open_store(tmp_path)
    fn_a = _make_fn("fn::app/a::base", "base", "app/a.py")
    fn_b = _make_fn("fn::app/b::caller", "caller", "app/b.py")
    store.upsert_function(fn_a)
    store.upsert_function(fn_b)
    store.insert_call_edge(_edge(fn_b.id, fn_a.id, line=5))

    results = compute_impact(store, changed_paths=["app/a.py"])
    scores = [r.impact_score for r in results]
    assert scores == sorted(scores, reverse=True), "Results must be sorted by score descending"
    store.close()


def test_compute_impact_no_duplicate_function_ids(tmp_path):
    """Each function must appear at most once (shortest hop wins)."""
    from repograph.services.impact_analysis import compute_impact

    store = _open_store(tmp_path)
    fn_a = _make_fn("fn::app/a::base", "base", "app/a.py")
    fn_b = _make_fn("fn::app/b::mid", "mid", "app/b.py")
    fn_c = _make_fn("fn::app/c::top", "top", "app/c.py")
    store.upsert_function(fn_a)
    store.upsert_function(fn_b)
    store.upsert_function(fn_c)
    # Two paths to fn_c: direct (hop=1) and via fn_b (hop=2)
    store.insert_call_edge(_edge(fn_b.id, fn_a.id, line=5))
    store.insert_call_edge(_edge(fn_c.id, fn_a.id, line=6))  # direct
    store.insert_call_edge(_edge(fn_c.id, fn_b.id, line=7))  # also via fn_b

    results = compute_impact(store, changed_paths=["app/a.py"])
    fn_ids = [r.fn_id for r in results]
    assert len(fn_ids) == len(set(fn_ids)), "Each function must appear only once"
    store.close()


def test_compute_impact_via_http_flag(tmp_path):
    """Functions reached via MAKES_HTTP_CALL must have via_http=True."""
    from repograph.services.impact_analysis import compute_impact

    store = _open_store(tmp_path)
    py_caller = _make_fn("fn::app/client::call_api", "call_api", "app/client.py")
    js_handler = _make_fn("fn::api/route::handler", "handler", "api/route.ts")
    store.upsert_function(py_caller)
    store.upsert_function(js_handler)
    store.insert_makes_http_call_edge(
        py_caller.id, js_handler.id,
        http_method="POST", url_pattern="/api/users",
        confidence=0.85, reason="http_endpoint_match",
    )

    # Changed file is the JS handler; Python caller should be in results via HTTP
    results = compute_impact(store, changed_paths=["api/route.ts"])
    http_results = [r for r in results if r.via_http]
    assert any(r.fn_id == py_caller.id for r in http_results), (
        "Python caller should appear with via_http=True after JS handler is changed"
    )
    store.close()


# ---------------------------------------------------------------------------
# I1.2 format_impact_table
# ---------------------------------------------------------------------------


def test_format_impact_table_empty():
    from repograph.services.impact_analysis import format_impact_table
    result = format_impact_table([])
    assert "No impacted" in result


def test_format_impact_table_shows_function_names():
    from repograph.services.impact_analysis import ImpactedFunction, format_impact_table

    results = [
        ImpactedFunction(
            fn_id="fn::a", qualified_name="my_module.my_func",
            file_path="app/module.py", hop=1, impact_score=0.75,
        )
    ]
    table = format_impact_table(results)
    assert "my_module.my_func" in table
    assert "0.750" in table


# ---------------------------------------------------------------------------
# I1.3 service method
# ---------------------------------------------------------------------------


def test_service_compute_diff_impact_returns_dicts(tmp_path):
    """RepoGraphService.compute_diff_impact must return list of dicts."""
    from repograph.services.repo_graph_service import RepoGraphService
    from repograph.graph_store.store import GraphStore

    repograph_dir = str(tmp_path / ".repograph")
    os.makedirs(repograph_dir, exist_ok=True)
    store = GraphStore(str(tmp_path / ".repograph" / "graph.db"))
    store.initialize_schema()
    fn = _make_fn("fn::app/a::foo", "foo", "app/a.py")
    store.upsert_function(fn)

    svc = RepoGraphService(repo_path=str(tmp_path), repograph_dir=repograph_dir)
    svc._store = store  # inject pre-opened store

    results = svc.compute_diff_impact(["app/a.py"], max_hops=2)
    assert isinstance(results, list)
    if results:
        r = results[0]
        assert "fn_id" in r
        assert "qualified_name" in r
        assert "hop" in r
        assert "impact_score" in r
    store.close()
