"""Coordinator for full static rebuild orchestration."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from repograph.core.models import FileRecord, ParsedFile
from repograph.observability import (
    ObservabilityConfig,
    init_observability,
    new_run_id,
    set_obs_context,
    shutdown_observability,
)
from repograph.runtime.execution import build_dynamic_input_analysis_state

from .config import RunConfig, validate_run_config_paths
from .shared import close_store_quietly, console, logger

__all__ = ["run_full_pipeline_impl"]


def run_full_pipeline_impl(
    config: RunConfig,
    *,
    graph_store_cls: Callable[[str], Any],
    run_full_build_steps: Callable[[RunConfig, Any], tuple[list[FileRecord], list[ParsedFile]]],
    run_experimental_pipeline_phases: Callable[[RunConfig, Any, list[ParsedFile]], None],
    fire_hooks: Callable[..., dict[str, Any]],
    count_valid_runtime_observations: Callable[[Any], int],
) -> dict[str, int]:
    """Run the full graph-build pipeline against a repository."""
    from repograph.graph_store.store import _delete_db_dir
    from repograph.pipeline.health import (
        build_health_failure_report,
        build_health_report,
        write_health_json,
    )
    from repograph.pipeline.incremental import IncrementalDiff
    from repograph.pipeline.sync_state import clear_sync_lock, write_sync_lock

    run_id = new_run_id()
    validate_run_config_paths(config)
    init_observability(
        ObservabilityConfig(
            log_dir=Path(config.repograph_dir) / "logs",
            run_id=run_id,
        )
    )
    set_obs_context(phase="full_sync")
    logger.info("full pipeline started", repo_root=config.repo_root, run_id=run_id)

    write_sync_lock(
        config.repograph_dir,
        mode="full",
        repo_root=config.repo_root,
        phase="starting",
    )
    store: Any = None
    files: list[FileRecord] = []
    parsed: list[ParsedFile] = []

    try:
        db_path = os.path.join(config.repograph_dir, "graph.db")
        _delete_db_dir(db_path)
        store = graph_store_cls(db_path)
        store.initialize_schema()
        files, parsed = run_full_build_steps(config, store)
        run_experimental_pipeline_phases(config, store, parsed)
        hook_summary = fire_hooks(
            config,
            store,
            parsed,
            run_dynamic=config.allow_dynamic_inputs,
        )
        differ = IncrementalDiff(config.repograph_dir)
        differ.save_index({record.path: record for record in files})

        stats = store.get_stats()
        dynamic_analysis = build_dynamic_input_analysis_state(
            repo_root=config.repo_root,
            repograph_dir=config.repograph_dir,
            dynamic_inputs_enabled=config.allow_dynamic_inputs,
            hook_summary=hook_summary,
            overlay_persisted_functions=count_valid_runtime_observations(store),
            dynamic_findings_count=int(hook_summary.get("dynamic_findings_count") or 0),
            skipped_reason="dynamic_inputs_disabled" if not config.allow_dynamic_inputs else "",
        )
        write_health_json(
            config.repograph_dir,
            build_health_report(
                store,
                stats,
                repo_root=config.repo_root,
                repograph_dir=config.repograph_dir,
                sync_mode="full",
                files_walked=len(files),
                strict=config.strict,
                hook_summary=hook_summary,
                dynamic_analysis=dynamic_analysis,
            ),
        )
        return stats

    except BaseException as exc:
        partial = None
        if store is not None:
            try:
                partial = store.get_stats()
            except Exception as stats_exc:
                logger.warning(
                    "store.get_stats() failed during error recovery",
                    exc_msg=str(stats_exc),
                )
        try:
            write_health_json(
                config.repograph_dir,
                build_health_failure_report(
                    repo_root=config.repo_root,
                    repograph_dir=config.repograph_dir,
                    sync_mode="full",
                    error_phase="pipeline",
                    error_message=f"{type(exc).__name__}: {exc}",
                    strict=config.strict,
                    partial_stats=partial,
                ),
            )
        except Exception as health_exc:
            logger.warning(
                "write_health_json failed during error recovery",
                exc_msg=str(health_exc),
            )
        logger.error("full pipeline failed", exc_type=type(exc).__name__, exc_msg=str(exc))
        console.print(f"[red bold]Sync failed:[/] {exc}")
        raise
    finally:
        clear_sync_lock(config.repograph_dir)
        close_store_quietly(store)
        shutdown_observability()
