"""Sanity-check bundled JSONL trace fixtures."""
from __future__ import annotations

from pathlib import Path

from repograph.runtime.trace_format import iter_records


def test_minimal_call_jsonl_parses() -> None:
    path = Path(__file__).resolve().parents[1] / "fixtures" / "traces" / "minimal_call.jsonl"
    kinds = [r.get("kind") for r in iter_records(path)]
    assert "session" in kinds
    assert "call" in kinds
