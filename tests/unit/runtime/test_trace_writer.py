"""Tests for TraceWriter resource management (Block B7/A3)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from repograph.runtime.trace_policy import TracePolicy
from repograph.runtime.trace_writer import TraceWriter


def _policy(**kwargs) -> TracePolicy:
    return TracePolicy(**kwargs)


def _writer(tmp_path: Path, **policy_kwargs) -> TraceWriter:
    return TraceWriter(tmp_path / "traces", "test_session", _policy(**policy_kwargs))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_context_manager_closes_file(tmp_path: Path):
    """After the context manager block, the file handle must be closed."""
    with _writer(tmp_path) as w:
        w.write({"event": "test"})
        assert w._file is not None
    assert w._file is None


def test_context_manager_writes_records(tmp_path: Path):
    """Records written inside the context are flushed and readable."""
    with _writer(tmp_path) as w:
        w.write({"event": "hello"})
        path = w.path

    assert path is not None
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "hello"


def test_exception_during_block_closes_file(tmp_path: Path):
    """An exception inside the context manager must still close the file."""
    writer = _writer(tmp_path)
    with pytest.raises(RuntimeError):
        with writer:
            writer.write({"event": "before_error"})
            raise RuntimeError("test error")
    assert writer._file is None


def test_open_and_close_explicitly(tmp_path: Path):
    """Manual open/close round-trip works correctly."""
    w = _writer(tmp_path)
    w.open()
    assert w._file is not None
    w.write({"k": "v"})
    w.close()
    assert w._file is None


def test_close_idempotent(tmp_path: Path):
    """Closing an already-closed writer must not raise."""
    w = _writer(tmp_path)
    w.open()
    w.close()
    w.close()  # second close must be safe


def test_rotation_creates_new_file(tmp_path: Path):
    """Rotation closes the old file and opens a new one."""
    # max_file_bytes=1 so the first write triggers rotation
    with _writer(tmp_path, max_file_bytes=1, rotate_files=2) as w:
        w.write({"a": 1})
        w.write({"b": 2})
        assert w.stats.rotated_files >= 1
    assert w._file is None


def test_del_warning_if_not_closed(tmp_path: Path, caplog):
    """__del__ on an unclosed writer must emit a warning."""
    w = _writer(tmp_path)
    w.open()
    path = w.path
    # Do not call close() — let __del__ handle it
    with caplog.at_level(logging.WARNING, logger="repograph.runtime.trace_writer"):
        del w
    assert any("garbage collected" in r.message or "open file" in r.message for r in caplog.records), (
        "Expected a GC warning from TraceWriter.__del__"
    )


def test_write_returns_false_before_open(tmp_path: Path):
    """Writing to an unopened writer returns False (no crash)."""
    w = _writer(tmp_path)
    result = w.write({"event": "test"})
    assert result is False


def test_stats_track_written_records(tmp_path: Path):
    """stats.written_records increments for each successful write."""
    with _writer(tmp_path) as w:
        w.write({"a": 1})
        w.write({"b": 2})
        w.write({"c": 3})
    assert w.stats.written_records == 3


def test_single_file_mode_replaces_old_trace_files(tmp_path: Path):
    """single_file mode must prune old JSONL traces before writing."""
    out_dir = tmp_path / "traces"
    out_dir.mkdir(parents=True)
    (out_dir / "old_a.jsonl").write_text('{"kind":"session"}\n', encoding="utf-8")
    (out_dir / "old_b.jsonl").write_text('{"kind":"session"}\n', encoding="utf-8")

    w = TraceWriter(out_dir, "pytest", _policy(), single_file=True)
    with w:
        ok = w.write({"kind": "call", "fn": "x"})
        assert ok is True
        assert w.path is not None
        assert w.path.name == "pytest.jsonl"

    files = sorted(p.name for p in out_dir.glob("*.jsonl"))
    assert files == ["pytest.jsonl"]
