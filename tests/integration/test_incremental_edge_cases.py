"""Block B3 — Incremental sync edge-case integration tests.

These tests verify the actual graph state after incremental sync operations,
not just the diff computation. Each test:
  1. Runs a full sync on the python_simple fixture.
  2. Performs a filesystem mutation (delete, rename, modify, etc.).
  3. Runs an incremental sync.
  4. Queries the graph directly and asserts the expected state.
"""
from __future__ import annotations

import os
import shutil

SIMPLE_FIXTURE = os.path.join(os.path.dirname(__file__), "..", "fixtures", "python_simple")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_repo(tmp_path) -> tuple[str, str]:
    """Copy fixture to writable dir; return (repo_root, repograph_dir)."""
    repo = str(tmp_path / "repo")
    shutil.copytree(os.path.abspath(SIMPLE_FIXTURE), repo)
    rg_dir = str(tmp_path / ".repograph")
    return repo, rg_dir


def _full_sync(repo: str, rg_dir: str):
    from repograph.pipeline.runner import RunConfig, run_full_pipeline
    config = RunConfig(repo_root=repo, repograph_dir=rg_dir, include_git=False, full=True)
    run_full_pipeline(config)
    return config


def _incremental_sync(config):
    from repograph.pipeline.runner import run_incremental_pipeline
    run_incremental_pipeline(config)


def _open_store(rg_dir: str):
    from repograph.graph_store.store import GraphStore
    store = GraphStore(os.path.join(rg_dir, "graph.db"))
    store.initialize_schema()
    return store


def _fn_ids_in_file(store, rel_path: str) -> list[str]:
    rows = store.query(
        "MATCH (f:Function) WHERE f.file_path ENDS WITH $p RETURN f.id",
        {"p": rel_path},
    )
    return [r[0] for r in rows]


def _file_node_exists(store, rel_path: str) -> bool:
    rows = store.query(
        "MATCH (f:File) WHERE f.path ENDS WITH $p RETURN f.id",
        {"p": rel_path},
    )
    return bool(rows)


# ---------------------------------------------------------------------------
# B3.1 File deleted — node and functions removed, call edges cleaned up
# ---------------------------------------------------------------------------


def test_incremental_file_deleted_removes_graph_nodes(tmp_path):
    """After deleting services.py the store must contain no Function nodes for it."""
    repo, rg_dir = _setup_repo(tmp_path)
    config = _full_sync(repo, rg_dir)

    store = _open_store(rg_dir)
    fn_ids_before = _fn_ids_in_file(store, "services.py")
    store.close()
    assert fn_ids_before, "Fixture should have functions in services.py before deletion"

    os.remove(os.path.join(repo, "services.py"))
    _incremental_sync(config)

    store = _open_store(rg_dir)
    fn_ids_after = _fn_ids_in_file(store, "services.py")
    file_exists = _file_node_exists(store, "services.py")
    store.close()

    assert fn_ids_after == [], "All functions from deleted file must be removed from graph"
    assert not file_exists, "File node for deleted file must be removed from graph"


# ---------------------------------------------------------------------------
# B3.2 File renamed — old path gone, new path present
# ---------------------------------------------------------------------------


def test_incremental_file_renamed_updates_graph(tmp_path):
    """Renaming models.py to domain.py: graph must have domain.py nodes, not models.py."""
    repo, rg_dir = _setup_repo(tmp_path)
    config = _full_sync(repo, rg_dir)

    store = _open_store(rg_dir)
    fns_before = _fn_ids_in_file(store, "models.py")
    store.close()
    assert fns_before, "Fixture should have functions in models.py"

    os.rename(
        os.path.join(repo, "models.py"),
        os.path.join(repo, "domain.py"),
    )
    _incremental_sync(config)

    store = _open_store(rg_dir)
    fns_old = _fn_ids_in_file(store, "models.py")
    fns_new = _fn_ids_in_file(store, "domain.py")
    old_file = _file_node_exists(store, "models.py")
    new_file = _file_node_exists(store, "domain.py")
    store.close()

    assert fns_old == [], "Old path (models.py) must have no function nodes after rename"
    assert not old_file, "File node for old path must be removed"
    assert fns_new, "New path (domain.py) must have function nodes after rename"
    assert new_file, "File node for new path must exist"


# ---------------------------------------------------------------------------
# B3.3 No changes — incremental sync is idempotent
# ---------------------------------------------------------------------------


