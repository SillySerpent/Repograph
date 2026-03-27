"""Experimental pipeline phase SPI (no-op reference)."""
from __future__ import annotations

from unittest.mock import MagicMock

from repograph.pipeline.runner import RunConfig, _run_experimental_pipeline_phases
from repograph.plugins.pipeline_phases.no_op.plugin import NoOpPipelinePhase


def test_no_op_phase_runs_when_flag_enabled(tmp_path) -> None:
    store = MagicMock()
    parsed = []
    cfg = RunConfig(
        repo_root=str(tmp_path),
        repograph_dir=str(tmp_path / ".repograph"),
        experimental_phase_plugins=True,
    )
    _run_experimental_pipeline_phases(cfg, store, parsed)  # should not raise


def test_no_op_phase_skipped_when_flag_off(tmp_path) -> None:
    store = MagicMock()
    cfg = RunConfig(
        repo_root=str(tmp_path),
        repograph_dir=str(tmp_path / ".repograph"),
        experimental_phase_plugins=False,
    )
    _run_experimental_pipeline_phases(cfg, store, [])


def test_no_op_class_has_phase_id() -> None:
    assert NoOpPipelinePhase().phase_id
