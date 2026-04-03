"""Coordinator for incremental sync orchestration."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from repograph.core.models import ParsedFile
from repograph.observability import (
    ObservabilityConfig,
    init_observability,
    new_run_id,
    set_obs_context,
    shutdown_observability,
)
from repograph.parsing.symbol_table import SymbolTable
from repograph.runtime.orchestration import dynamic_input_state
from repograph.runtime.execution import build_dynamic_input_analysis_state

from .build import get_function_ids_in_paths
from .config import RunConfig, validate_run_config_paths
from .shared import close_store_quietly, console, ensure_scheduler_bootstrapped, logger

__all__ = ["run_incremental_pipeline_impl"]


def run_incremental_pipeline_impl(
    config: RunConfig,
    *,
    graph_store_cls: Callable[[str], Any],
    run_phases_parallel: Callable[..., None],
    run_experimental_pipeline_phases: Callable[[RunConfig, Any, list[ParsedFile]], None],
    fire_hooks: Callable[..., dict[str, Any]],
    count_valid_runtime_observations: Callable[[Any], int],
) -> dict[str, int]:
    """Run incremental sync over changed files and affected callers/importers."""
    from repograph.docs.staleness import StalenessTracker
    from repograph.pipeline.health import (
        build_health_failure_report,
        build_health_report,
        write_health_json,
    )
    from repograph.pipeline.incremental import (
        IncrementalDiff,
        expand_reparse_paths_for_incremental,
    )
    from repograph.pipeline.phases import p01_walk, p03_parse, p09_communities, p10_processes
    from repograph.pipeline.phases import p03b_framework_tags
    from repograph.pipeline.sync_state import clear_sync_lock, write_sync_lock

    run_id = new_run_id()
    validate_run_config_paths(config)
    init_observability(
        ObservabilityConfig(
            log_dir=Path(config.repograph_dir) / "logs",
            run_id=run_id,
        )
    )
    set_obs_context(phase="incremental_sync")
    logger.info("incremental pipeline started", repo_root=config.repo_root, run_id=run_id)

    write_sync_lock(
        config.repograph_dir,
        mode="incremental",
        repo_root=config.repo_root,
        phase="starting",
    )
    store: Any = None
    parsed: list[ParsedFile] = []

    try:
        db_path = os.path.join(config.repograph_dir, "graph.db")
        store = graph_store_cls(db_path)
        store.initialize_schema()

        staleness = StalenessTracker(config.repograph_dir)
        differ = IncrementalDiff(config.repograph_dir)

        current_files = p01_walk.run(config.repo_root)
        current_map = {record.path: record for record in current_files}
        diff = differ.compute(current_map)

        if not diff.added and not diff.removed and not diff.changed:
            dynamic_inputs = dynamic_input_state(config.repo_root, config.repograph_dir)
            if dynamic_inputs.inputs_present:
                console.print(
                    "[cyan]No source file changes; refreshing derived index data and "
                    "merging available runtime / coverage inputs...[/]"
                )
                parsed = []
                store.clear_communities()
                store.clear_pathways()
                store.clear_processes()
                p09_communities.run(store, min_community_size=config.min_community_size)
                p10_processes.run(store)
                run_experimental_pipeline_phases(config, store, parsed)
                hook_summary = fire_hooks(config, store, parsed)
                differ.save_index(current_map)
                staleness.save()
                stats = store.get_stats()
                dynamic_analysis = build_dynamic_input_analysis_state(
                    repo_root=config.repo_root,
                    repograph_dir=config.repograph_dir,
                    dynamic_inputs_enabled=True,
                    input_state=dynamic_inputs,
                    hook_summary=hook_summary,
                    overlay_persisted_functions=count_valid_runtime_observations(store),
                    dynamic_findings_count=int(hook_summary.get("dynamic_findings_count") or 0),
                    resolution="incremental_traces_only",
                )
                write_health_json(
                    config.repograph_dir,
                    build_health_report(
                        store,
                        stats,
                        repo_root=config.repo_root,
                        repograph_dir=config.repograph_dir,
                        sync_mode="incremental_traces_only",
                        files_walked=len(current_files),
                        strict=config.strict,
                        hook_summary=hook_summary,
                        dynamic_analysis=dynamic_analysis,
                    ),
                )
                return stats

            console.print("[green]Already up to date.[/]")
            stats = store.get_stats()
            write_health_json(
                config.repograph_dir,
                build_health_report(
                    store,
                    stats,
                    repo_root=config.repo_root,
                    repograph_dir=config.repograph_dir,
                    sync_mode="incremental_unchanged",
                    files_walked=len(current_files),
                    strict=config.strict,
                ),
            )
            return stats

        console.print(
            f"[cyan]Incremental: +{len(diff.added)} added, "
            f"~{len(diff.changed)} changed, -{len(diff.removed)} removed[/]"
        )

        current_path_set = set(current_map.keys())
        reparse_paths = expand_reparse_paths_for_incremental(
            store,
            added=diff.added,
            changed=diff.changed,
            removed=diff.removed,
            current_paths=current_path_set,
        )
        extra = len(reparse_paths - (diff.added | diff.changed))
        if extra:
            console.print(
                f"  [dim]also re-parsing {extra} caller/importer file(s) to restore CALLS[/]"
            )

        for path in diff.removed:
            store.delete_file_nodes(path)
            console.print(f"  [red]removed[/] {path}")

        for path in diff.changed:
            store.delete_file_nodes(path)
            staleness.mark_stale_for_file(path)
            console.print(f"  [yellow]changed[/] {path}")

        reparse_files = [record for record in current_files if record.path in reparse_paths]

        if reparse_files:
            symbol_table = SymbolTable()
            for fn_dict in store.get_all_functions_for_symbol_table():
                if fn_dict["file_path"] not in reparse_paths:
                    symbol_table.add_function_from_dict(fn_dict)
            for cls_dict in store.get_all_classes_for_symbol_table():
                if cls_dict["file_path"] not in reparse_paths:
                    symbol_table.add_class_from_dict(cls_dict)

            ensure_scheduler_bootstrapped()
            parsed = p03_parse.run(reparse_files, store, symbol_table)
            p03b_framework_tags.run(parsed, store)
            run_phases_parallel(
                config,
                parsed,
                store,
                symbol_table,
                include_git=False,
                reparse_paths=reparse_paths,
            )

        store.clear_pathways()
        store.clear_processes()

        community_snapshot = p09_communities.load_community_snapshot(config.repograph_dir)
        did_partial = False
        if community_snapshot and reparse_paths:
            changed_functions = get_function_ids_in_paths(store, reparse_paths)
            total_functions = community_snapshot.get("total_functions", 0)
            if (
                total_functions > 0
                and len(changed_functions)
                < total_functions * p09_communities._PARTIAL_RERUN_THRESHOLD
            ):
                did_partial = p09_communities.run_partial(
                    store,
                    changed_functions,
                    min_community_size=config.min_community_size,
                )

        if not did_partial:
            store.clear_communities()
            p09_communities.run(store, min_community_size=config.min_community_size)

        p09_communities.save_community_snapshot(config.repograph_dir, store)
        p10_processes.run(store)

        run_experimental_pipeline_phases(config, store, parsed)
        hook_summary = fire_hooks(config, store, parsed)

        differ.save_index(current_map)
        staleness.save()

        stats = store.get_stats()
        dynamic_analysis = build_dynamic_input_analysis_state(
            repo_root=config.repo_root,
            repograph_dir=config.repograph_dir,
            dynamic_inputs_enabled=True,
            hook_summary=hook_summary,
            overlay_persisted_functions=count_valid_runtime_observations(store),
            dynamic_findings_count=int(hook_summary.get("dynamic_findings_count") or 0),
        )
        write_health_json(
            config.repograph_dir,
            build_health_report(
                store,
                stats,
                repo_root=config.repo_root,
                repograph_dir=config.repograph_dir,
                sync_mode="incremental",
                files_walked=len(current_files),
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
                    sync_mode="incremental",
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
        logger.error(
            "incremental pipeline failed",
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
        )
        console.print(f"[red bold]Incremental sync failed:[/] {exc}")
        raise
    finally:
        clear_sync_lock(config.repograph_dir)
        close_store_quietly(store)
        shutdown_observability()
