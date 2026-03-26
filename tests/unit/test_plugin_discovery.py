"""Parity checks for plugin discovery order vs registered plugin ids."""
from __future__ import annotations

from repograph.plugins.discovery import (
    DEMAND_ANALYZER_ORDER,
    DYNAMIC_ANALYZER_ORDER,
    EVIDENCE_PRODUCER_ORDER,
    EXPORTER_ORDER,
    FRAMEWORK_ADAPTER_ORDER,
    PARSER_ORDER,
    STATIC_ANALYZER_ORDER,
)
from repograph.plugins.lifecycle import get_hook_scheduler


def test_hook_scheduler_manifest_counts() -> None:
    s = get_hook_scheduler()
    m = s.manifests()
    assert len(m["parser"]) == len(PARSER_ORDER)
    assert len(m["framework_adapter"]) == len(FRAMEWORK_ADAPTER_ORDER)
    assert len(m["static_analyzer"]) == len(STATIC_ANALYZER_ORDER)
    assert len(m["demand_analyzer"]) == len(DEMAND_ANALYZER_ORDER)
    assert len(m["exporter"]) == len(EXPORTER_ORDER)
    assert len(m["evidence_producer"]) == len(EVIDENCE_PRODUCER_ORDER)
    assert len(m["dynamic_analyzer"]) == len(DYNAMIC_ANALYZER_ORDER)
    assert len(m["tracer"]) == 1
