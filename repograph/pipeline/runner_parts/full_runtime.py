"""Coordinator for full rebuilds with runtime-mode execution and overlay merge.

This module owns the only runner path that actively executes a runtime plan.
Static rebuild, runtime-plan execution, and final overlay/export phases stay
grouped here so that the generic full/incremental coordinators do not absorb
runtime-specific policy again.
"""
from __future__ import annotations

import os
import shutil
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
from repograph.runtime.execution import (
    apply_runtime_plan_metadata,
    build_dynamic_analysis_state,
    execute_runtime_plan,
)
from repograph.runtime.orchestration import (
    RuntimePlan,
    describe_attach_outcome,
    describe_attach_policy,
    describe_live_target,
    describe_runtime_mode,
    describe_runtime_reason,
    describe_runtime_resolution,
    describe_trace_collection,
)
from repograph.runtime.session import RuntimeCleanupResult, RuntimeExecutionResult
from rich.panel import Panel

from .config import RunConfig, validate_run_config_paths
from .shared import close_store_quietly, console, logger, phase_scope

__all__ = ["clear_runtime_trace_dir", "run_full_pipeline_with_runtime_overlay_impl"]


def clear_runtime_trace_dir(repograph_dir: str) -> None:
    """Remove stale overlay-input traces while preserving live-session state."""
    trace_dir = Path(repograph_dir) / "runtime"
    trace_dir.mkdir(parents=True, exist_ok=True)
    for child in trace_dir.iterdir():
        if child.is_file() and child.suffix == ".jsonl":
            child.unlink()
            continue
        if child.is_dir() and child.name not in {"live", "live_sessions"}:
            shutil.rmtree(child, ignore_errors=True)


def _runtime_command_preview(command: tuple[str, ...]) -> str:
    if not command:
        return "none"
    return " ".join(command)


def _runtime_plan_lines(runtime_plan: RuntimePlan) -> list[str]:
    lines = [
        f"[bold white]Runtime mode:[/] {describe_runtime_mode(runtime_plan.mode)}",
        f"[bold white]Selection:[/] {describe_runtime_resolution(runtime_plan.resolution)}",
        f"[bold white]Trace collection:[/] {describe_trace_collection(runtime_plan.mode)}",
    ]
    if runtime_plan.command:
        lines.append(
            f"[bold white]Command:[/] [dim]{_runtime_command_preview(runtime_plan.command)}[/]"
        )
    if runtime_plan.probe_url:
        lines.append(f"[bold white]Probe URL:[/] {runtime_plan.probe_url}")
    if runtime_plan.scenario_urls:
        scenario_list = ", ".join(runtime_plan.scenario_urls)
        lines.append(f"[bold white]Scenario URLs:[/] {scenario_list}")
    if runtime_plan.scenario_driver_command:
        lines.append(
            "[bold white]Scenario driver:[/] "
            f"[dim]{_runtime_command_preview(runtime_plan.scenario_driver_command)}[/]"
        )
    if runtime_plan.detected_targets:
        lines.append(
            f"[bold white]Detected live targets:[/] {len(runtime_plan.detected_targets)}"
        )
        for target in runtime_plan.detected_targets:
            lines.append(f"  • {describe_live_target(target)}")
    attach_reason = ""
    if runtime_plan.attach_decision.present:
        attach_reason = describe_runtime_reason(runtime_plan.attach_decision.reason)
        lines.append(
            "[bold white]Attach decision:[/] "
            f"{describe_attach_outcome(runtime_plan.attach_decision.outcome)}"
        )
        lines.append(
            "[bold white]Attach policy:[/] "
            f"{describe_attach_policy(runtime_plan.attach_decision.policy)}"
        )
        if runtime_plan.attach_decision.target is not None:
            lines.append(
                "[bold white]Attach target:[/] "
                f"{describe_live_target(runtime_plan.attach_decision.target)}"
            )
        if runtime_plan.attach_decision.reason:
            lines.append(
                "[bold white]Attach detail:[/] "
                f"{attach_reason}"
            )
        approval = runtime_plan.attach_decision.approval
        if approval.outcome != "not_applicable":
            approval_reason = describe_runtime_reason(approval.reason)
            lines.append(
                "[bold white]Attach approval:[/] "
                f"{approval.outcome}"
            )
            if approval_reason:
                lines.append(
                    "[bold white]Attach approval detail:[/] "
                    f"{approval_reason}"
                )
    fallback_reason = describe_runtime_reason(runtime_plan.fallback_reason)
    if runtime_plan.fallback_reason and fallback_reason != attach_reason:
        lines.append(
            "[bold white]Fallback:[/] "
            f"{fallback_reason}"
        )
    if runtime_plan.skip_reason:
        lines.append(
            "[bold white]Will skip runtime execution:[/] "
            f"{describe_runtime_reason(runtime_plan.skip_reason)}"
        )
    return lines


