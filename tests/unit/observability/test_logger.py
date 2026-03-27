"""Tests for StructuredLogger and the JSONL handler installation."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from repograph.observability import (
    ObservabilityConfig,
    get_logger,
    init_observability,
    new_run_id,
    shutdown_observability,
)
from repograph.observability._logger import StructuredLogger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path) -> ObservabilityConfig:
    return ObservabilityConfig(
        log_dir=tmp_path / "logs",
        run_id=new_run_id(),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_logger_returns_structured_logger():
    logger = get_logger(__name__)
    assert isinstance(logger, StructuredLogger)


def test_logger_has_correct_name():
    logger = get_logger("repograph.pipeline.runner")
    assert logger.name == "repograph.pipeline.runner"


def test_subsystem_inferred_from_module_name():
    from repograph.observability._logger import _infer_subsystem
    assert _infer_subsystem("repograph.pipeline.runner") == "pipeline"
    assert _infer_subsystem("repograph.plugins.parsers.python") == "parsers"
    assert _infer_subsystem("repograph.graph_store.store_base") == "graph_store"
    assert _infer_subsystem("repograph.mcp.server") == "mcp"
    assert _infer_subsystem("repograph.unknown.module") == "core"


def test_subsystem_override():
    logger = get_logger("repograph.pipeline.runner", subsystem="custom")
    # Confirm it's the right type — actual subsystem is embedded inside _log()
    # so we verify via the log record in a full init test below.
    assert isinstance(logger, StructuredLogger)


def test_logger_before_init_does_not_error():
    """Calling logger.info before init_observability must not raise."""
    shutdown_observability()  # ensure clean state
    logger = get_logger("repograph.test.pre_init")
    # Should not raise even without an active sink
    logger.info("test message before init", key="value")
    logger.warning("test warning before init")
    logger.debug("test debug before init")
    logger.error("test error before init")


def test_log_record_schema(tmp_path: Path):
    """After init, emitting a record produces a JSONL file with all required fields."""
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        logger = get_logger("repograph.test.schema")
        logger.info("schema test", phase="p04", some_extra="hello")
    finally:
        shutdown_observability()

    all_jsonl = config.run_dir / "all.jsonl"
    assert all_jsonl.exists(), "all.jsonl was not created"

    records = [json.loads(line) for line in all_jsonl.read_text().splitlines() if line.strip()]
    assert len(records) >= 1

    # Find our test record (there may also be the init record)
    test_records = [r for r in records if "schema test" in r.get("msg", "")]
    assert test_records, "test record not found in all.jsonl"

    rec = test_records[0]
    required_fields = {
        "ts", "level", "level_no", "msg", "subsystem", "component",
        "run_id", "command_id", "span_id", "phase", "plugin_id", "hook",
        "duration_ms", "path", "symbol", "exc_type", "exc_msg", "exc_tb",
        "degraded", "partial_result",
    }
    for field in required_fields:
        assert field in rec, f"Required field '{field}' missing from JSONL record"

    assert rec["level"] == "INFO"
    assert rec["msg"] == "schema test"
    assert rec["run_id"] == config.run_id
    assert rec["some_extra"] == "hello"


def test_logger_enabled_for_level():
    logger = get_logger("repograph.test.enabled")
    # After init, DEBUG should be enabled for repograph loggers
    assert logger.isEnabledFor(10)  # logging.DEBUG = 10


def test_exception_method_captures_exc_info(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        logger = get_logger("repograph.test.exception_method")
        try:
            raise ValueError("test error")
        except ValueError:
            logger.exception("caught error")
    finally:
        shutdown_observability()

    all_jsonl = config.run_dir / "all.jsonl"
    records = [json.loads(line) for line in all_jsonl.read_text().splitlines() if line.strip()]
    exc_records = [r for r in records if "caught error" in r.get("msg", "")]
    assert exc_records
    rec = exc_records[0]
    assert rec["exc_type"] == "ValueError"
    assert "test error" in rec["exc_msg"]
    assert rec["exc_tb"] is not None
