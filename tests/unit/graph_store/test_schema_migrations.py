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