def _print_runtime_plan(runtime_plan: RuntimePlan) -> None:
    console.print(
        Panel(
            "\n".join(_runtime_plan_lines(runtime_plan)),
            title="[bold cyan]Dynamic Analysis Plan[/]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


def _cleanup_status_text(cleanup: RuntimeCleanupResult | None) -> str:
    if cleanup is None:
        return "not applicable"
    return cleanup.status_label


def _runtime_result_lines(
    runtime_plan: RuntimePlan,
    runtime_result: RuntimeExecutionResult,
) -> list[str]:
    input_state = runtime_result.input_state
    effective_mode = describe_runtime_mode(runtime_result.executed_mode)
    lines = [
        f"[bold white]Executed:[/] {'yes' if runtime_result.executed else 'no'}",
        f"[bold white]Runtime mode:[/] {effective_mode}",
        f"[bold white]Trace files:[/] {input_state.trace_file_count}",
        f"[bold white]Trace records:[/] {input_state.trace_record_count:,}",
        f"[bold white]Cleanup:[/] {_cleanup_status_text(runtime_result.cleanup)}",
    ]
    if runtime_result.executed_mode != runtime_plan.mode:
        lines.append(
            "[bold white]Selected mode:[/] "
            f"{describe_runtime_mode(runtime_plan.mode)}"
        )
    if runtime_result.fallback is not None:
        fallback = runtime_result.fallback
        lines.append(
            "[bold white]Fallback execution:[/] "
            f"{describe_runtime_mode(fallback.from_mode)} -> "
            f"{describe_runtime_mode(fallback.to_mode)} "
            f"({'ok' if fallback.succeeded else 'failed'})"
        )
        if fallback.reason:
            lines.append(f"[bold white]Fallback detail:[/] {fallback.reason}")
    if runtime_result.pytest_exit_code is not None:
        lines.append(f"[bold white]Test command exit:[/] {runtime_result.pytest_exit_code}")
    scenario_actions = runtime_result.scenario_actions
    if scenario_actions.present:
        lines.append(
            "[bold white]Scenarios:[/] "
            f"{scenario_actions.successful_count} ok / "
            f"{scenario_actions.failed_count} failed"
        )
        driver = scenario_actions.driver
        if driver is not None:
            lines.append(
                "[bold white]Scenario driver:[/] "
                f"{'ok' if driver.ok else 'failed'}"
            )
    if runtime_result.attempts:
        lines.append(
            "[bold white]Attempts:[/] "
            + "  ->  ".join(
                f"{attempt.phase}:{describe_runtime_mode(attempt.mode)}={attempt.outcome}"
                for attempt in runtime_result.attempts
            )
        )
    return lines


def _print_runtime_result(
    runtime_plan: RuntimePlan,
    runtime_result: RuntimeExecutionResult,
) -> None:
    console.print(
        Panel(
            "\n".join(_runtime_result_lines(runtime_plan, runtime_result)),
            title="[bold cyan]Dynamic Analysis Result[/]",
            border_style="cyan",
            padding=(0, 2),
        )
    )


def run_full_pipeline_with_runtime_overlay_impl(
    config: RunConfig,
    *,
    pytest_targets: list[str] | None,
    graph_store_cls: Callable[[str], Any],
    run_full_build_steps: Callable[[RunConfig, Any], tuple[list[FileRecord], list[ParsedFile]]],
    run_experimental_pipeline_phases: Callable[[RunConfig, Any, list[ParsedFile]], None],
    fire_hooks: Callable[..., dict[str, Any]],
    merge_hook_summaries: Callable[..., dict[str, Any]],
    count_valid_runtime_observations: Callable[[Any], int],
    resolve_runtime_plan: Callable[..., Any],
) -> dict[str, int]:
    """Run a full rebuild plus automatic traced runtime analysis in one command."""
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
    set_obs_context(phase="full_sync_runtime_overlay")
    logger.info(
        "full pipeline with runtime overlay started",
        repo_root=config.repo_root,
        run_id=run_id,
    )

    write_sync_lock(
        config.repograph_dir,
        mode="full",
        repo_root=config.repo_root,
        phase="starting",
    )
    store: Any = None
    files: list[FileRecord] = []
    parsed: list[ParsedFile] = []
    last_stats: dict[str, int] | None = None
    static_hook_summary: dict[str, Any] = {}
    final_hook_summary: dict[str, Any] = {}
    dynamic_analysis: dict[str, Any] = build_dynamic_analysis_state()

    try:
        db_path = os.path.join(config.repograph_dir, "graph.db")
        console.print("[cyan]Step 1/3: full static pipeline...[/]")
        _delete_db_dir(db_path)
        store = graph_store_cls(db_path)
        store.initialize_schema()
        with phase_scope("dynamic_full.step1_static_rebuild"):
            files, parsed = run_full_build_steps(config, store)
            run_experimental_pipeline_phases(config, store, parsed)
            static_hook_summary = fire_hooks(
                config,
                store,
                parsed,
                run_graph_built=True,
                run_dynamic=False,
                run_evidence=False,
                run_export=False,
            )
        IncrementalDiff(config.repograph_dir).save_index({record.path: record for record in files})
        last_stats = store.get_stats()
        store.close()
        store = None

        runtime_plan = resolve_runtime_plan(
            config.repo_root,
            repograph_dir=config.repograph_dir,
            pytest_targets=pytest_targets,
            attach_policy=config.runtime_attach_policy,
            attach_approval_resolver=config.runtime_attach_approval_resolver,
        )
        apply_runtime_plan_metadata(dynamic_analysis, runtime_plan)
        _print_runtime_plan(runtime_plan)
        clear_runtime_trace_dir(config.repograph_dir)

        if not runtime_plan.executed:
            console.print(
                "[yellow]Step 2/3: dynamic analysis will not run.[/] "
                "Step 3 will finalize the static rebuild without fresh runtime traces."
            )
            runtime_result = execute_runtime_plan(
                runtime_plan,
                repo_root=config.repo_root,
                repograph_dir=config.repograph_dir,
                strict=config.strict,
            )
            dynamic_analysis.update(runtime_result.to_analysis_update())
            _print_runtime_result(runtime_plan, runtime_result)
        else:
            if runtime_plan.mode == "managed_python_server":
                console.print(
                    "[cyan]Step 2/3: dynamic analysis via "
                    f"{describe_runtime_mode(runtime_plan.mode)}[/]"
                )
                with phase_scope(
                    "dynamic_full.step2_managed_runtime",
                    resolution=dynamic_analysis["resolution"],
                    command_len=len(runtime_plan.command),
                    scenario_count=len(runtime_plan.scenario_urls),
                ):
                    runtime_result = execute_runtime_plan(
                        runtime_plan,
                        repo_root=config.repo_root,
                        repograph_dir=config.repograph_dir,
                        strict=config.strict,
                        fallback_plan_resolver=lambda _failed_plan: resolve_runtime_plan(
                            config.repo_root,
                            repograph_dir=config.repograph_dir,
                            pytest_targets=pytest_targets,
                            attach_policy="never",
                        ),
                    )
            elif runtime_plan.mode == "attach_live_python":
                console.print(
                    "[cyan]Step 2/3: dynamic analysis via "
                    f"{describe_runtime_mode(runtime_plan.mode)}[/]"
                )
                with phase_scope(
                    "dynamic_full.step2_live_attach",
                    resolution=dynamic_analysis["resolution"],
                    live_target_count=len(runtime_plan.detected_targets),
                    scenario_count=len(runtime_plan.scenario_urls),
                ):
                    runtime_result = execute_runtime_plan(
                        runtime_plan,
                        repo_root=config.repo_root,
                        repograph_dir=config.repograph_dir,
                        strict=config.strict,
                        fallback_plan_resolver=lambda _failed_plan: resolve_runtime_plan(
                            config.repo_root,
                            repograph_dir=config.repograph_dir,
                            pytest_targets=pytest_targets,
                            attach_policy="never",
                        ),
                    )
            else:
                console.print(
                    "[cyan]Step 2/3: dynamic analysis via "
                    f"{describe_runtime_mode(runtime_plan.mode)}[/]"
                )
                with phase_scope(
                    "dynamic_full.step2_traced_tests",
                    resolution=dynamic_analysis["resolution"],
                    command_len=len(runtime_plan.command),
                ):
                    runtime_result = execute_runtime_plan(
                        runtime_plan,
                        repo_root=config.repo_root,
                        repograph_dir=config.repograph_dir,
                        strict=config.strict,
                        fallback_plan_resolver=lambda _failed_plan: resolve_runtime_plan(
                            config.repo_root,
                            repograph_dir=config.repograph_dir,
                            pytest_targets=pytest_targets,
                            attach_policy="never",
                        ),
                    )
            dynamic_analysis.update(runtime_result.to_analysis_update())
            _print_runtime_result(runtime_plan, runtime_result)
            for warning in runtime_result.warnings:
                if runtime_result.pytest_exit_code not in (None, 0):
                    result_code = int(runtime_result.pytest_exit_code)
                    message = f"test command exited with code {result_code}"
                    if config.strict:
                        raise RuntimeError(message)
                    console.print(
                        f"[yellow]{message} — continuing with any collected traces "
                        "(use [bold]--strict[/] on sync to abort on test failures)[/]"
                    )
                    continue
                console.print(
                    f"[yellow]{warning} — continuing with any collected traces "
                    "(use [bold]--strict[/] on sync to abort on runtime failures)[/]"
                )

        if dynamic_analysis.get("inputs_present"):
            console.print(
                "[cyan]Step 3/3: finalizing evidence, exports, and runtime overlay...[/]"
            )
        else:
            console.print(
                "[cyan]Step 3/3: finalizing evidence and exports without runtime overlay inputs...[/]"
            )
        store = graph_store_cls(db_path)
        store.initialize_schema()
        with phase_scope(
            "dynamic_full.step3_finalize_overlay",
            trace_file_count=dynamic_analysis["trace_file_count"],
        ):
            final_hook_summary = fire_hooks(
                config,
                store,
                [],
                run_graph_built=False,
                run_dynamic=bool(dynamic_analysis.get("inputs_present")),
                run_evidence=True,
                run_export=True,
            )
        dynamic_plugins = (
            (final_hook_summary.get("dynamic_stage") or {}).get("plugins") or {}
        )
        dynamic_analysis["dynamic_findings_count"] = int(
            final_hook_summary.get("dynamic_findings_count") or 0
        )
        dynamic_analysis["overlay_persisted_functions"] = count_valid_runtime_observations(store)
        dynamic_analysis["runtime_overlay_applied"] = bool(
            dynamic_analysis["trace_file_count"] > 0
            and (dynamic_plugins.get("dynamic_analyzer.runtime_overlay") or {}).get("executed")
        )
        dynamic_analysis["coverage_overlay_applied"] = bool(
            dynamic_analysis["coverage_json_present"]
            and (dynamic_plugins.get("dynamic_analyzer.coverage_overlay") or {}).get("executed")
        )
        last_stats = store.get_stats()
        sync_mode = (
            "full_with_runtime_overlay"
            if dynamic_analysis["runtime_overlay_applied"]
            else "full"
        )
        assert last_stats is not None
        write_health_json(
            config.repograph_dir,
            build_health_report(
                store,
                last_stats,
                repo_root=config.repo_root,
                repograph_dir=config.repograph_dir,
                sync_mode=sync_mode,
                files_walked=len(files),
                strict=config.strict,
                hook_summary=merge_hook_summaries(static_hook_summary, final_hook_summary),
                dynamic_analysis=dynamic_analysis,
            ),
        )
        return last_stats

    except BaseException as exc:
        partial = last_stats
        if partial is None and store is not None:
            try:
                partial = store.get_stats()
            except Exception as stats_exc:
                logger.warning(
                    "store.get_stats() failed during error recovery",
                    exc_msg=str(stats_exc),
                )
        error_phase = (
            "tests" if dynamic_analysis.get("pytest_exit_code") not in (None, 0) else "pipeline"
        )
        try:
            write_health_json(
                config.repograph_dir,
                build_health_failure_report(
                    repo_root=config.repo_root,
                    repograph_dir=config.repograph_dir,
                    sync_mode=(
                        "full_with_runtime_overlay"
                        if dynamic_analysis.get("executed")
                        else "full"
                    ),
                    error_phase=error_phase,
                    error_message=f"{type(exc).__name__}: {exc}",
                    strict=config.strict,
                    partial_stats=partial,
                    dynamic_analysis=dynamic_analysis,
                ),
            )
        except Exception as health_exc:
            logger.warning(
                "write_health_json failed during error recovery",
                exc_msg=str(health_exc),
            )
        logger.error(
            "full pipeline with runtime overlay failed",
            exc_type=type(exc).__name__,
            exc_msg=str(exc),
        )
        console.print(f"[red bold]Full sync failed:[/] {exc}")
        raise
    finally:
        clear_sync_lock(config.repograph_dir)
        close_store_quietly(store)
        shutdown_observability()
