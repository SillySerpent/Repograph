"""Tests for Block I3 — confidence-weighted impact graph exporter."""
from __future__ import annotations

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


def _edge(from_id: str, to_id: str, confidence: float = 0.9):
    from repograph.core.models import CallEdge
    return CallEdge(
        from_function_id=from_id, to_function_id=to_id,
        call_site_line=1, argument_names=[], confidence=confidence, reason="static",
    )


def _open_store(tmp_path: Path, db_name: str = "g.db"):
    from repograph.graph_store.store import GraphStore
    store = GraphStore(str(tmp_path / db_name))
    store.initialize_schema()
    return store


# ---------------------------------------------------------------------------
# I3.1 render_impact_graph — Mermaid output
# ---------------------------------------------------------------------------


def test_render_mermaid_contains_flowchart_directive(tmp_path):
    """Mermaid output must start with 'flowchart'."""
    from repograph.plugins.exporters.impact_graph.plugin import render_impact_graph

    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/a::entry", "entry", "app/a.py")
    store.upsert_function(fn)

    diagram, n_nodes, _n_edges = render_impact_graph(store, entry_point="fn::app/a::entry")
    assert diagram.startswith("flowchart"), f"Expected Mermaid flowchart, got: {diagram[:30]}"
    assert n_nodes >= 1
    store.close()


def test_render_mermaid_includes_callee_node(tmp_path):
    """Mermaid diagram must contain both root and callee nodes."""
    from repograph.plugins.exporters.impact_graph.plugin import render_impact_graph

    store = _open_store(tmp_path)
    fn_a = _make_fn("fn::app/a::entry", "entry", "app/a.py")
    fn_b = _make_fn("fn::app/b::helper", "helper", "app/b.py")
    store.upsert_function(fn_a)
    store.upsert_function(fn_b)
    store.insert_call_edge(_edge(fn_a.id, fn_b.id, confidence=0.9))

    diagram, n_nodes, n_edges = render_impact_graph(store, entry_point="fn::app/a::entry")
    assert n_nodes == 2
    assert n_edges == 1
    assert "helper" in diagram or "fn__app_b__helper" in diagram
    store.close()


def test_render_mermaid_root_node_has_root_class(tmp_path):
    """Root node must have the :::root style class in Mermaid output."""
    from repograph.plugins.exporters.impact_graph.plugin import render_impact_graph

    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/a::entry", "entry", "app/a.py")
    store.upsert_function(fn)

    diagram, _, _ = render_impact_graph(store, entry_point="fn::app/a::entry")
    assert ":::root" in diagram, "Root node must have :::root style class"
    store.close()


def test_render_mermaid_high_confidence_uses_thick_edge(tmp_path):
    """Edges with confidence >= 0.8 use ==> (thick arrow) in Mermaid."""
    from repograph.plugins.exporters.impact_graph.plugin import render_impact_graph

    store = _open_store(tmp_path)
    fn_a = _make_fn("fn::app/a::entry", "entry", "app/a.py")
    fn_b = _make_fn("fn::app/b::helper", "helper", "app/b.py")
    store.upsert_function(fn_a)
    store.upsert_function(fn_b)
    store.insert_call_edge(_edge(fn_a.id, fn_b.id, confidence=0.9))

    diagram, _, _ = render_impact_graph(store, entry_point="fn::app/a::entry")
    assert "==>" in diagram, "High-confidence edge must use ==> in Mermaid"
    store.close()


def test_render_mermaid_low_confidence_uses_regular_edge(tmp_path):
    """Edges with confidence < 0.8 use --> (regular arrow) in Mermaid."""
    from repograph.plugins.exporters.impact_graph.plugin import render_impact_graph

    store = _open_store(tmp_path)
    fn_a = _make_fn("fn::app/a::entry", "entry", "app/a.py")
    fn_b = _make_fn("fn::app/b::helper", "helper", "app/b.py")
    store.upsert_function(fn_a)
    store.upsert_function(fn_b)
    store.insert_call_edge(_edge(fn_a.id, fn_b.id, confidence=0.6))

    diagram, _, _ = render_impact_graph(
        store, entry_point="fn::app/a::entry", min_confidence=0.5
    )
    assert "-->" in diagram, "Low-confidence edge must use --> in Mermaid"
    store.close()


