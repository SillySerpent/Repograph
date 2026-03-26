from __future__ import annotations

from repograph.runtime.trace_filters import TraceFilter
from repograph.runtime.trace_policy import TracePolicy


def test_trace_filter_include_exclude() -> None:
    f = TraceFilter(
        TracePolicy.from_kwargs(include_pattern="repograph/", exclude_pattern="tests/")
    )
    ok = f.allow(file_path="repograph/runtime/tracer.py", qualified_name="x.y")
    blocked = f.allow(file_path="tests/test_x.py", qualified_name="x.y")
    assert ok.accepted is True
    assert blocked.accepted is False
    assert blocked.reason in {"include_filter", "exclude_filter"}


def test_trace_filter_sampling_zero_drops_all() -> None:
    f = TraceFilter(TracePolicy.from_kwargs(sample_rate=0.0))
    d = f.allow(file_path="repograph/a.py", qualified_name="mod.fn")
    assert d.accepted is False
    assert d.reason == "sampled_out"
