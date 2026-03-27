"""Tests for span-based instrumentation."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from repograph.observability import (
    ObservabilityConfig,
    init_observability,
    new_run_id,
    shutdown_observability,
    span,
    span_decorator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path) -> ObservabilityConfig:
    return ObservabilityConfig(log_dir=tmp_path / "logs", run_id=new_run_id())


def _records(config: ObservabilityConfig) -> list[dict]:
    all_jsonl = config.run_dir / "all.jsonl"
    if not all_jsonl.exists():
        return []
    return [json.loads(line) for line in all_jsonl.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_span_emits_start_and_end(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        with span("test_operation", subsystem="pipeline"):
            pass
    finally:
        shutdown_observability()

    records = _records(config)
    msgs = [r["msg"] for r in records]
    assert any("test_operation" in m and "start" in m for m in msgs), "start record missing"
    assert any("test_operation" in m and "end" in m for m in msgs), "end record missing"


def test_span_captures_duration(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        with span("timed_op"):
            time.sleep(0.01)
    finally:
        shutdown_observability()

    records = _records(config)
    end_records = [r for r in records if "timed_op" in r.get("msg", "") and "end" in r.get("msg", "")]
    assert end_records, "end record not found"
    duration = end_records[0].get("duration_ms")
    assert duration is not None, "duration_ms missing"
    assert duration > 0, "duration_ms should be positive"


def test_span_on_exception_emits_failure_record(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        with pytest.raises(RuntimeError):
            with span("failing_op"):
                raise RuntimeError("boom")
    finally:
        shutdown_observability()

    records = _records(config)
    failed_records = [
        r for r in records
        if "failing_op" in r.get("msg", "") and "failed" in r.get("msg", "")
    ]
    assert failed_records, "failure record not found"
    rec = failed_records[0]
    assert rec.get("exc_type") == "RuntimeError"
    assert "boom" in rec.get("exc_msg", "")
    assert rec.get("duration_ms") is not None


def test_span_success_flag(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        with span("success_op"):
            pass
    finally:
        shutdown_observability()

    records = _records(config)
    end_records = [r for r in records if "success_op" in r.get("msg", "") and "end" in r.get("msg", "")]
    assert end_records
    # end record should not have exc_type set
    assert end_records[0].get("exc_type") is None


def test_span_context_propagation(tmp_path: Path):
    """Nested spans: child span log records carry a span_id."""
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        from repograph.observability import get_logger
        logger = get_logger("repograph.test.nested")
        with span("outer_op"):
            with span("inner_op"):
                logger.info("inside inner span")
    finally:
        shutdown_observability()

    records = _records(config)
    inner_records = [r for r in records if "inside inner span" in r.get("msg", "")]
    assert inner_records, "inner span log record not found"
    assert inner_records[0].get("span_id"), "span_id should be set inside span"


def test_span_as_decorator(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        @span_decorator("decorated_op", subsystem="pipeline")
        def do_work() -> str:
            return "result"

        result = do_work()
        assert result == "result"
    finally:
        shutdown_observability()

    records = _records(config)
    msgs = [r["msg"] for r in records]
    assert any("decorated_op" in m for m in msgs), "span records for decorated function missing"


def test_span_add_metadata(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        with span("metadata_op") as s:
            s.add_metadata(file_count=42, parse_errors=0)
    finally:
        shutdown_observability()

    records = _records(config)
    end_records = [r for r in records if "metadata_op" in r.get("msg", "") and "end" in r.get("msg", "")]
    assert end_records
    rec = end_records[0]
    assert rec.get("file_count") == 42
    assert rec.get("parse_errors") == 0


def test_span_restores_parent_span_id(tmp_path: Path):
    """After a child span exits, the parent span_id is restored."""
    from repograph.observability._context import get_context_var
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        with span("outer"):
            outer_span_id_before = get_context_var("span_id")
            with span("inner"):
                inner_span_id = get_context_var("span_id")
            outer_span_id_after = get_context_var("span_id")
        assert outer_span_id_before == outer_span_id_after, (
            "parent span_id not restored after child exits"
        )
        assert inner_span_id != outer_span_id_before, "inner span must have different span_id"
    finally:
        shutdown_observability()
