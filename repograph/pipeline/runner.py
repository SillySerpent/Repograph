"""Thin public facade for RepoGraph pipeline orchestration.

The actual runner implementation lives under `repograph.pipeline.runner_parts/`
so each responsibility has one focused module:

- `config.py` — `RunConfig` and validation
- `shared.py` — observability scopes, console output, cleanup policy
- `build.py` — static phase execution and optional SPI phases
- `hooks.py` — plugin-hook execution and summary merging
- `full.py` — full static rebuild coordinator
- `incremental.py` — incremental sync coordinator
- `full_runtime.py` — full rebuild plus runtime-plan execution

This module deliberately stays as the stable import surface used by CLI,
services, and tests. It wires the focused modules together without re-growing
their internal logic here.
"""
from __future__ import annotations

from repograph.graph_store.store import GraphStore
from repograph.runtime.orchestration import resolve_runtime_plan

from .runner_parts.build import (
    count_valid_runtime_observations as _count_valid_runtime_observations,
    run_experimental_pipeline_phases as _run_experimental_pipeline_phases,
    run_full_build_steps as _run_full_build_steps,
    run_phases_parallel as _run_phases_parallel,
)
from .runner_parts.config import RunConfig, validate_run_config_paths as _validate_run_config_paths
from .runner_parts.full import run_full_pipeline_impl
from .runner_parts.full_runtime import (
    clear_runtime_trace_dir as _clear_runtime_trace_dir,
    run_full_pipeline_with_runtime_overlay_impl,
)
from .runner_parts.hooks import (
    dynamic_findings_count as _dynamic_findings_count,
    fire_hooks as _fire_hooks,
    merge_hook_summaries as _merge_hook_summaries,
)
from .runner_parts.incremental import run_incremental_pipeline_impl

__all__ = [
    "RunConfig",
    "_clear_runtime_trace_dir",
    "_count_valid_runtime_observations",
    "_dynamic_findings_count",
    "_fire_hooks",
    "_merge_hook_summaries",
    "_run_experimental_pipeline_phases",
    "_run_full_build_steps",
    "_run_phases_parallel",
    "_validate_run_config_paths",
    "run_full_pipeline",
    "run_full_pipeline_with_runtime_overlay",
    "run_incremental_pipeline",
]


def run_full_pipeline(config: RunConfig) -> dict[str, int]:
    """Run a full static rebuild through the focused runner modules."""
    return run_full_pipeline_impl(
        config,
        graph_store_cls=GraphStore,
        run_full_build_steps=_run_full_build_steps,
        run_experimental_pipeline_phases=_run_experimental_pipeline_phases,
        fire_hooks=_fire_hooks,
        count_valid_runtime_observations=_count_valid_runtime_observations,
    )


def run_incremental_pipeline(config: RunConfig) -> dict[str, int]:
    """Run an incremental sync through the focused runner modules."""
    return run_incremental_pipeline_impl(
        config,
        graph_store_cls=GraphStore,
        run_phases_parallel=_run_phases_parallel,
        run_experimental_pipeline_phases=_run_experimental_pipeline_phases,
        fire_hooks=_fire_hooks,
        count_valid_runtime_observations=_count_valid_runtime_observations,
    )


def run_full_pipeline_with_runtime_overlay(
    config: RunConfig,
    *,
    pytest_targets: list[str] | None = None,
) -> dict[str, int]:
    """Run the canonical full-power sync flow with runtime-plan execution."""
    return run_full_pipeline_with_runtime_overlay_impl(
        config,
        pytest_targets=pytest_targets,
        graph_store_cls=GraphStore,
        run_full_build_steps=_run_full_build_steps,
        run_experimental_pipeline_phases=_run_experimental_pipeline_phases,
        fire_hooks=_fire_hooks,
        merge_hook_summaries=_merge_hook_summaries,
        count_valid_runtime_observations=_count_valid_runtime_observations,
        resolve_runtime_plan=resolve_runtime_plan,
    )