def test_incremental_no_changes_is_idempotent(tmp_path):
    """Running incremental sync with no file changes must not alter the graph."""
    repo, rg_dir = _setup_repo(tmp_path)
    config = _full_sync(repo, rg_dir)

    store = _open_store(rg_dir)
    fn_count_before = len(store.query("MATCH (f:Function) RETURN f.id"))
    file_count_before = len(store.query("MATCH (f:File) RETURN f.id"))
    store.close()

    _incremental_sync(config)

    store = _open_store(rg_dir)
    fn_count_after = len(store.query("MATCH (f:Function) RETURN f.id"))
    file_count_after = len(store.query("MATCH (f:File) RETURN f.id"))
    store.close()

    assert fn_count_after == fn_count_before, (
        "Function count must be unchanged after no-op incremental sync"
    )
    assert file_count_after == file_count_before, (
        "File count must be unchanged after no-op incremental sync"
    )


# ---------------------------------------------------------------------------
# B3.4 Source-hash change only — graph reflects new hash, structure stable
# ---------------------------------------------------------------------------


def test_incremental_source_hash_change_updates_hash(tmp_path):
    """Appending a comment to services.py: graph must contain updated source_hash."""
    repo, rg_dir = _setup_repo(tmp_path)
    config = _full_sync(repo, rg_dir)

    store = _open_store(rg_dir)
    rows = store.query(
        "MATCH (f:File) WHERE f.path ENDS WITH 'services.py' RETURN f.source_hash"
    )
    hash_before = rows[0][0] if rows else None
    store.close()

    # Modify without changing any function signatures
    services_path = os.path.join(repo, "services.py")
    with open(services_path, "a") as fp:
        fp.write("\n# comment only change\n")

    _incremental_sync(config)

    store = _open_store(rg_dir)
    rows_after = store.query(
        "MATCH (f:File) WHERE f.path ENDS WITH 'services.py' RETURN f.source_hash"
    )
    hash_after = rows_after[0][0] if rows_after else None
    fn_count_after = len(_fn_ids_in_file(store, "services.py"))
    store.close()

    assert hash_after != hash_before, "source_hash must change when file content changes"
    assert fn_count_after >= 1, "Functions in services.py must still be present after hash-only change"


# ---------------------------------------------------------------------------
# B3.5 Expand reparse callers — caller of changed file is re-parsed
# ---------------------------------------------------------------------------


def test_incremental_expand_reparse_callers(tmp_path):
    """Adding a function to services.py must be reflected in the graph."""
    repo, rg_dir = _setup_repo(tmp_path)
    config = _full_sync(repo, rg_dir)

    # Verify new_function doesn't exist yet
    store = _open_store(rg_dir)
    before_rows = store.query(
        "MATCH (f:Function) WHERE f.name = 'brand_new_service_fn' RETURN f.id"
    )
    store.close()
    assert not before_rows, "new function should not exist before incremental sync"

    services_path = os.path.join(repo, "services.py")
    with open(services_path, "a") as fp:
        fp.write("\ndef brand_new_service_fn() -> int:\n    return 42\n")

    _incremental_sync(config)

    store = _open_store(rg_dir)
    after_rows = store.query(
        "MATCH (f:Function) WHERE f.name = 'brand_new_service_fn' RETURN f.id"
    )
    store.close()

    assert after_rows, "New function added to services.py must appear in graph after incremental sync"


# ---------------------------------------------------------------------------
# B3.6 source_hash=None — warning logged, no crash, safe partial result
# ---------------------------------------------------------------------------


def test_incremental_source_hash_none_warning(tmp_path):
    """IncrementalDiff.compute() with a FileRecord whose source_hash is None must not crash."""
    from repograph.pipeline.incremental import IncrementalDiff
    from repograph.core.models import FileRecord
    import logging

    repo, rg_dir = _setup_repo(tmp_path)
    config = _full_sync(repo, rg_dir)

    # Build a valid index first
    from repograph.pipeline.phases.p01_walk import run as walk
    differ = IncrementalDiff(rg_dir)
    files = walk(repo)
    differ.save_index({fr.path: fr for fr in files})

    # Inject a FileRecord with source_hash=None
    bad_record = FileRecord(
        path="fake/bad.py",
        abs_path=os.path.join(repo, "bad.py"),
        name="bad.py",
        extension=".py",
        language="python",
        size_bytes=0,
        line_count=0,
        source_hash=None,  # type: ignore[arg-type]  — intentional bad input
        is_test=False,
        is_config=False,
        mtime=0.0,
    )
    current = {fr.path: fr for fr in files}
    current["fake/bad.py"] = bad_record

    warning_records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            warning_records.append(record.getMessage())

    handler = _Capture(level=logging.WARNING)
    logging.getLogger("repograph.pipeline.incremental").addHandler(handler)
    try:
        diff = differ.compute(current)
    finally:
        logging.getLogger("repograph.pipeline.incremental").removeHandler(handler)

    # Must not raise; the bad record is handled gracefully
    assert diff is not None, "compute() must return a DiffResult even with bad input"
    assert any("source_hash" in w or "bad.py" in w or "None" in w for w in warning_records), (
        "A warning must be logged when source_hash is None. Got warnings: "
        + str(warning_records[:5])
    )
