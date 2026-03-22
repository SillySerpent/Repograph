"""Normalized runtime session contracts for dynamic-analysis orchestration.

This module defines the typed plan and execution-result shapes shared across
runtime plan resolution, runtime execution, health metadata, and operator
facing output. RepoGraph now supports traced tests, managed Python servers,
and a narrow live-attach mode for repo-scoped Python processes that are
already publishing a RepoGraph live-session marker. The session contract keeps
those modes normalized without falling back to loosely-typed payload
dictionaries again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

RuntimeAttachPolicy = Literal["prompt", "always", "never"]

AttachOutcome = Literal[
    "not_applicable",
    "unsupported",
    "unavailable",
    "ambiguous",
    "selected",
    "failed",
]

RuntimeMode = Literal[
    "attach_live_python",
    "attach_live_node",
    "managed_python_server",
    "managed_node_server",
    "managed_browser_scenario",
    "traced_tests",
    "none",
]

AttachApprovalOutcome = Literal[
    "not_applicable",
    "approved",
    "declined",
]

RuntimeAttemptOutcome = Literal[
    "succeeded",
    "failed",
    "skipped",
]

__all__ = [
    "AttachApprovalOutcome",
    "AttachOutcome",
    "DynamicInputInventory",
    "LiveTarget",
    "RuntimeAttachApproval",
    "RuntimeAttachDecision",
    "RuntimeAttachPolicy",
    "RuntimeCleanupResult",
    "RuntimeExecutionAttempt",
    "RuntimeExecutionResult",
    "RuntimeFallbackExecution",
    "RuntimeHttpObservation",
    "RuntimeMode",
    "RuntimePlan",
    "RuntimeScenarioActions",
    "RuntimeScenarioDriverResult",
    "RuntimeSessionTarget",
]


@dataclass(frozen=True)
class LiveTarget:
    """A detected live runtime target associated with the repo."""

    pid: int
    runtime: Literal["python", "node"]
    kind: str
    command: str
    association: str
    port: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "pid": self.pid,
            "runtime": self.runtime,
            "kind": self.kind,
            "command": self.command,
            "association": self.association,
            "port": self.port,
        }


@dataclass(frozen=True)
class DynamicInputInventory:
    """Inventory of dynamic-analysis input artifacts available to a sync."""

    trace_file_count: int = 0
    trace_record_count: int = 0
    coverage_json_present: bool = False
    inputs_present: bool = False

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any] | None,
    ) -> DynamicInputInventory:
        if not data:
            return cls()
        trace_file_count = int(data.get("trace_file_count") or 0)
        coverage_json_present = bool(data.get("coverage_json_present"))
        raw_inputs_present = data.get("inputs_present")
        return cls(
            trace_file_count=trace_file_count,
            trace_record_count=int(data.get("trace_record_count") or 0),
            coverage_json_present=coverage_json_present,
            inputs_present=(
                bool(raw_inputs_present)
                if raw_inputs_present is not None
                else bool(trace_file_count > 0 or coverage_json_present)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_file_count": self.trace_file_count,
            "trace_record_count": self.trace_record_count,
            "coverage_json_present": self.coverage_json_present,
            "inputs_present": self.inputs_present,
        }


@dataclass(frozen=True)
class RuntimeAttachApproval:
    """Operator or policy approval state for an otherwise-attachable target."""

    outcome: AttachApprovalOutcome = "not_applicable"
    reason: str = ""

    @property
    def approved(self) -> bool:
        return self.outcome == "approved"

    @property
    def declined(self) -> bool:
        return self.outcome == "declined"

    def to_dict(self) -> dict[str, Any]:
        if self.outcome == "not_applicable":
            return {}
        payload = {"outcome": self.outcome}
        if self.reason:
            payload["reason"] = self.reason
        return payload


@dataclass(frozen=True)
class RuntimeAttachDecision:
    """Decision metadata for the live-attach branch of runtime selection.

    RepoGraph does not yet execute live-process attachment, but the selection
    layer still needs an explicit contract for whether a safe attach candidate
    existed, whether attach was ambiguous, and why execution fell back to a
    managed runtime or traced tests.
    """

    outcome: AttachOutcome = "not_applicable"
    reason: str = ""
    attach_mode: RuntimeMode = "none"
    candidate_count: int = 0
    target: LiveTarget | None = None
    strategy_id: str = ""
    policy: RuntimeAttachPolicy = "prompt"
    approval: RuntimeAttachApproval = field(default_factory=RuntimeAttachApproval)

    @property
    def present(self) -> bool:
        return self.outcome != "not_applicable"

    @property
    def approved_for_execution(self) -> bool:
        return self.outcome == "selected" and self.approval.approved

    def to_dict(self) -> dict[str, Any]:
        if not self.present:
            return {}
        payload: dict[str, Any] = {
            "outcome": self.outcome,
            "reason": self.reason,
            "attach_mode": self.attach_mode,
            "candidate_count": self.candidate_count,
            "policy": self.policy,
        }
        if self.strategy_id:
            payload["strategy_id"] = self.strategy_id
        if self.target is not None:
            payload["target"] = self.target.to_dict()
        approval = self.approval.to_dict()
        if approval:
            payload["approval"] = approval
        return payload


@dataclass(frozen=True)
class RuntimePlan:
    """Resolved runtime strategy for a full-power sync."""

    mode: RuntimeMode
    resolution: str
    command: tuple[str, ...]
    skip_reason: str = ""
    fallback_reason: str = ""
    detected_targets: tuple[LiveTarget, ...] = ()
    attach_decision: RuntimeAttachDecision = field(default_factory=RuntimeAttachDecision)
    probe_url: str = ""
    scenario_urls: tuple[str, ...] = ()
    scenario_driver_command: tuple[str, ...] = ()
    ready_timeout: int = 15

    @property
    def executed(self) -> bool:
        if self.mode in {"attach_live_python", "attach_live_node"}:
            return self.attach_decision.approved_for_execution
        return bool(self.command)


@dataclass(frozen=True)
class RuntimeSessionTarget:
    """Normalized description of the runtime target or command that was used."""

    source: Literal["managed_runtime", "test_command", "live_target", "none"] = "none"
    mode: RuntimeMode = "none"
    runtime: str = ""
    kind: str = ""
    command: tuple[str, ...] = ()
    association: str = ""
    pid: int | None = None
    port: int | None = None
    probe_url: str = ""
    scenario_urls: tuple[str, ...] = ()
    scenario_driver_command: tuple[str, ...] = ()
    ready_timeout: int | None = None

    @classmethod
    def from_runtime_plan(cls, runtime_plan: RuntimePlan) -> RuntimeSessionTarget:
        if (
            runtime_plan.mode in {"attach_live_python", "attach_live_node"}
            and runtime_plan.attach_decision.target is not None
        ):
            return cls.from_live_target(
                runtime_plan.attach_decision.target,
                mode=runtime_plan.mode,
                probe_url=runtime_plan.probe_url,
                scenario_urls=runtime_plan.scenario_urls,
                scenario_driver_command=runtime_plan.scenario_driver_command,
                ready_timeout=runtime_plan.ready_timeout,
            )
        if runtime_plan.mode == "managed_python_server":
            return cls(
                source="managed_runtime",
                mode=runtime_plan.mode,
                runtime="python",
                kind="managed_runtime_server",
                command=runtime_plan.command,
                probe_url=runtime_plan.probe_url,
                scenario_urls=runtime_plan.scenario_urls,
                scenario_driver_command=runtime_plan.scenario_driver_command,
                ready_timeout=runtime_plan.ready_timeout,
            )
        if runtime_plan.mode == "traced_tests":
            return cls(
                source="test_command",
                mode=runtime_plan.mode,
                runtime="python",
                kind="pytest",
                command=runtime_plan.command,
            )
        return cls(mode=runtime_plan.mode)

    @classmethod
    def from_live_target(
        cls,
        target: LiveTarget,
        *,
        mode: RuntimeMode,
        probe_url: str = "",
        scenario_urls: tuple[str, ...] = (),
        scenario_driver_command: tuple[str, ...] = (),
        ready_timeout: int | None = None,
    ) -> RuntimeSessionTarget:
        return cls(
            source="live_target",
            mode=mode,
            runtime=target.runtime,
            kind=target.kind,
            command=(target.command,),
            association=target.association,
            pid=target.pid,
            port=target.port,
            probe_url=probe_url,
            scenario_urls=scenario_urls,
            scenario_driver_command=scenario_driver_command,
            ready_timeout=ready_timeout,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "source": self.source,
            "mode": self.mode,
            "runtime": self.runtime,
            "kind": self.kind,
            "command": list(self.command),
            "association": self.association,
            "pid": self.pid,
            "port": self.port,
            "probe_url": self.probe_url,
            "scenario_urls": list(self.scenario_urls),
            "ready_timeout": self.ready_timeout,
        }
        if self.scenario_driver_command:
            payload["scenario_driver_command"] = list(self.scenario_driver_command)
        return payload


@dataclass(frozen=True)
class RuntimeHttpObservation:
    """One HTTP observation recorded during managed runtime scenario driving."""

    url: str
    ok: bool
    status_code: int | None = None
    error: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> RuntimeHttpObservation:
        return cls(
            url=str(data.get("url") or ""),
            ok=bool(data.get("ok")),
            status_code=(
                int(data["status_code"])
                if data.get("status_code") not in (None, "")
                else None
            ),
            error=str(data.get("error") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "url": self.url,
            "ok": self.ok,
            "status_code": self.status_code,
        }
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass(frozen=True)
class RuntimeScenarioDriverResult:
    """Outcome of a repo-provided scenario driver command."""

    command: tuple[str, ...] = ()
    ok: bool = False
    exit_code: int | None = None
    timeout_seconds: float | None = None
    stdout_preview: str = ""
    stderr_preview: str = ""
    error: str = ""
    python_driver: bool = False

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any] | None,
    ) -> RuntimeScenarioDriverResult | None:
        if not data:
            return None
        return cls(
            command=tuple(str(part) for part in (data.get("command") or [])),
            ok=bool(data.get("ok")),
            exit_code=(
                int(data["exit_code"]) if data.get("exit_code") not in (None, "") else None
            ),
            timeout_seconds=(
                float(data["timeout_seconds"])
                if data.get("timeout_seconds") not in (None, "")
                else None
            ),
            stdout_preview=str(data.get("stdout_preview") or ""),
            stderr_preview=str(data.get("stderr_preview") or ""),
            error=str(data.get("error") or ""),
            python_driver=bool(data.get("python_driver")),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "command": list(self.command),
            "ok": self.ok,
            "exit_code": self.exit_code,
            "timeout_seconds": self.timeout_seconds,
            "stdout_preview": self.stdout_preview,
            "stderr_preview": self.stderr_preview,
        }
        if self.error:
            payload["error"] = self.error
        if self.python_driver:
            payload["python_driver"] = True
        return payload


@dataclass(frozen=True)
class RuntimeScenarioActions:
    """Normalized summary of HTTP and driver actions taken during a session."""

    kind: Literal["none", "http", "driver", "combined"] = "none"
    planned_count: int = 0
    executed_count: int = 0
    successful_count: int = 0
    failed_count: int = 0
    requests: tuple[RuntimeHttpObservation, ...] = ()
    driver: RuntimeScenarioDriverResult | None = None

    @property
    def present(self) -> bool:
        return self.kind != "none"

    @classmethod
    def from_components(
        cls,
        *,
        http_actions: Mapping[str, Any] | None,
        driver_actions: Mapping[str, Any] | None,
    ) -> RuntimeScenarioActions:
        if not http_actions and not driver_actions:
            return cls()

        http_result = dict(http_actions or {})
        driver_result = dict(driver_actions or {})
        driver = RuntimeScenarioDriverResult.from_mapping(driver_result)
        driver_executed = driver is not None
        driver_ok = bool(driver and driver.ok)
        driver_failed = driver_executed and not driver_ok

        if http_result and driver_result:
            kind: Literal["none", "http", "driver", "combined"] = "combined"
        elif driver_result:
            kind = "driver"
        else:
            kind = "http"

        return cls(
            kind=kind,
            planned_count=int(http_result.get("planned_count") or 0) + (1 if driver_executed else 0),
            executed_count=int(http_result.get("executed_count") or 0) + (1 if driver_executed else 0),
            successful_count=int(http_result.get("successful_count") or 0) + (1 if driver_ok else 0),
            failed_count=int(http_result.get("failed_count") or 0) + (1 if driver_failed else 0),
            requests=tuple(
                RuntimeHttpObservation.from_mapping(item)
                for item in (http_result.get("requests") or [])
            ),
            driver=driver,
        )

    def to_dict(self) -> dict[str, Any]:
        if not self.present:
            return {}
        payload: dict[str, Any] = {
            "kind": self.kind,
            "planned_count": self.planned_count,
            "executed_count": self.executed_count,
            "successful_count": self.successful_count,
            "failed_count": self.failed_count,
            "requests": [request.to_dict() for request in self.requests],
        }
        if self.driver is not None:
            payload["driver"] = self.driver.to_dict()
        return payload


@dataclass(frozen=True)
class RuntimeCleanupResult:
    """Normalized process/artifact cleanup summary for a runtime session."""

    pid: int | None = None
    process_group_id: int | None = None
    stopped: bool | None = None
    forced_kill: bool = False
    returncode: int | None = None
    bootstrap_removed: bool | None = None
    pid_alive_after_stop: bool | None = None
    process_group_alive_after_stop: bool | None = None
    stdout_path: str = ""
    stderr_path: str = ""

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any] | None,
    ) -> RuntimeCleanupResult | None:
        if not data:
            return None
        return cls(
            pid=int(data["pid"]) if data.get("pid") not in (None, "") else None,
            process_group_id=(
                int(data["process_group_id"])
                if data.get("process_group_id") not in (None, "")
                else None
            ),
            stopped=bool(data["stopped"]) if data.get("stopped") is not None else None,
            forced_kill=bool(data.get("forced_kill")),
            returncode=(
                int(data["returncode"])
                if data.get("returncode") not in (None, "")
                else None
            ),
            bootstrap_removed=(
                bool(data["bootstrap_removed"])
                if data.get("bootstrap_removed") is not None
                else None
            ),
            pid_alive_after_stop=(
                bool(data["pid_alive_after_stop"])
                if data.get("pid_alive_after_stop") is not None
                else None
            ),
            process_group_alive_after_stop=(
                bool(data["process_group_alive_after_stop"])
                if data.get("process_group_alive_after_stop") is not None
                else None
            ),
            stdout_path=str(data.get("stdout_path") or ""),
            stderr_path=str(data.get("stderr_path") or ""),
        )

    @property
    def present(self) -> bool:
        return any((
            self.pid is not None,
            self.process_group_id is not None,
            self.stopped is not None,
            self.returncode is not None,
            self.stdout_path,
            self.stderr_path,
        ))

    @property
    def status_label(self) -> str:
        if not self.present:
            return "not applicable"
        if self.stopped is True and self.bootstrap_removed is not False:
            return "clean"

        issues: list[str] = []
        if self.stopped is False:
            issues.append("process still running")
        if self.forced_kill:
            issues.append("force-killed")
        if self.bootstrap_removed is False:
            issues.append("bootstrap dir retained")
        if self.pid_alive_after_stop:
            issues.append("pid still alive")
        if self.process_group_alive_after_stop:
            issues.append("process group still alive")
        if not issues:
            return "partial"
        return ", ".join(issues)

    @property
    def warning_message(self) -> str:
        issues: list[str] = []
        if self.pid_alive_after_stop:
            issues.append(f"pid {self.pid} still exists after cleanup")
        if self.process_group_alive_after_stop:
            issues.append(
                f"process group {self.process_group_id} still exists after cleanup"
            )
        if self.present and self.bootstrap_removed is False:
            issues.append("trace bootstrap directory was not removed")
        if not issues:
            return ""
        return "managed runtime cleanup incomplete: " + ", ".join(issues)

    def to_dict(self) -> dict[str, Any]:
        if not self.present:
            return {}
        return {
            "pid": self.pid,
            "process_group_id": self.process_group_id,
            "stopped": self.stopped,
            "forced_kill": self.forced_kill,
            "returncode": self.returncode,
            "bootstrap_removed": self.bootstrap_removed,
            "pid_alive_after_stop": self.pid_alive_after_stop,
            "process_group_alive_after_stop": self.process_group_alive_after_stop,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
        }


@dataclass(frozen=True)
class RuntimeExecutionAttempt:
    """One concrete runtime execution attempt and its outcome."""

    phase: Literal["primary", "fallback"] = "primary"
    mode: RuntimeMode = "none"
    resolution: str = ""
    outcome: RuntimeAttemptOutcome = "skipped"
    detail: str = ""
    trace_file_count: int = 0
    trace_record_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "phase": self.phase,
            "mode": self.mode,
            "resolution": self.resolution,
            "outcome": self.outcome,
            "trace_file_count": self.trace_file_count,
            "trace_record_count": self.trace_record_count,
        }
        if self.detail:
            payload["detail"] = self.detail
        return payload


@dataclass(frozen=True)
class RuntimeFallbackExecution:
    """Summary of a second-chance runtime fallback after a primary failure."""

    from_mode: RuntimeMode
    to_mode: RuntimeMode
    reason: str
    from_resolution: str = ""
    to_resolution: str = ""
    succeeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "from_mode": self.from_mode,
            "to_mode": self.to_mode,
            "reason": self.reason,
            "succeeded": self.succeeded,
        }
        if self.from_resolution:
            payload["from_resolution"] = self.from_resolution
        if self.to_resolution:
            payload["to_resolution"] = self.to_resolution
        return payload


@dataclass(frozen=True)
class RuntimeExecutionResult:
    """Concrete execution outcome for a resolved runtime plan."""

    executed: bool
    executed_mode: RuntimeMode = "none"
    chosen_target: RuntimeSessionTarget | None = None
    scenario_actions: RuntimeScenarioActions = field(default_factory=RuntimeScenarioActions)
    cleanup: RuntimeCleanupResult | None = None
    pytest_exit_code: int | None = None
    input_state: DynamicInputInventory = field(default_factory=DynamicInputInventory)
    attempts: tuple[RuntimeExecutionAttempt, ...] = ()
    fallback: RuntimeFallbackExecution | None = None
    warnings: tuple[str, ...] = ()

    def to_analysis_update(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "executed": self.executed,
            "executed_mode": self.executed_mode,
            "chosen_target": (
                self.chosen_target.to_dict() if self.chosen_target is not None else {}
            ),
            "scenario_actions": self.scenario_actions.to_dict(),
            "cleanup": self.cleanup.to_dict() if self.cleanup is not None else {},
            "pytest_exit_code": self.pytest_exit_code,
            "execution_attempts": [attempt.to_dict() for attempt in self.attempts],
            "fallback_execution": (
                self.fallback.to_dict() if self.fallback is not None else {}
            ),
        }
        payload.update(self.input_state.to_dict())
        return payload
