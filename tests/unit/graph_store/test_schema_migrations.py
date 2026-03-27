"""Tests for GraphStore schema migrations (Block B2)."""
from __future__ import annotations

from pathlib import Path


def _make_store(tmp_path: Path):
    from repograph.graph_store.store import GraphStore
    db = str(tmp_path / "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    return store


def _column_exists(store, table: str, column: str) -> bool:
    """Return True if the column exists on the table by probing a query."""
    try:
        store.query(f"MATCH (n:{table}) RETURN n.{column} LIMIT 1")
        return True
    except Exception:
        return False


def _rel_column_exists(store, rel: str, column: str) -> bool:
    try:
        store.query(f"MATCH ()-[r:{rel}]->() RETURN r.{column} LIMIT 1")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Migration v1.3 — Function.is_test
# ---------------------------------------------------------------------------


def test_migration_v13_is_test_column_exists(tmp_path: Path):
    """initialize_schema() must create Function.is_test."""
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "is_test")
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Migration v1.4 — entry_score breakdown columns
# ---------------------------------------------------------------------------


def test_migration_v14_entry_score_base(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "entry_score_base")
    finally:
        store.close()


def test_migration_v14_entry_score_multipliers(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "entry_score_multipliers")
    finally:
        store.close()


def test_migration_v14_entry_callee_count(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "entry_callee_count")
    finally:
        store.close()


def test_migration_v14_entry_caller_count(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "entry_caller_count")
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Migration v1.4 — runtime overlay columns
# ---------------------------------------------------------------------------


def test_migration_v14_runtime_observed(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "runtime_observed")
    finally:
        store.close()


def test_migration_v14_runtime_observed_calls(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "runtime_observed_calls")
    finally:
        store.close()


def test_migration_v14_runtime_observed_at(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "runtime_observed_at")
    finally:
        store.close()


def test_migration_v14_runtime_observed_for_hash(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "runtime_observed_for_hash")
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------


def test_probe_calls_extra_lines_column(tmp_path: Path):
    """_probe_calls_extra_lines_column returns True on a fresh schema."""
    store = _make_store(tmp_path)
    try:
        # The CALLS table is in the base schema with extra_site_lines
        assert store._calls_extra_lines is True
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_migration_idempotency(tmp_path: Path):
    """Calling initialize_schema() twice must not raise."""
    from repograph.graph_store.store import GraphStore
    db = str(tmp_path / "graph.db")
    store = GraphStore(db)
    try:
        store.initialize_schema()
        store.initialize_schema()  # second call must be safe
        assert _column_exists(store, "Function", "is_test")
    finally:
        store.close()


def test_migration_preserves_existing_data(tmp_path: Path):
    """Migrations run on a DB with data must not delete existing rows."""
    from repograph.graph_store.store import GraphStore
    from repograph.core.models import FunctionNode

    db = str(tmp_path / "graph.db")
    store = GraphStore(db)
    store.initialize_schema()

    fn = FunctionNode(
        id="fn_preserved",
        name="preserved",
        qualified_name="preserved",
        file_path="test.py",
        line_start=1,
        line_end=5,
        signature="def preserved()",
        docstring=None,
        is_method=False,
        is_async=False,
        is_exported=True,
        decorators=[],
        param_names=[],
        return_type=None,
        source_hash="abc",
    )
    store.upsert_function(fn)

    # Re-run migrations — data must survive
    store._migrate_function_is_test_column()
    store._migrate_function_entry_score_details()
    store._migrate_function_runtime_overlay_columns()

    rows = store.query("MATCH (f:Function {id: 'fn_preserved'}) RETURN f.name")
    assert rows and rows[0][0] == "preserved"
    store.close()


# ---------------------------------------------------------------------------
# Migration v1.6 — layer/role/http classification columns
# ---------------------------------------------------------------------------


def test_migration_v16_function_layer(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "layer")
    finally:
        store.close()


def test_migration_v16_function_role(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "role")
    finally:
        store.close()


def test_migration_v16_function_http_method(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "http_method")
    finally:
        store.close()


