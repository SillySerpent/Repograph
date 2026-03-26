"""Ensure reference plugins under ``repograph.plugins.examples`` import and build."""
from __future__ import annotations

import pytest

from repograph.core.plugin_framework import RepoGraphPlugin


@pytest.mark.parametrize(
    "module_path, expected_id",
    [
        ("repograph.plugins.examples.parser.plugin", "parser.example_reference"),
        ("repograph.plugins.examples.framework_adapter.plugin", "framework_adapter.example_reference"),
        ("repograph.plugins.examples.static_analyzer.plugin", "static_analyzer.example_reference"),
        ("repograph.plugins.examples.demand_analyzer.plugin", "demand_analyzer.example_reference"),
        ("repograph.plugins.examples.evidence_producer.plugin", "evidence_producer.example_reference"),
        ("repograph.plugins.examples.exporter.plugin", "exporter.example_reference"),
        ("repograph.plugins.examples.dynamic_analyzer.plugin", "dynamic_analyzer.example_reference"),
        ("repograph.plugins.examples.tracer.plugin", "tracer.example_reference"),
    ],
)
def test_example_repo_graph_plugins_build(module_path: str, expected_id: str) -> None:
    mod = __import__(module_path, fromlist=["build_plugin"])
    p: RepoGraphPlugin = mod.build_plugin()
    assert p.plugin_id() == expected_id


def test_example_pipeline_phase_build() -> None:
    from repograph.plugins.examples.pipeline_phase.plugin import build_plugin
    from repograph.core.plugin_framework.pipeline_phases import PipelinePhasePlugin

    phase = build_plugin()
    assert isinstance(phase, PipelinePhasePlugin)
    assert phase.phase_id == "phase.example_reference"
