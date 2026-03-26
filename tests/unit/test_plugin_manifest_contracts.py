"""Fast structural checks on ``built_in_plugin_manifests`` (no pipeline)."""
from __future__ import annotations

import pytest

from repograph.plugins.features import built_in_plugin_manifests

pytestmark = pytest.mark.plugin


def test_built_in_plugin_manifests_non_empty() -> None:
    m = built_in_plugin_manifests()
    assert m["parsers"]
    assert m["exporters"]
    assert m["demand_analyzers"]
    assert m["static_analyzers"]
    assert m["framework_adapters"]
    assert m["evidence_producers"]
    assert m["dynamic_analyzers"]
    assert m["tracers"]


@pytest.mark.parametrize(
    "family",
    [
        "parsers",
        "exporters",
        "demand_analyzers",
        "static_analyzers",
        "framework_adapters",
        "evidence_producers",
        "dynamic_analyzers",
        "tracers",
    ],
)
def test_each_manifest_has_id_kind_hooks(family: str) -> None:
    m = built_in_plugin_manifests()
    for manifest in m[family]:
        assert manifest.get("id"), manifest
        assert manifest.get("kind"), manifest
        hooks = manifest.get("hooks")
        assert hooks is not None and len(hooks) >= 1, manifest