def test_migration_v16_function_route_path(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "Function", "route_path")
    finally:
        store.close()


def test_migration_v16_file_layer(tmp_path: Path):
    store = _make_store(tmp_path)
    try:
        assert _column_exists(store, "File", "layer")
    finally:
        store.close()


def test_migration_v16_makes_http_call_rel_exists(tmp_path: Path):
    """MAKES_HTTP_CALL relationship table must exist after schema init."""
    store = _make_store(tmp_path)
    try:
        assert _rel_column_exists(store, "MAKES_HTTP_CALL", "http_method")
    finally:
        store.close()


def test_update_function_layer_role(tmp_path: Path):
    """update_function_layer_role must write layer/role/http fields."""
    from repograph.graph_store.store import GraphStore
    from repograph.core.models import FunctionNode

    db = str(tmp_path / "graph.db")
    store = GraphStore(db)
    store.initialize_schema()
    fn = FunctionNode(
        id="fn_lr1", name="my_route", qualified_name="my_route",
        file_path="app.py", line_start=1, line_end=5,
        signature="def my_route()", docstring=None,
        is_method=False, is_async=False, is_exported=True,
        decorators=[], param_names=[], return_type=None, source_hash="x",
    )
    store.upsert_function(fn)
    store.update_function_layer_role("fn_lr1", layer="api", role="handler", http_method="POST", route_path="/api/users")
    rows = store.query("MATCH (f:Function {id: 'fn_lr1'}) RETURN f.layer, f.role, f.http_method, f.route_path")
    assert rows and rows[0][0] == "api"
    assert rows[0][1] == "handler"
    assert rows[0][2] == "POST"
    assert rows[0][3] == "/api/users"
    store.close()


def test_get_functions_by_layer(tmp_path: Path):
    """get_functions_by_layer must return only functions with the given layer."""
    from repograph.graph_store.store import GraphStore
    from repograph.core.models import FunctionNode

    db = str(tmp_path / "graph.db")
    store = GraphStore(db)
    store.initialize_schema()

    for fn_id, layer in [("fn_api1", "api"), ("fn_db1", "persistence"), ("fn_api2", "api")]:
        fn = FunctionNode(
            id=fn_id, name=fn_id, qualified_name=fn_id,
            file_path="x.py", line_start=1, line_end=2,
            signature=f"def {fn_id}()", docstring=None,
            is_method=False, is_async=False, is_exported=False,
            decorators=[], param_names=[], return_type=None, source_hash="h",
        )
        store.upsert_function(fn)
        store.update_function_layer_role(fn_id, layer=layer)

    api_fns = store.get_functions_by_layer("api")
    assert len(api_fns) == 2
    assert all(f["layer"] == "api" for f in api_fns)

    db_fns = store.get_functions_by_layer("persistence")
    assert len(db_fns) == 1

    unknown_fns = store.get_functions_by_layer("unknown_layer")
    assert unknown_fns == []
    store.close()


def test_get_http_endpoints(tmp_path: Path):
    """get_http_endpoints must return only functions with non-empty http_method."""
    from repograph.graph_store.store import GraphStore
    from repograph.core.models import FunctionNode

    db = str(tmp_path / "graph.db")
    store = GraphStore(db)
    store.initialize_schema()

    for fn_id, http_method, route in [
        ("fn_ep1", "GET", "/users"),
        ("fn_ep2", "POST", "/users"),
        ("fn_ep3", "", ""),  # not an endpoint
    ]:
        fn = FunctionNode(
            id=fn_id, name=fn_id, qualified_name=fn_id,
            file_path="routes.py", line_start=1, line_end=2,
            signature=f"def {fn_id}()", docstring=None,
            is_method=False, is_async=False, is_exported=False,
            decorators=[], param_names=[], return_type=None, source_hash="h",
        )
        store.upsert_function(fn)
        if http_method:
            store.update_function_layer_role(fn_id, layer="api", http_method=http_method, route_path=route)

    endpoints = store.get_http_endpoints()
    assert len(endpoints) == 2
    methods = {ep["http_method"] for ep in endpoints}
    assert methods == {"GET", "POST"}
    store.close()
