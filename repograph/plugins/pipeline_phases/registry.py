"""Registered experimental pipeline phases (explicit order)."""
from __future__ import annotations

from collections.abc import Iterator

from repograph.core.plugin_framework.pipeline_phases import PipelinePhasePlugin


def iter_pipeline_phases() -> Iterator[PipelinePhasePlugin]:
    from repograph.plugins.pipeline_phases.no_op.plugin import build_no_op

    yield build_no_op()
