"""Tests for repository-agnostic call-edge postprocessing."""
from __future__ import annotations

from repograph.core.confidence import CONF_DIRECT_CALL, CONF_IMPORT_RESOLVED, CONF_METHOD_CALL
from repograph.core.confidence import should_skip_call_edge


def test_keeps_high_confidence_self_edge() -> None:
    assert not should_skip_call_edge("a", "a", CONF_IMPORT_RESOLVED, "import_resolved")


def test_drops_low_confidence_self_method_edge() -> None:
    assert should_skip_call_edge("a", "a", CONF_METHOD_CALL, "method_call")


def test_keeps_distinct_functions() -> None:
    assert not should_skip_call_edge("a", "b", CONF_METHOD_CALL, "method_call")


def test_drops_fuzzy_self_edge() -> None:
    from repograph.core.confidence import CONF_FUZZY_MATCH

    assert should_skip_call_edge("x", "x", CONF_FUZZY_MATCH, "fuzzy")
