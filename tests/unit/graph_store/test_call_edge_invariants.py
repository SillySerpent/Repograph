"""Tests for CALLS edge confidence invariant and site-line merging.

These tests operate on a fresh in-memory GraphStore (no full pipeline run).
They verify the core invariants documented in insert_call_edge:
  - confidence never decreases
  - confidence increases when a higher value is supplied
  - extra_site_lines JSON parse failure is logged and handled gracefully
  - call-site lines are merged correctly across multiple insertions
  - same (from, to, line) triple produces exactly one edge
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from repograph.core.models import CallEdge, FunctionNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path):
    from repograph.graph_store.store import GraphStore

    db = str(tmp_path / "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    return store


def _fn(fn_id: str) -> FunctionNode:
    return FunctionNode(
        id=fn_id,
        name=fn_id,
        qualified_name=fn_id,
        file_path="test.py",
        line_start=1,
        line_end=5,
        signature=f"def {fn_id}()",
        docstring=None,
        is_method=False,
        is_async=False,
        is_exported=True,
        decorators=[],
        param_names=[],
        return_type=None,
        source_hash="abc123",
    )


def _edge(from_id: str, to_id: str, *, line: int = 10, conf: float = 0.5) -> CallEdge:
    return CallEdge(
        from_function_id=from_id,
        to_function_id=to_id,
        call_site_line=line,
        argument_names=[],
        confidence=conf,
        reason="direct_call",
    )


def _stored_conf(store, from_id: str, to_id: str) -> float | None:
    rows = store.query(
        "MATCH (a:Function {id: $from})-[r:CALLS]->(b:Function {id: $to}) RETURN r.confidence",
        {"from": from_id, "to": to_id},
    )
    return float(rows[0][0]) if rows else None


def _stored_extra_lines(store, from_id: str, to_id: str) -> list[int]:
    rows = store.query(
        "MATCH (a:Function {id: $from})-[r:CALLS]->(b:Function {id: $to}) "
        "RETURN r.call_site_line, r.extra_site_lines",
        {"from": from_id, "to": to_id},
    )
    if not rows:
        return []
    primary = int(rows[0][0])
    raw = rows[0][1]
    try:
        extras = json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        extras = []
    return sorted([primary] + [int(x) for x in extras if x is not None])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_confidence_never_decreases(tmp_path: Path):
    """Inserting an edge with lower confidence must not overwrite a higher one."""
    store = _make_store(tmp_path)
    try:
        store.upsert_function(_fn("caller"))
        store.upsert_function(_fn("callee"))

        store.insert_call_edge(_edge("caller", "callee", conf=0.9))
        assert _stored_conf(store, "caller", "callee") == pytest.approx(0.9)

        # Re-insert with a lower confidence — must keep 0.9
        store.insert_call_edge(_edge("caller", "callee", conf=0.3))
        assert _stored_conf(store, "caller", "callee") == pytest.approx(0.9)
    finally:
        store.close()


def test_confidence_increases_when_higher(tmp_path: Path):
    """Inserting an edge with higher confidence must upgrade to the new value."""
    store = _make_store(tmp_path)
    try:
        store.upsert_function(_fn("caller"))
        store.upsert_function(_fn("callee"))

        store.insert_call_edge(_edge("caller", "callee", conf=0.3))
        assert _stored_conf(store, "caller", "callee") == pytest.approx(0.3)

        # Re-insert with higher confidence — must upgrade to 0.9
        store.insert_call_edge(_edge("caller", "callee", conf=0.9))
        assert _stored_conf(store, "caller", "callee") == pytest.approx(0.9)
    finally:
        store.close()


def test_invariant_with_malformed_extra_list(tmp_path: Path, caplog):
    """When extra_site_lines contains invalid JSON, confidence must be preserved
    and a warning must be logged; no exception must escape."""
    store = _make_store(tmp_path)
    try:
        store.upsert_function(_fn("caller"))
        store.upsert_function(_fn("callee"))

        # Create the edge first
        store.insert_call_edge(_edge("caller", "callee", conf=0.8))
        assert _stored_conf(store, "caller", "callee") == pytest.approx(0.8)

        # Manually corrupt extra_site_lines with invalid JSON
        store._require_conn().execute(
            "MATCH (a:Function {id: 'caller'})-[r:CALLS]->(b:Function {id: 'callee'}) "
            "SET r.extra_site_lines = 'NOT_VALID_JSON'"
        )

        # Insert another edge — must handle the bad JSON gracefully
        with caplog.at_level(logging.WARNING, logger="repograph.graph_store.store_writes_rel"):
            store.insert_call_edge(_edge("caller", "callee", conf=0.8, line=20))

        # Confidence must still be preserved
        assert _stored_conf(store, "caller", "callee") == pytest.approx(0.8)

        # A warning must have been emitted
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("extra_site_lines" in m or "JSON" in m for m in warning_msgs), (
            f"Expected a warning about JSON parse failure; got: {warning_msgs}"
        )
    finally:
        store.close()


def test_extra_site_lines_merging(tmp_path: Path):
    """Call-site lines from multiple insertions must all be preserved."""
    store = _make_store(tmp_path)
    try:
        store.upsert_function(_fn("caller"))
        store.upsert_function(_fn("callee"))

        store.insert_call_edge(_edge("caller", "callee", line=5, conf=0.7))
        store.insert_call_edge(_edge("caller", "callee", line=10, conf=0.7))
        store.insert_call_edge(_edge("caller", "callee", line=15, conf=0.7))

        all_lines = _stored_extra_lines(store, "caller", "callee")
        assert 5 in all_lines
        assert 10 in all_lines
        assert 15 in all_lines
    finally:
        store.close()


def test_deduplication_key(tmp_path: Path):
    """Inserting the same (from, to, line) triple twice must produce one edge."""
    store = _make_store(tmp_path)
    try:
        store.upsert_function(_fn("caller"))
        store.upsert_function(_fn("callee"))

        store.insert_call_edge(_edge("caller", "callee", line=42, conf=0.7))
        store.insert_call_edge(_edge("caller", "callee", line=42, conf=0.7))

        rows = store.query(
            "MATCH (a:Function {id: 'caller'})-[r:CALLS]->(b:Function {id: 'callee'}) "
            "RETURN count(r)",
        )
        edge_count = rows[0][0] if rows else 0
        assert edge_count == 1, f"Expected 1 CALLS edge, found {edge_count}"
    finally:
        store.close()