def test_render_mermaid_below_min_confidence_excluded(tmp_path):
    """Edges below min_confidence are excluded from the diagram."""
    from repograph.plugins.exporters.impact_graph.plugin import render_impact_graph

    store = _open_store(tmp_path)
    fn_a = _make_fn("fn::app/a::entry", "entry", "app/a.py")
    fn_b = _make_fn("fn::app/b::helper", "helper", "app/b.py")
    store.upsert_function(fn_a)
    store.upsert_function(fn_b)
    store.insert_call_edge(_edge(fn_a.id, fn_b.id, confidence=0.3))

    diagram, n_nodes, n_edges = render_impact_graph(
        store, entry_point="fn::app/a::entry", min_confidence=0.5
    )
    # helper should not appear since its edge is below min_confidence
    assert n_edges == 0, "Edge below min_confidence must be excluded"
    store.close()


# ---------------------------------------------------------------------------
# I3.2 render_impact_graph — DOT output
# ---------------------------------------------------------------------------


def test_render_dot_starts_with_digraph(tmp_path):
    """DOT output must start with 'digraph'."""
    from repograph.plugins.exporters.impact_graph.plugin import render_impact_graph

    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/a::entry", "entry", "app/a.py")
    store.upsert_function(fn)

    diagram, _, _ = render_impact_graph(store, entry_point="fn::app/a::entry", fmt="dot")
    assert diagram.startswith("digraph"), f"Expected DOT digraph, got: {diagram[:30]}"
    store.close()


def test_render_dot_includes_edge_confidence_label(tmp_path):
    """DOT output must include confidence value as edge label."""
    from repograph.plugins.exporters.impact_graph.plugin import render_impact_graph

    store = _open_store(tmp_path)
    fn_a = _make_fn("fn::app/a::entry", "entry", "app/a.py")
    fn_b = _make_fn("fn::app/b::helper", "helper", "app/b.py")
    store.upsert_function(fn_a)
    store.upsert_function(fn_b)
    store.insert_call_edge(_edge(fn_a.id, fn_b.id, confidence=0.85))

    diagram, _, _ = render_impact_graph(store, entry_point="fn::app/a::entry", fmt="dot")
    assert "0.85" in diagram, "DOT output must include edge confidence as label"
    store.close()


# ---------------------------------------------------------------------------
# I3.3 unknown entry point returns empty
# ---------------------------------------------------------------------------


def test_render_unknown_entry_returns_empty(tmp_path):
    """Unresolvable entry point must return empty diagram string."""
    from repograph.plugins.exporters.impact_graph.plugin import render_impact_graph

    store = _open_store(tmp_path)
    diagram, n_nodes, n_edges = render_impact_graph(
        store, entry_point="no_such_function_xyzzy"
    )
    assert diagram == ""
    assert n_nodes == 0
    assert n_edges == 0
    store.close()


# ---------------------------------------------------------------------------
# I3.4 plugin export method
# ---------------------------------------------------------------------------


def test_plugin_export_returns_dict_with_required_keys(tmp_path):
    """ImpactGraphExporterPlugin.export() must return diagram, format, node_count, edge_count."""
    from repograph.plugins.exporters.impact_graph.plugin import ImpactGraphExporterPlugin

    store = _open_store(tmp_path)
    fn = _make_fn("fn::app/a::entry", "entry", "app/a.py")
    store.upsert_function(fn)

    plugin = ImpactGraphExporterPlugin()
    result = plugin.export(store=store, entry_point="fn::app/a::entry", format="mermaid")

    assert "diagram" in result
    assert "format" in result
    assert "node_count" in result
    assert "edge_count" in result
    store.close()


def test_plugin_export_no_store_returns_empty():
    """export() without a store must return an empty diagram gracefully."""
    from repograph.plugins.exporters.impact_graph.plugin import ImpactGraphExporterPlugin

    plugin = ImpactGraphExporterPlugin()
    result = plugin.export(store=None, entry_point="some.func")
    assert result["diagram"] == ""
    assert result["node_count"] == 0
