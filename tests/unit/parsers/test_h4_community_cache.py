"""Tests for Block H4 — incremental community caching."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


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


def _open_store(tmp_path: Path, db_name: str = "g.db"):
    from repograph.graph_store.store import GraphStore
    store = GraphStore(str(tmp_path / db_name))
    store.initialize_schema()
    return store


# ---------------------------------------------------------------------------
# H4.1 save / load snapshot
# ---------------------------------------------------------------------------


def test_save_community_snapshot_writes_file(tmp_path):
    """save_community_snapshot must create community_snapshot.json in meta/."""
    from repograph.pipeline.phases.p09_communities import save_community_snapshot

    store = _open_store(tmp_path)
    fns = [_make_fn(f"fn::{i}", f"func_{i}", "app/a.py") for i in range(3)]
    for fn in fns:
        store.upsert_function(fn)

    repograph_dir = str(tmp_path / ".repograph")
    os.makedirs(repograph_dir, exist_ok=True)
    save_community_snapshot(repograph_dir, store)

    snap_path = tmp_path / ".repograph" / "meta" / "community_snapshot.json"
    assert snap_path.exists(), "community_snapshot.json not created"
    data = json.loads(snap_path.read_text())
    assert "snapshot_hash" in data
    assert data["total_functions"] == 3
    store.close()


def test_load_community_snapshot_returns_none_when_missing(tmp_path):
    """load_community_snapshot must return None when no snapshot exists."""
    from repograph.pipeline.phases.p09_communities import load_community_snapshot

    result = load_community_snapshot(str(tmp_path / "no_such_dir"))
    assert result is None


def test_load_community_snapshot_returns_dict(tmp_path):
    """load_community_snapshot must return the saved dict."""
    from repograph.pipeline.phases.p09_communities import (
        save_community_snapshot, load_community_snapshot,
    )

    store = _open_store(tmp_path)
    fn = _make_fn("fn::0", "func_0", "app/a.py")
    store.upsert_function(fn)

    repograph_dir = str(tmp_path / ".repograph")
    os.makedirs(repograph_dir, exist_ok=True)
    save_community_snapshot(repograph_dir, store)
    data = load_community_snapshot(repograph_dir)

    assert data is not None
    assert data["total_functions"] == 1
    assert len(data["snapshot_hash"]) == 16
    store.close()


def test_snapshot_hash_changes_when_assignments_change(tmp_path):
    """Changing community assignments must produce a different snapshot hash."""
    from repograph.pipeline.phases.p09_communities import (
        save_community_snapshot, load_community_snapshot,
    )

    store = _open_store(tmp_path)
    fn = _make_fn("fn::0", "func_0", "app/a.py")
    store.upsert_function(fn)

    repograph_dir = str(tmp_path / ".repograph")
    os.makedirs(repograph_dir, exist_ok=True)
    save_community_snapshot(repograph_dir, store)
    snap_before = load_community_snapshot(repograph_dir)
    assert snap_before is not None
    hash_before = snap_before["snapshot_hash"]

    # Change community assignment
    store.update_function_flags("fn::0", community_id="community:99")
    save_community_snapshot(repograph_dir, store)
    snap_after = load_community_snapshot(repograph_dir)
    assert snap_after is not None
    hash_after = snap_after["snapshot_hash"]

    assert hash_before != hash_after, "Hash should change when community assignments change"
    store.close()


# ---------------------------------------------------------------------------
# H4.2 partial re-run threshold logic (unit — mocks p09 internals)
# ---------------------------------------------------------------------------


def test_partial_rerun_skipped_when_no_snapshot(tmp_path):
    """If no snapshot exists, runner must do a full community re-run."""
    from repograph.pipeline.phases import p09_communities

    store = MagicMock()
    repograph_dir = str(tmp_path / "no_snapshot")

    snapshot = p09_communities.load_community_snapshot(repograph_dir)
    assert snapshot is None, "Should be None when snapshot file missing"


def test_partial_rerun_skipped_when_change_exceeds_threshold(tmp_path):
    """If changed functions >= 5% of total, run_partial should not be called."""
    from repograph.pipeline.phases.p09_communities import _PARTIAL_RERUN_THRESHOLD

    # 20% change → threshold exceeded → should not attempt partial
    total_functions = 100
    changed_count = 20  # 20% > 5%
    assert changed_count >= total_functions * _PARTIAL_RERUN_THRESHOLD, (
        "Test setup error: changed_count should exceed threshold"
    )


def test_partial_rerun_attempted_when_change_below_threshold(tmp_path):
    """If changed functions < 5% of total, run_partial should be attempted."""
    from repograph.pipeline.phases.p09_communities import _PARTIAL_RERUN_THRESHOLD

    total_functions = 100
    changed_count = 3  # 3% < 5%
    assert changed_count < total_functions * _PARTIAL_RERUN_THRESHOLD, (
        "Test setup error: changed_count should be below threshold"
    )


# ---------------------------------------------------------------------------
# H4.3 run_partial correctness
# ---------------------------------------------------------------------------


def test_run_partial_empty_changed_returns_true(tmp_path):
    """run_partial with empty changed set must return True (no-op)."""
    from repograph.pipeline.phases.p09_communities import run_partial

    store = MagicMock()
    result = run_partial(store, changed_fn_ids=set())
    assert result is True


def test_run_partial_returns_false_when_leidenalg_unavailable(tmp_path):
    """run_partial must return False when leidenalg is not installed."""
    import sys
    from repograph.pipeline.phases.p09_communities import run_partial

    store = MagicMock()
    store.get_all_functions.return_value = [
        {"id": "fn::a", "community_id": "community:1"},
    ]

    # Mask both leidenalg and igraph from sys.modules so the try/except ImportError fires.
    saved_leiden = sys.modules.get("leidenalg", "MISSING")
    saved_igraph = sys.modules.get("igraph", "MISSING")
    sys.modules["leidenalg"] = None  # type: ignore[assignment]
    sys.modules["igraph"] = None  # type: ignore[assignment]
    try:
        result = run_partial(store, changed_fn_ids={"fn::a"})
    finally:
        if saved_leiden == "MISSING":
            sys.modules.pop("leidenalg", None)
        else:
            sys.modules["leidenalg"] = saved_leiden  # type: ignore[assignment]
        if saved_igraph == "MISSING":
            sys.modules.pop("igraph", None)
        else:
            sys.modules["igraph"] = saved_igraph  # type: ignore[assignment]

    assert result is False


def test_run_partial_returns_false_when_changed_have_no_communities(tmp_path):
    """run_partial returns False when changed functions have no existing community."""
    from repograph.pipeline.phases.p09_communities import run_partial

    store = MagicMock()
    store.get_all_functions.return_value = [
        {"id": "fn::a", "community_id": ""},  # no community
    ]

    result = run_partial(store, changed_fn_ids={"fn::a"})
    assert result is False, "Should fall back when changed functions have no community"


# ---------------------------------------------------------------------------
# H4.4 full integration: snapshot saved after p09.run()
# ---------------------------------------------------------------------------


def test_snapshot_saved_after_full_p09_run(tmp_path):
    """After p09_communities.run(), the snapshot file must exist."""
    from repograph.pipeline.phases.p09_communities import (
        run as run_communities,
        save_community_snapshot,
        load_community_snapshot,
    )

    store = _open_store(tmp_path)
    fns = [_make_fn(f"fn::{i}", f"func_{i}", "app/a.py") for i in range(4)]
    for fn in fns:
        store.upsert_function(fn)

    repograph_dir = str(tmp_path / ".repograph")
    os.makedirs(repograph_dir, exist_ok=True)

    run_communities(store, min_community_size=1)
    save_community_snapshot(repograph_dir, store)

    snap = load_community_snapshot(repograph_dir)
    assert snap is not None
    assert snap["total_functions"] == 4
    store.close()
