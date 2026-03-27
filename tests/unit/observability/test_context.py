"""Tests for context propagation via contextvars."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from repograph.observability import (
    ObservabilityConfig,
    get_logger,
    get_obs_context,
    init_observability,
    make_thread_context,
    new_run_id,
    set_obs_context,
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


def test_run_id_propagates_through_context(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        logger = get_logger("repograph.test.context")
        logger.info("context propagation test")
    finally:
        shutdown_observability()

    records = _read_jsonl(config.run_dir / "all.jsonl")
    test_records = [r for r in records if "context propagation test" in r.get("msg", "")]
    assert test_records
    assert test_records[0]["run_id"] == config.run_id


def test_set_obs_context_phase_appears_in_records(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        set_obs_context(phase="p04_imports")
        logger = get_logger("repograph.pipeline.runner")
        logger.info("phase context test")
        set_obs_context(phase="")
    finally:
        shutdown_observability()

    records = _read_jsonl(config.run_dir / "all.jsonl")
    phase_records = [r for r in records if "phase context test" in r.get("msg", "")]
    assert phase_records
    assert phase_records[0]["phase"] == "p04_imports"


def test_get_obs_context_snapshot():
    set_obs_context(run_id="test_run_123", phase="test_phase")
    ctx = get_obs_context()
    assert ctx["run_id"] == "test_run_123"
    assert ctx["phase"] == "test_phase"
    # Reset
    set_obs_context(run_id="", phase="")


def test_context_empty_values_returned_as_none():
    set_obs_context(span_id="")
    ctx = get_obs_context()
    # Empty string should be returned as None (stable schema)
    assert ctx["span_id"] is None


def test_context_isolated_across_threads():
    """Context set in thread 1 must not be visible in thread 2."""
    results: dict[str, str | None] = {}

    def thread1() -> None:
        set_obs_context(command_id="thread1_cmd")
        import time
        time.sleep(0.05)  # give thread2 a chance to check
        results["thread1"] = get_obs_context()["command_id"]

    def thread2() -> None:
        # thread2 should start with empty/independent context
        import time
        time.sleep(0.02)  # let thread1 set its context first
        results["thread2"] = get_obs_context()["command_id"]

    t1 = threading.Thread(target=thread1)
    t2 = threading.Thread(target=thread2)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["thread1"] == "thread1_cmd"
    # thread2's command_id should NOT be "thread1_cmd"
    assert results["thread2"] != "thread1_cmd"


def test_make_thread_context_copies_current_context():
    """make_thread_context() should capture the parent context for worker threads."""
    set_obs_context(run_id="parent_run_id")
    ctx = make_thread_context()

    inherited_value: list[str | None] = []

    def worker() -> None:
        inherited_value.append(get_obs_context()["run_id"])

    t = threading.Thread(target=lambda: ctx.run(worker))
    t.start()
    t.join()

    assert inherited_value == ["parent_run_id"], (
        "Worker thread should inherit run_id from parent context via ctx.run()"
    )
    # Reset
    set_obs_context(run_id="")


def test_phase_context_in_span(tmp_path: Path):
    """Phase set on context propagates into span records."""
    from repograph.observability import span

    config = _make_config(tmp_path)
    init_observability(config)
    try:
        set_obs_context(phase="p04")
        with span("test_span_with_phase"):
            pass
        set_obs_context(phase="")
    finally:
        shutdown_observability()

    records = _read_jsonl(config.run_dir / "all.jsonl")
    span_records = [r for r in records if "test_span_with_phase" in r.get("msg", "")]
    assert span_records
    # The start/end span records should carry phase from context
    for rec in span_records:
        assert rec.get("phase") == "p04", f"Expected phase=p04, got {rec.get('phase')} in {rec['msg']}"


def test_unknown_context_key_ignored():
    """set_obs_context silently ignores unknown keys (no hard failure)."""
    # Should not raise
    set_obs_context(unknown_key="value", run_id="valid")
    ctx = get_obs_context()
    assert ctx["run_id"] == "valid"
    assert "unknown_key" not in ctx
    set_obs_context(run_id="")
