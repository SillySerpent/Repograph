"""Runtime execution helpers for full-power sync orchestration.

This module owns execution-time behavior after runtime planning is complete:
single-attempt dispatch, attach-failure fallback, and normalization of the
result contract used by health/report/output surfaces.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from repograph.runtime.attach import execute_live_attach
from repograph.runtime.ephemeral import (
    run_command_under_trace,
    spawn_command_under_trace,
    stop_command_under_trace,
)
from repograph.runtime.orchestration import RuntimePlan, dynamic_input_state
from repograph.runtime.session import (
    DynamicInputInventory,
    RuntimeCleanupResult,
    RuntimeAttemptOutcome,
    RuntimeExecutionAttempt,
    RuntimeExecutionResult,
    RuntimeFallbackExecution,
    RuntimeScenarioActions,
    RuntimeSessionTarget,
)
from repograph.runtime.scenario import (
    drive_http_scenarios,
    run_scenario_driver,
    wait_for_http_ready,
)

__all__ = [
    "RuntimeExecutionResult",
    "build_dynamic_analysis_state",
    "build_dynamic_input_analysis_state",
    "apply_runtime_plan_metadata",
    "execute_runtime_plan",
]


def build_dynamic_analysis_state(*, requested: bool = True) -> dict[str, Any]:
    """Return the default runtime-analysis payload persisted into health JSON."""
    return {
        "requested": requested,
        "mode": "none",
        "executed_mode": "none",
        "executed": False,
        "resolution": "",
        "fallback_reason": "",
        "attach_outcome": "not_applicable",
        "attach_reason": "",
        "attach_mode": "none",
        "attach_candidate_count": 0,
        "attach_target": {},
        "attach_strategy": "",
        "attach_policy": "prompt",
        "attach_approval_outcome": "not_applicable",
        "attach_approval_reason": "",
        "test_command": [],
        "skipped_reason": "",
        "detected_live_target_count": 0,
        "detected_live_targets": [],
        "chosen_target": {},
        "scenario_actions": {},
        "cleanup": {},
        "pytest_exit_code": None,
        "execution_attempts": [],
        "fallback_execution": {},
        "inputs_present": False,
        "trace_file_count": 0,
        "trace_record_count": 0,
        "overlay_persisted_functions": 0,
        "dynamic_findings_count": 0,
        "coverage_json_present": False,
        "runtime_overlay_applied": False,
        "coverage_overlay_applied": False,
    }


def _dynamic_plugin_executed(hook_summary: dict[str, Any] | None, plugin_id: str) -> bool:
    dynamic_stage = (hook_summary or {}).get("dynamic_stage") or {}
    plugins = dynamic_stage.get("plugins") or {}
    plugin_state = plugins.get(plugin_id)
    return bool(isinstance(plugin_state, dict) and plugin_state.get("executed"))


def build_dynamic_input_analysis_state(
    *,
    repo_root: str,
    repograph_dir: str,
    dynamic_inputs_enabled: bool,
    input_state: DynamicInputInventory | dict[str, Any] | None = None,
    hook_summary: dict[str, Any] | None = None,
    overlay_persisted_functions: int = 0,
    dynamic_findings_count: int = 0,
    resolution: str = "existing_dynamic_inputs",
    skipped_reason: str = "",
) -> dict[str, Any] | None:
    """Build a normalized health payload for syncs that only process existing inputs.

    This is used by static full and incremental syncs that may merge already
    collected trace files or ``coverage.json`` without running a runtime
    command in the current sync.
    """
    inventory = (
        input_state
        if isinstance(input_state, DynamicInputInventory)
        else DynamicInputInventory.from_mapping(input_state)
    )
    if not inventory.inputs_present:
        inventory = dynamic_input_state(repo_root, repograph_dir)
    if not inventory.inputs_present:
        return None

    requested = bool(dynamic_inputs_enabled)
    payload = build_dynamic_analysis_state(requested=requested)
    payload.update(inventory.to_dict())
    payload["executed"] = requested
    payload["dynamic_findings_count"] = int(dynamic_findings_count)
    payload["overlay_persisted_functions"] = int(overlay_persisted_functions)
    payload["runtime_overlay_applied"] = bool(
        inventory.trace_file_count > 0
        and _dynamic_plugin_executed(hook_summary, "dynamic_analyzer.runtime_overlay")
    )
    payload["coverage_overlay_applied"] = bool(
        inventory.coverage_json_present
        and _dynamic_plugin_executed(hook_summary, "dynamic_analyzer.coverage_overlay")
    )

    if requested:
        payload["mode"] = "existing_inputs"
        payload["resolution"] = resolution
    elif skipped_reason:
        payload["skipped_reason"] = skipped_reason

    return payload


def apply_runtime_plan_metadata(dynamic_analysis: dict[str, Any], runtime_plan: RuntimePlan) -> None:
    """Copy resolved runtime-plan metadata into the health-analysis payload."""
    dynamic_analysis["mode"] = runtime_plan.mode
    dynamic_analysis["resolution"] = runtime_plan.resolution
    dynamic_analysis["fallback_reason"] = runtime_plan.fallback_reason
    dynamic_analysis["attach_outcome"] = runtime_plan.attach_decision.outcome
    dynamic_analysis["attach_reason"] = runtime_plan.attach_decision.reason
    dynamic_analysis["attach_mode"] = runtime_plan.attach_decision.attach_mode
    dynamic_analysis["attach_candidate_count"] = runtime_plan.attach_decision.candidate_count
    dynamic_analysis["attach_strategy"] = runtime_plan.attach_decision.strategy_id
    dynamic_analysis["attach_policy"] = runtime_plan.attach_decision.policy
    dynamic_analysis["attach_approval_outcome"] = runtime_plan.attach_decision.approval.outcome
    dynamic_analysis["attach_approval_reason"] = runtime_plan.attach_decision.approval.reason
    dynamic_analysis["attach_target"] = (
        runtime_plan.attach_decision.target.to_dict()
        if runtime_plan.attach_decision.target is not None
        else {}
    )
    dynamic_analysis["test_command"] = list(runtime_plan.command)
    dynamic_analysis["skipped_reason"] = runtime_plan.skip_reason
    dynamic_analysis["detected_live_target_count"] = len(runtime_plan.detected_targets)
    dynamic_analysis["detected_live_targets"] = [
        target.to_dict() for target in runtime_plan.detected_targets
    ]


def _run_runtime_scenarios(
    runtime_plan: RuntimePlan,
    *,
    repo_root: str,
) -> RuntimeScenarioActions:
    http_actions = (
        drive_http_scenarios(
            probe_url=runtime_plan.probe_url,
            scenario_urls=runtime_plan.scenario_urls,
        )
        if runtime_plan.scenario_urls
        else None
    )
    driver_actions = (
        run_scenario_driver(
            list(runtime_plan.scenario_driver_command),
            repo_root=repo_root,
            probe_url=runtime_plan.probe_url,
            timeout_seconds=float(runtime_plan.ready_timeout),
        )
        if runtime_plan.scenario_driver_command
        else None
    )
    return RuntimeScenarioActions.from_components(
        http_actions=http_actions,
        driver_actions=driver_actions,
    )


def _handle_driver_failure(
    scenario_actions: RuntimeScenarioActions,
    *,
    strict: bool,
    warnings: list[str],
    context_label: str,
) -> None:
    if scenario_actions.driver is None or scenario_actions.driver.ok:
        return
    message = (
        f"{context_label} scenario driver failed"
        f" with exit code {scenario_actions.driver.exit_code!r}"
    )
    if strict:
        raise RuntimeError(message)
    warnings.append(message)


def _execute_managed_python_server(
    runtime_plan: RuntimePlan,
    *,
    repo_root: str,
    repograph_dir: str,
    strict: bool,
) -> RuntimeExecutionResult:
    chosen_target = RuntimeSessionTarget.from_runtime_plan(runtime_plan)
    traced_process = None
    warnings: list[str] = []
    scenario_actions = RuntimeScenarioActions()
    cleanup: RuntimeCleanupResult | None = None
    error_message: str | None = None

    try:
        traced_process = spawn_command_under_trace(
            list(runtime_plan.command),
            repo_root=repo_root,
            repograph_dir=repograph_dir,
            session_name="runtime_server",
        )
        wait_for_http_ready(
            runtime_plan.probe_url,
            timeout_seconds=float(runtime_plan.ready_timeout),
        )
        scenario_actions = _run_runtime_scenarios(runtime_plan, repo_root=repo_root)
        _handle_driver_failure(
            scenario_actions,
            strict=strict,
            warnings=warnings,
            context_label="managed runtime",
        )
    except Exception as exc:
        error_message = f"managed runtime scenario failed: {type(exc).__name__}: {exc}"
    finally:
        if traced_process is not None:
            cleanup = RuntimeCleanupResult.from_mapping(stop_command_under_trace(traced_process))

    cleanup_message = cleanup.warning_message if cleanup is not None else ""
    if cleanup_message:
        if error_message is not None:
            error_message = f"{error_message}; {cleanup_message}"
        elif strict:
            error_message = cleanup_message
        else:
            warnings.append(cleanup_message)

    if error_message is not None:
        if strict:
            raise RuntimeError(error_message)
        warnings.append(error_message)

    return RuntimeExecutionResult(
        executed=True,
        executed_mode=runtime_plan.mode,
        chosen_target=chosen_target,
        scenario_actions=scenario_actions,
        cleanup=cleanup,
        input_state=dynamic_input_state(repo_root, repograph_dir),
        warnings=tuple(warnings),
    )


def _execute_traced_tests(
    runtime_plan: RuntimePlan,
    *,
    repo_root: str,
    repograph_dir: str,
    strict: bool,
) -> RuntimeExecutionResult:
    result = run_command_under_trace(
        list(runtime_plan.command),
        repo_root=repo_root,
        repograph_dir=repograph_dir,
        session_name="pytest",
    )
    returncode = int(result.returncode)
    warnings: list[str] = []
    if returncode != 0 and not strict:
        warnings.append(f"test command exited with code {returncode}")
    return RuntimeExecutionResult(
        executed=True,
        executed_mode=runtime_plan.mode,
        chosen_target=RuntimeSessionTarget.from_runtime_plan(runtime_plan),
        cleanup=RuntimeCleanupResult(
            stopped=True,
            forced_kill=False,
            returncode=returncode,
            bootstrap_removed=True,
        ),
        pytest_exit_code=returncode,
        input_state=dynamic_input_state(repo_root, repograph_dir),
        warnings=tuple(warnings),
    )


def _build_attempt(
    runtime_plan: RuntimePlan,
    *,
    phase: Literal["primary", "fallback"],
    outcome: RuntimeAttemptOutcome,
    detail: str = "",
    input_state: DynamicInputInventory | None = None,
) -> RuntimeExecutionAttempt:
    state = input_state or DynamicInputInventory()
    return RuntimeExecutionAttempt(
        phase=phase,
        mode=runtime_plan.mode,
        resolution=runtime_plan.resolution,
        outcome=outcome,
        detail=detail,
        trace_file_count=state.trace_file_count,
        trace_record_count=state.trace_record_count,
    )


def _attach_failure_message(
    runtime_plan: RuntimePlan,
    *,
    result: RuntimeExecutionResult | None = None,
    error: BaseException | None = None,
) -> str:
    if error is not None:
        return f"{type(error).__name__}: {error}"
    if result is not None:
        if result.warnings:
            return str(result.warnings[0])
        if not result.input_state.inputs_present:
            return (
                "live attach completed but produced no dynamic inputs for the current sync window"
            )
    return f"{runtime_plan.mode} failed without a reported detail"


def _execute_single_runtime_plan(
    runtime_plan: RuntimePlan,
    *,
    repo_root: str,
    repograph_dir: str,
    strict: bool,
) -> RuntimeExecutionResult:
    if runtime_plan.mode == "attach_live_python":
        return execute_live_attach(
            runtime_plan,
            repo_root=repo_root,
            repograph_dir=repograph_dir,
            strict=strict,
        )
    if runtime_plan.mode == "managed_python_server":
        return _execute_managed_python_server(
            runtime_plan,
            repo_root=repo_root,
            repograph_dir=repograph_dir,
            strict=strict,
        )
    return _execute_traced_tests(
        runtime_plan,
        repo_root=repo_root,
        repograph_dir=repograph_dir,
        strict=strict,
    )


def execute_runtime_plan(
    runtime_plan: RuntimePlan,
    *,
    repo_root: str,
    repograph_dir: str,
    strict: bool,
    fallback_plan_resolver: Callable[[RuntimePlan], RuntimePlan | None] | None = None,
) -> RuntimeExecutionResult:
    """Execute a runtime plan and return the normalized result contract."""
    if not runtime_plan.executed:
        return RuntimeExecutionResult(
            executed=False,
            executed_mode="none",
            input_state=dynamic_input_state(repo_root, repograph_dir),
        )
    if runtime_plan.mode != "attach_live_python":
        result = _execute_single_runtime_plan(
            runtime_plan,
            repo_root=repo_root,
            repograph_dir=repograph_dir,
            strict=strict,
        )
        return RuntimeExecutionResult(
            executed=result.executed,
            executed_mode=result.executed_mode,
            chosen_target=result.chosen_target,
            scenario_actions=result.scenario_actions,
            cleanup=result.cleanup,
            pytest_exit_code=result.pytest_exit_code,
            input_state=result.input_state,
            attempts=(
                _build_attempt(
                    runtime_plan,
                    phase="primary",
                    outcome="succeeded",
                    input_state=result.input_state,
                ),
            ),
            warnings=result.warnings,
        )

    primary_result: RuntimeExecutionResult | None = None
    primary_error: BaseException | None = None
    try:
        primary_result = _execute_single_runtime_plan(
            runtime_plan,
            repo_root=repo_root,
            repograph_dir=repograph_dir,
            strict=strict,
        )
    except Exception as exc:
        primary_error = exc

    attach_failed = primary_error is not None or not bool(
        primary_result and primary_result.input_state.inputs_present
    )
    if not attach_failed and primary_result is not None:
        return RuntimeExecutionResult(
            executed=primary_result.executed,
            executed_mode=primary_result.executed_mode,
            chosen_target=primary_result.chosen_target,
            scenario_actions=primary_result.scenario_actions,
            cleanup=primary_result.cleanup,
            pytest_exit_code=primary_result.pytest_exit_code,
            input_state=primary_result.input_state,
            attempts=(
                _build_attempt(
                    runtime_plan,
                    phase="primary",
                    outcome="succeeded",
                    input_state=primary_result.input_state,
                ),
            ),
            warnings=primary_result.warnings,
        )

    failure_detail = _attach_failure_message(
        runtime_plan,
        result=primary_result,
        error=primary_error,
    )
    primary_attempt = _build_attempt(
        runtime_plan,
        phase="primary",
        outcome="failed",
        detail=failure_detail,
        input_state=primary_result.input_state if primary_result is not None else None,
    )
    fallback_plan = (
        fallback_plan_resolver(runtime_plan) if fallback_plan_resolver is not None else None
    )
    if fallback_plan is None or not fallback_plan.executed:
        if strict and primary_error is not None:
            raise RuntimeError(f"live attach failed: {failure_detail}") from primary_error
        return RuntimeExecutionResult(
            executed=bool(primary_result and primary_result.executed),
            executed_mode="none",
            chosen_target=(
                primary_result.chosen_target
                if primary_result is not None
                else RuntimeSessionTarget.from_runtime_plan(runtime_plan)
            ),
            scenario_actions=(
                primary_result.scenario_actions
                if primary_result is not None
                else RuntimeScenarioActions()
            ),
            cleanup=primary_result.cleanup if primary_result is not None else None,
            pytest_exit_code=(
                primary_result.pytest_exit_code if primary_result is not None else None
            ),
            input_state=dynamic_input_state(repo_root, repograph_dir),
            attempts=(primary_attempt,),
            warnings=(failure_detail,),
        )

    fallback_error: BaseException | None = None
    fallback_result: RuntimeExecutionResult | None = None
    try:
        fallback_result = _execute_single_runtime_plan(
            fallback_plan,
            repo_root=repo_root,
            repograph_dir=repograph_dir,
            strict=strict,
        )
    except Exception as exc:
        fallback_error = exc

    if fallback_error is None and fallback_result is not None and fallback_result.input_state.inputs_present:
        return RuntimeExecutionResult(
            executed=fallback_result.executed,
            executed_mode=fallback_result.executed_mode,
            chosen_target=fallback_result.chosen_target,
            scenario_actions=fallback_result.scenario_actions,
            cleanup=fallback_result.cleanup,
            pytest_exit_code=fallback_result.pytest_exit_code,
            input_state=fallback_result.input_state,
            attempts=(
                primary_attempt,
                _build_attempt(
                    fallback_plan,
                    phase="fallback",
                    outcome="succeeded",
                    input_state=fallback_result.input_state,
                ),
            ),
            fallback=RuntimeFallbackExecution(
                from_mode=runtime_plan.mode,
                from_resolution=runtime_plan.resolution,
                to_mode=fallback_plan.mode,
                to_resolution=fallback_plan.resolution,
                reason=failure_detail,
                succeeded=True,
            ),
            warnings=fallback_result.warnings,
        )

    fallback_detail = _attach_failure_message(
        fallback_plan,
        result=fallback_result,
        error=fallback_error,
    )
    fallback_attempt = _build_attempt(
        fallback_plan,
        phase="fallback",
        outcome="failed",
        detail=fallback_detail,
        input_state=fallback_result.input_state if fallback_result is not None else None,
    )
    if strict:
        message = (
            "live attach failed and fallback execution did not recover: "
            f"{failure_detail}; fallback {fallback_plan.mode} failed: {fallback_detail}"
        )
        if fallback_error is not None:
            raise RuntimeError(message) from fallback_error
        if primary_error is not None:
            raise RuntimeError(message) from primary_error
        raise RuntimeError(message)

    warnings: list[str] = [failure_detail, fallback_detail]
    if fallback_result is not None:
        warnings.extend(fallback_result.warnings)
    final_result = fallback_result if fallback_result is not None else primary_result
    return RuntimeExecutionResult(
        executed=bool(final_result is not None and final_result.executed),
        executed_mode="none",
        chosen_target=(
            fallback_result.chosen_target
            if fallback_result is not None
            else primary_result.chosen_target
            if primary_result is not None
            else RuntimeSessionTarget.from_runtime_plan(runtime_plan)
        ),
        scenario_actions=(
            fallback_result.scenario_actions
            if fallback_result is not None
            else primary_result.scenario_actions
            if primary_result is not None
            else RuntimeScenarioActions()
        ),
        cleanup=(
            fallback_result.cleanup
            if fallback_result is not None
            else primary_result.cleanup
            if primary_result is not None
            else None
        ),
        pytest_exit_code=(
            fallback_result.pytest_exit_code
            if fallback_result is not None
            else primary_result.pytest_exit_code
            if primary_result is not None
            else None
        ),
        input_state=dynamic_input_state(repo_root, repograph_dir),
        attempts=(primary_attempt, fallback_attempt),
        fallback=RuntimeFallbackExecution(
            from_mode=runtime_plan.mode,
            from_resolution=runtime_plan.resolution,
            to_mode=fallback_plan.mode,
            to_resolution=fallback_plan.resolution,
            reason=failure_detail,
            succeeded=False,
        ),
        warnings=tuple(warnings),
    )
