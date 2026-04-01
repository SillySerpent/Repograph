from __future__ import annotations

from repograph.plugins.dynamic_analyzers._registry import get_registry


def test_dynamic_registry_includes_runtime_overlay_coverage_and_quality() -> None:
    reg = get_registry()
    manifests = {m["id"] for m in reg.manifests()}
    assert "dynamic_analyzer.runtime_overlay" in manifests
    assert "dynamic_analyzer.coverage_overlay" in manifests
    assert "dynamic_analyzer.runtime_quality" in manifests
