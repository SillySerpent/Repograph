"""Tests for SinkManager: routing, error filtering, symlinks, thread safety."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from repograph.observability import (
    ObservabilityConfig,
    get_logger,
    init_observability,
    new_run_id,
    shutdown_observability,
)
from repograph.observability._sinks import KNOWN_SUBSYSTEMS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, **kwargs) -> ObservabilityConfig:
    return ObservabilityConfig(log_dir=tmp_path / "logs", run_id=new_run_id(), **kwargs)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_all_jsonl_receives_every_record(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        get_logger("repograph.pipeline.runner").info("pipeline msg")
        get_logger("repograph.plugins.lifecycle").info("plugins msg")
        get_logger("repograph.graph_store.store_base").info("graph_store msg")
    finally:
        shutdown_observability()

    all_records = _read_jsonl(config.run_dir / "all.jsonl")
    msgs = {r["msg"] for r in all_records}
    assert "pipeline msg" in msgs
    assert "plugins msg" in msgs
    assert "graph_store msg" in msgs


def test_errors_jsonl_only_errors(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        logger = get_logger("repograph.pipeline.runner")
        logger.info("should not appear in errors")
        logger.warning("warning should not appear in errors")
        logger.error("this IS an error")
    finally:
        shutdown_observability()

    error_records = _read_jsonl(config.run_dir / "errors.jsonl")
    error_msgs = {r["msg"] for r in error_records}
    assert "this IS an error" in error_msgs
    assert "should not appear in errors" not in error_msgs
    assert "warning should not appear in errors" not in error_msgs


def test_subsystem_routing(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        get_logger("repograph.pipeline.runner").info("pipeline only message")
        get_logger("repograph.plugins.lifecycle").info("plugins only message")
    finally:
        shutdown_observability()

    pipeline_records = _read_jsonl(config.run_dir / "pipeline.jsonl")
    plugins_records = _read_jsonl(config.run_dir / "plugins.jsonl")

    pipeline_msgs = {r["msg"] for r in pipeline_records}
    plugins_msgs = {r["msg"] for r in plugins_records}

    assert "pipeline only message" in pipeline_msgs
    assert "pipeline only message" not in plugins_msgs
    assert "plugins only message" in plugins_msgs
    assert "plugins only message" not in pipeline_msgs


def test_latest_symlink_updated(tmp_path: Path):
    config = _make_config(tmp_path)
    init_observability(config)
    shutdown_observability()

    latest = config.log_dir / "latest"
    assert latest.is_symlink(), "latest symlink was not created"
    assert latest.resolve() == config.run_dir.resolve(), (
        "latest symlink does not point to the current run directory"
    )


def test_thread_safe_writes(tmp_path: Path):
    """Ten threads writing simultaneously must produce no duplicate records and no corruption."""
    config = _make_config(tmp_path)
    init_observability(config)
    try:
        loggers = [get_logger(f"repograph.pipeline.phase{i}") for i in range(10)]
        threads = []
        for i, lg in enumerate(loggers):
            t = threading.Thread(target=lambda l=lg, n=i: l.info(f"thread msg {n}"))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        shutdown_observability()

    all_records = _read_jsonl(config.run_dir / "all.jsonl")
    thread_msgs = [r["msg"] for r in all_records if r.get("msg", "").startswith("thread msg ")]

    assert len(thread_msgs) == 10, f"Expected 10 thread records, got {len(thread_msgs)}"
    assert len(set(thread_msgs)) == 10, "Duplicate thread records detected"


def test_subsystem_files_disabled(tmp_path: Path):
    config = _make_config(tmp_path, subsystem_files=False)
    init_observability(config)
    try:
        get_logger("repograph.pipeline.runner").info("should only go to all.jsonl")
    finally:
        shutdown_observability()

    assert (config.run_dir / "all.jsonl").exists(), "all.jsonl should always be written"
    assert not (config.run_dir / "pipeline.jsonl").exists(), (
        "pipeline.jsonl should not exist when subsystem_files=False"
    )


def test_known_subsystems_constant():
    """Sanity check: known subsystem set matches what the plan specifies."""
    expected = {
        "pipeline", "plugins", "parsers", "graph_store", "runtime",
        "services", "cli", "mcp", "setup", "incremental", "config", "observability",
    }
    assert expected == KNOWN_SUBSYSTEMS


def test_second_init_shuts_down_first(tmp_path: Path):
    """Calling init_observability twice cleanly replaces the previous sink."""
    config1 = _make_config(tmp_path)
    config2 = ObservabilityConfig(log_dir=tmp_path / "logs", run_id=new_run_id())

    init_observability(config1)
    get_logger("repograph.test").info("first run msg")

    init_observability(config2)
    get_logger("repograph.test").info("second run msg")
    shutdown_observability()

    records1 = _read_jsonl(config1.run_dir / "all.jsonl")
    records2 = _read_jsonl(config2.run_dir / "all.jsonl")

    msgs1 = {r["msg"] for r in records1}
    msgs2 = {r["msg"] for r in records2}

    assert "first run msg" in msgs1
    assert "second run msg" in msgs2
    assert "first run msg" not in msgs2
