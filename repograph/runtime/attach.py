"""Attach strategies for supported live-runtime flows.

The attach layer is intentionally registry-based. RepoGraph currently ships one
real strategy: reuse a repo-scoped Python process that is already publishing a
RepoGraph live-session marker. Future server types can register another
strategy without reopening runtime selection or execution logic.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

from repograph.runtime.live_session import ActiveTraceSession, read_live_trace_session
from repograph.runtime.scenario import (
    drive_http_scenarios,
    run_scenario_driver,
    wait_for_http_ready,
)
from repograph.runtime.session import (
    LiveTarget,
    RuntimeAttachDecision,
    RuntimeExecutionResult,
    RuntimeScenarioActions,
    RuntimeSessionTarget,
)
from repograph.runtime.trace_format import trace_dir

if TYPE_CHECKING:
    from repograph.runtime.session import RuntimeMode, RuntimePlan

__all__ = [
    "count_trace_records",
    "default_probe_url",
    "execute_live_attach",
    "extract_trace_delta",
    "find_attach_strategy_for_target",
    "get_attach_strategy",
    "iter_attach_strategies",
    "register_attach_strategy",
]


@dataclass(frozen=True)
class RuntimeAttachStrategy:
    """Attach capability and executor for one supported runtime target class."""

    strategy_id: str
    runtime: Literal["python", "node"]
    mode: "RuntimeMode"
    evaluate: Callable[[LiveTarget, str, Any], RuntimeAttachDecision]
    execute: Callable[["RuntimePlan", str, str, bool], RuntimeExecutionResult]


_ATTACH_STRATEGIES: dict[str, RuntimeAttachStrategy] = {}


def default_probe_url(target: LiveTarget, configured_probe_url: str = "") -> str:
    """Return the attach probe URL for a live target, if one can be derived safely."""
    explicit = configured_probe_url.strip()
    if explicit:
        return explicit
    if target.port:
        return f"http://127.0.0.1:{target.port}/"
    return ""


def register_attach_strategy(strategy: RuntimeAttachStrategy) -> None:
    """Register one attach strategy by stable id."""
    _ATTACH_STRATEGIES[strategy.strategy_id] = strategy


def iter_attach_strategies() -> tuple[RuntimeAttachStrategy, ...]:
    """Return the currently registered attach strategies."""
    return tuple(_ATTACH_STRATEGIES.values())


def find_attach_strategy_for_target(target: LiveTarget) -> RuntimeAttachStrategy | None:
    """Return the first registered strategy for the target runtime."""
    for strategy in _ATTACH_STRATEGIES.values():
        if strategy.runtime == target.runtime:
            return strategy
    return None


def get_attach_strategy(strategy_id: str) -> RuntimeAttachStrategy | None:
    """Resolve one attach strategy by id."""
    return _ATTACH_STRATEGIES.get(strategy_id)


def count_trace_records(trace_path: str | Path) -> int:
    """Count readable JSONL records in one trace file."""
    path = Path(trace_path)
    if not path.is_file():
        return 0
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def extract_trace_delta(
    session: ActiveTraceSession,
    *,
    start_record_count: int,
    repograph_dir: str | Path,
    session_name: str = "attach_live_python",
) -> tuple[Path | None, int]:
    """Write only the new records from a live-session trace into the sync input dir."""
    source_path = Path(session.trace_path)
    if not source_path.is_file():
        return None, 0

    output_dir = trace_dir(repograph_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{session_name}_{session.pid}_{int(time.time())}.jsonl"

    new_record_count = 0
    try:
        with source_path.open(encoding="utf-8", errors="replace") as source, output_path.open(
            "w",
            encoding="utf-8",
        ) as sink:
            for index, line in enumerate(source):
                if index < start_record_count:
                    continue
                if not line:
                    continue
                sink.write(line)
                new_record_count += 1
    except OSError:
        return None, 0

    if new_record_count == 0:
        try:
            output_path.unlink()
        except OSError:
            pass
        return None, 0
    return output_path, new_record_count


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


def _run_attach_scenarios(runtime_plan: "RuntimePlan", *, repo_root: str) -> RuntimeScenarioActions:
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


def _evaluate_live_python_trace_strategy(
    target: LiveTarget,
    repograph_dir: str,
    settings: Any,
) -> RuntimeAttachDecision:
    probe_url = default_probe_url(
        target,
        str(getattr(settings, "sync_runtime_probe_url", "") or ""),
    )
    if not probe_url:
        return RuntimeAttachDecision(
            outcome="unavailable",
            reason="live_python_target_missing_probe_url",
            attach_mode="attach_live_python",
            candidate_count=1,
            target=target,
            strategy_id="python.live_trace_session",
        )
    session = read_live_trace_session(repograph_dir, target.pid)
    if session is None:
        return RuntimeAttachDecision(
            outcome="unavailable",
            reason="live_python_target_not_trace_capable",
            attach_mode="attach_live_python",
            candidate_count=1,
            target=target,
            strategy_id="python.live_trace_session",
        )
    return RuntimeAttachDecision(
        outcome="selected",
        reason="live_python_trace_session_detected",
        attach_mode="attach_live_python",
        candidate_count=1,
        target=target,
        strategy_id="python.live_trace_session",
    )


def _execute_live_python_attach(
    runtime_plan: "RuntimePlan",
    repo_root: str,
    repograph_dir: str,
    strict: bool,
) -> RuntimeExecutionResult:
    target = runtime_plan.attach_decision.target
    if target is None:
        raise RuntimeError("attach-live-python execution requires a selected live target")

    live_session = read_live_trace_session(repograph_dir, target.pid)
    if live_session is None:
        message = (
            "selected live Python target no longer has an active RepoGraph live trace session"
        )
        if strict:
            raise RuntimeError(message)
        return RuntimeExecutionResult(
            executed=True,
            chosen_target=RuntimeSessionTarget.from_runtime_plan(runtime_plan),
            warnings=(message,),
        )

    baseline_records = count_trace_records(live_session.trace_path)
    warnings: list[str] = []
    wait_for_http_ready(
        runtime_plan.probe_url,
        timeout_seconds=float(runtime_plan.ready_timeout),
    )
    scenario_actions = _run_attach_scenarios(runtime_plan, repo_root=repo_root)
    _handle_driver_failure(
        scenario_actions,
        strict=strict,
        warnings=warnings,
        context_label="live attach",
    )
    _delta_path, new_record_count = extract_trace_delta(
        live_session,
        start_record_count=baseline_records,
        repograph_dir=repograph_dir,
    )
    if new_record_count <= 0:
        message = (
            "live attach produced no new trace records; the server may not have executed "
            "application code during the attach window"
        )
        if strict:
            raise RuntimeError(message)
        warnings.append(message)

    from repograph.runtime.orchestration import dynamic_input_state

    return RuntimeExecutionResult(
        executed=True,
        chosen_target=RuntimeSessionTarget.from_runtime_plan(runtime_plan),
        scenario_actions=scenario_actions,
        input_state=dynamic_input_state(repo_root, repograph_dir),
        warnings=tuple(warnings),
    )


def execute_live_attach(
    runtime_plan: "RuntimePlan",
    *,
    repo_root: str,
    repograph_dir: str,
    strict: bool,
) -> RuntimeExecutionResult:
    """Execute one attach runtime plan via its registered strategy."""
    strategy = get_attach_strategy(runtime_plan.attach_decision.strategy_id)
    if strategy is None:
        raise RuntimeError(
            "no attach strategy is registered for "
            f"{runtime_plan.attach_decision.strategy_id or runtime_plan.mode!r}"
        )
    return strategy.execute(runtime_plan, repo_root, repograph_dir, strict)


register_attach_strategy(
    RuntimeAttachStrategy(
        strategy_id="python.live_trace_session",
        runtime="python",
        mode="attach_live_python",
        evaluate=_evaluate_live_python_trace_strategy,
        execute=_execute_live_python_attach,
    )
)
