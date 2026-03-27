"""Tests for Block G3 — layer-aware report surfaces in the agent guide generator."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_store(
    entry_points: list[dict] | None = None,
    pathways: list[dict] | None = None,
    fn_layer_rows: list[list] | None = None,
    layer_count_rows: list[list] | None = None,
    ep_layer_rows: list[list] | None = None,
) -> MagicMock:
    store = MagicMock()
    store.get_stats.return_value = {"functions": 10, "files": 3}
    store.get_all_pathways.return_value = pathways or []
    store.get_entry_points.return_value = entry_points or []
    store.get_event_topology.return_value = []
    store.get_async_tasks.return_value = []

    def query_side(cypher: str, params: dict | None = None):
        params = params or {}
        # _build_fn_layer_map
        if "f.id IN $ids" in cypher:
            return fn_layer_rows or []
        # architecture layers count
        if "count(f)" in cypher and "ORDER BY count" in cypher:
            return layer_count_rows or []
        # architecture layers entry points
        if "is_entry_point: true" in cypher and "f.layer" in cypher:
            return ep_layer_rows or []
        return []

    store.query.side_effect = query_side
    return store


# ---------------------------------------------------------------------------
# _build_fn_layer_map
# ---------------------------------------------------------------------------


def test_build_fn_layer_map_returns_correct_mapping():
    from repograph.plugins.exporters.agent_guide.generator import _build_fn_layer_map

    store = MagicMock()
    store.query.return_value = [
        ["fn::a", "api"],
        ["fn::b", "persistence"],
    ]
    result = _build_fn_layer_map(store, ["fn::a", "fn::b"])
    assert result == {"fn::a": "api", "fn::b": "persistence"}


def test_build_fn_layer_map_empty_ids_returns_empty():
    from repograph.plugins.exporters.agent_guide.generator import _build_fn_layer_map

    store = MagicMock()
    result = _build_fn_layer_map(store, [])
    assert result == {}
    store.query.assert_not_called()


# ---------------------------------------------------------------------------
# _build_architecture_layers_section
# ---------------------------------------------------------------------------


def test_architecture_layers_section_empty_when_no_data():
    from repograph.plugins.exporters.agent_guide.generator import _build_architecture_layers_section

    store = MagicMock()
    store.query.return_value = []
    result = _build_architecture_layers_section(store)
    assert result == []


def test_architecture_layers_section_has_table_header():
    from repograph.plugins.exporters.agent_guide.generator import _build_architecture_layers_section

    store = MagicMock()
    call_count = [0]

    def query_side(cypher: str, params=None):
        call_count[0] += 1
        if call_count[0] == 1:
            # layer count query
            return [["api", 5], ["persistence", 3], ["business_logic", 2]]
        if call_count[0] == 2:
            # entry points per layer query
            return [["api", "login_handler"], ["persistence", "save_user"]]
        return []

    store.query.side_effect = query_side
    lines = _build_architecture_layers_section(store)

    assert any("Architecture Layers" in ln for ln in lines)
    assert any("| Layer |" in ln for ln in lines)
    assert any("api" in ln for ln in lines)
    assert any("persistence" in ln for ln in lines)


def test_architecture_layers_section_shows_function_count():
    from repograph.plugins.exporters.agent_guide.generator import _build_architecture_layers_section

    store = MagicMock()
    call_count = [0]

    def query_side(cypher, params=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return [["api", 7]]
        return []

    store.query.side_effect = query_side
    lines = _build_architecture_layers_section(store)

    combined = "\n".join(lines)
    assert "7" in combined  # function count must appear


def test_architecture_layers_shows_entry_point_names():
    from repograph.plugins.exporters.agent_guide.generator import _build_architecture_layers_section

    store = MagicMock()
    call_count = [0]

    def query_side(cypher, params=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return [["api", 5]]
        if call_count[0] == 2:
            return [["api", "handle_login"], ["api", "get_user"]]
        return []

    store.query.side_effect = query_side
    lines = _build_architecture_layers_section(store)
    combined = "\n".join(lines)
    assert "handle_login" in combined


# ---------------------------------------------------------------------------
# generate_agent_guide integration — Layer column in entry points
# ---------------------------------------------------------------------------


def test_agent_guide_entry_points_include_layer_column():
    from repograph.plugins.exporters.agent_guide.generator import generate_agent_guide

    entry_points = [
        {"id": "fn::ep", "qualified_name": "my_module::login", "file_path": "app/routes/auth.py",
         "entry_score": 0.9, "signature": "def login():"},
    ]

    store = _mock_store(
        entry_points=entry_points,
        fn_layer_rows=[["fn::ep", "api"]],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        guide = generate_agent_guide(store, tmpdir, tmpdir)

    assert "| Layer |" in guide or "Layer" in guide
    # The api layer value should appear in the entry points table
    assert "api" in guide


def test_agent_guide_entry_points_unknown_layer_shows_dash():
    from repograph.plugins.exporters.agent_guide.generator import generate_agent_guide

    entry_points = [
        {"id": "fn::ep", "qualified_name": "my_module::process", "file_path": "app/misc.py",
         "entry_score": 0.5, "signature": "def process():"},
    ]

    store = _mock_store(
        entry_points=entry_points,
        fn_layer_rows=[["fn::ep", "unknown"]],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        guide = generate_agent_guide(store, tmpdir, tmpdir)

    assert "— |" in guide or "—" in guide


# ---------------------------------------------------------------------------
# generate_agent_guide — Pathway layer column
# ---------------------------------------------------------------------------


def test_agent_guide_pathways_include_layer_column():
    from repograph.plugins.exporters.agent_guide.generator import generate_agent_guide

    pathways = [{
        "id": "pathway::login",
        "name": "login_flow",
        "display_name": "Login Flow",
        "description": "Handles login",
        "confidence": 0.8,
        "step_count": 3,
        "source": "auto_detected",
        "entry_function": "fn::login",
        "importance_score": 0.5,
    }]

    store = _mock_store(
        pathways=pathways,
        fn_layer_rows=[["fn::login", "api"]],
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        guide = generate_agent_guide(store, tmpdir, tmpdir)

    # The pathways table should include a layer column
    assert "| Layer |" in guide or "api" in guide
