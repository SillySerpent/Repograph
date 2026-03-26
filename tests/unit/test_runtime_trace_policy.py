from __future__ import annotations

from repograph.runtime.trace_policy import TracePolicy
from repograph.runtime.trace_writer import TraceWriter


def test_trace_policy_from_kwargs_normalizes_bounds() -> None:
    p = TracePolicy.from_kwargs(
        max_records=-1,
        max_file_bytes=-5,
        rotate_files=-2,
        sample_rate=99.0,
    )
    assert p.max_records == 0
    assert p.max_file_bytes == 0
    assert p.rotate_files == 0
    assert p.sample_rate == 1.0


def test_trace_writer_enforces_max_records(tmp_path) -> None:
    p = TracePolicy.from_kwargs(max_records=2)
    w = TraceWriter(tmp_path, "pytest", p)
    w.open()
    try:
        assert w.write({"kind": "session"}) is True
        assert w.write({"kind": "call"}) is True
        assert w.write({"kind": "call"}) is False
        assert w.stats.written_records == 2
        assert w.stats.dropped_by_reason.get("max_records") == 1
    finally:
        w.close()
