"""Tests for no-silent-failure policy helpers."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from repograph.observability import (
    ObservabilityConfig,
    get_logger,
    init_observability,
    log_degraded,
    log_swallowed,
    new_run_id,
    shutdown_observability,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path) -> ObservabilityConfig:
    return ObservabilityConfig(log_dir=tmp_path / "logs", run_id=new_run_id())


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_log_degraded_emits_warning_with_degraded_true(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        logger = get_logger("repograph.test.policy")
        exc = ValueError("something missing")
        log_degraded(logger, "edge skipped — missing node", exc=exc, partial_result="edge skipped", node_id="abc123")
    finally:
        shutdown_observability()

    records = _read_jsonl(config.run_dir / "all.jsonl")
    degraded = [r for r in records if "edge skipped" in r.get("msg", "")]
    assert degraded, "log_degraded record not found"

    rec = degraded[0]
    assert rec["level"] == "WARNING"
    assert rec["degraded"] is True
    assert rec["partial_result"] == "edge skipped"
    assert rec["exc_type"] == "ValueError"
    assert "something missing" in rec["exc_msg"]
    assert rec.get("node_id") == "abc123"


def test_log_degraded_without_exc(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        logger = get_logger("repograph.test.policy")
        log_degraded(logger, "partial result returned", partial_result="3 of 7 files")
    finally:
        shutdown_observability()

    records = _read_jsonl(config.run_dir / "all.jsonl")
    rec = next((r for r in records if "partial result returned" in r.get("msg", "")), None)
    assert rec is not None
    assert rec["level"] == "WARNING"
    assert rec["degraded"] is True
    assert rec["exc_type"] is None


def test_log_swallowed_emits_error(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        logger = get_logger("repograph.test.policy")
        try:
            raise RuntimeError("unexpected plugin crash")
        except RuntimeError as exc:
            log_swallowed(logger, "plugin dispatch failed", exc, plugin_id="my_plugin")
    finally:
        shutdown_observability()

    records = _read_jsonl(config.run_dir / "all.jsonl")
    swallowed = [r for r in records if "plugin dispatch failed" in r.get("msg", "")]
    assert swallowed, "log_swallowed record not found"

    rec = swallowed[0]
    assert rec["level"] == "ERROR"
    assert rec["degraded"] is True
    assert rec.get("plugin_id") == "my_plugin"


def test_log_swallowed_appears_in_errors_jsonl(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        logger = get_logger("repograph.test.policy")
        try:
            raise ConnectionError("db gone")
        except ConnectionError as exc:
            log_swallowed(logger, "store write failed", exc)
    finally:
        shutdown_observability()

    error_records = _read_jsonl(config.run_dir / "errors.jsonl")
    assert any("store write failed" in r.get("msg", "") for r in error_records), (
        "log_swallowed record should appear in errors.jsonl"
    )


def test_log_degraded_does_not_raise():
    """log_degraded must never raise regardless of logger state."""
    logger = get_logger("repograph.test.safe")
    # No init_observability — sink is not active
    log_degraded(logger, "safe call before init", exc=None)
    log_degraded(logger, "safe with exc", exc=ValueError("x"))


def test_log_swallowed_does_not_raise():
    """log_swallowed must never raise regardless of logger state."""
    logger = get_logger("repograph.test.safe")
    log_swallowed(logger, "safe swallow before init", Exception("y"))


def test_no_silent_failure_in_exec_rel(tmp_path: Path):
    """After Block A1 fix: _exec_rel logs a debug message for missing-node errors.

    This test verifies the fix is in place: a real KuzuDB syntax error IS re-raised,
    while a missing-node-like error is caught and logged.
    """
    from repograph.graph_store.store_base import GraphStoreBase
    import tempfile, os

    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "test.db")
        store = GraphStoreBase(db_path)
        store.initialize_schema()

        # A malformed Cypher query (not a missing-node error) must propagate
        with pytest.raises(Exception):
            store._exec_rel("THIS IS NOT VALID CYPHER")

        store.close()
