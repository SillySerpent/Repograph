"""Runtime-orchestration helpers for full-power sync flows.

Selection is intentionally deterministic:
1. explicit deprecated pytest-target alias from the caller
2. attachable live target when one repo-scoped target is both unambiguous and
   already publishing the capability required by a registered attach strategy;
   attach approval policy is then applied before execution or fallback
3. managed runtime configuration
4. traced tests
5. structured skip
"""
from __future__ import annotations

from dataclasses import replace
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from repograph.settings import (
    load_settings,
    load_sync_test_command,
    repograph_dir as repograph_dir_fn,
)
from repograph.runtime.attach import (
    default_probe_url,
    find_attach_strategy_for_target,
)
from repograph.runtime.live_session import read_live_trace_session
from repograph.runtime.session import (
    AttachOutcome,
    DynamicInputInventory,
    LiveTarget,
    RuntimeAttachApproval,
    RuntimeAttachDecision,
    RuntimeAttachPolicy,
    RuntimeMode,
    RuntimePlan,
)
from repograph.runtime.trace_format import collect_trace_files

__all__ = [
    "LiveTarget",
    "RuntimeMode",
    "RuntimeAttachDecision",
    "RuntimePlan",
    "describe_attach_outcome",
    "describe_attach_policy",
    "describe_live_target",
    "describe_runtime_mode",
    "describe_runtime_reason",
    "describe_runtime_resolution",
    "describe_trace_collection",
    "detect_live_targets",
    "dynamic_input_state",
    "resolve_runtime_plan",
]


def describe_attach_outcome(outcome: AttachOutcome | str) -> str:
    """Return a short human-readable label for attach-policy status."""
    labels = {
        "not_applicable": "not applicable",
        "unsupported": "unsupported",
        "unavailable": "unavailable",
        "ambiguous": "ambiguous",
        "selected": "selected",
        "failed": "failed",
    }
    return labels.get(str(outcome), str(outcome).replace("_", " "))


def describe_attach_policy(policy: RuntimeAttachPolicy | str) -> str:
    """Return a short human-readable label for attach approval policy."""
    labels = {
        "prompt": "prompt",
        "always": "always attach",
        "never": "never attach",
    }
    return labels.get(str(policy), str(policy).replace("_", " "))


def describe_runtime_mode(mode: RuntimeMode | str) -> str:
    """Return a short human-readable label for a runtime mode."""
    labels = {
        "attach_live_python": "live Python attach",
        "attach_live_node": "live Node attach",
        "managed_python_server": "managed traced Python server",
        "managed_node_server": "managed Node server",
        "managed_browser_scenario": "managed browser scenario",
        "traced_tests": "traced tests",
        "none": "no runtime execution",
        "existing_inputs": "existing dynamic inputs",
    }
    return labels.get(str(mode), str(mode).replace("_", " "))


def describe_runtime_resolution(resolution: str) -> str:
    """Return a short explanation of why a runtime plan was selected."""
    labels = {
        "deprecated_alias": "explicit pytest targets supplied by the caller",
        "managed_runtime_config": "managed runtime settings",
        "managed_runtime_config_invalid": "managed runtime settings were present but invalid",
        "config_override": "configured sync_test_command override",
        "pyproject_tests_dir": "pyproject.toml pytest config with tests/ directory",
        "pyproject": "pyproject.toml pytest config",
        "auto_detected_tests": "auto-detected tests/ directory",
        "auto_detected_test": "auto-detected test/ directory",
        "auto_detected_spec": "auto-detected spec/ directory",
        "live_target_detected": "live runtime targets were detected",
        "live_target_attach": "attachable live runtime target with active RepoGraph trace session",
    }
    if not resolution:
        return "no runtime signal matched"
    return labels.get(resolution, resolution.replace("_", " "))


def describe_runtime_reason(reason: str) -> str:
    """Return a human-readable explanation for a skip or fallback reason."""
    labels = {
        "live_python_attach_not_implemented": (
            "direct attach to a detected live Python runtime is not implemented yet"
        ),
        "live_python_trace_session_detected": (
            "the detected live Python runtime is already publishing a RepoGraph live trace session"
        ),
        "live_python_target_not_trace_capable": (
            "the detected live Python runtime is not running with RepoGraph live tracing, "
            "so automatic attach could not safely collect evidence from it"
        ),
        "live_python_target_missing_probe_url": (
            "the detected live Python runtime has no usable HTTP probe URL; "
            "configure sync_runtime_probe_url or run it with an explicit port"
        ),
        "live_node_attach_not_implemented": (
            "direct attach to a detected live Node runtime is not implemented yet"
        ),
        "multiple_live_targets_detected": (
            "multiple live runtime targets were detected, so RepoGraph could not choose "
            "one safe automatic attach target"
        ),
        "live_attach_declined": (
            "the operator declined automatic attach to the running server"
        ),
        "live_attach_disabled_by_policy": (
            "live attach is disabled by the configured sync_runtime_attach_policy"
        ),
        "live_attach_prompt_unavailable": (
            "live attach required confirmation, but no interactive terminal was available"
        ),
        "live_attach_prompt_failed": (
            "live attach confirmation failed, so RepoGraph fell back safely"
        ),
        "live_attach_enabled_by_policy": (
            "live attach is enabled automatically by the configured sync_runtime_attach_policy"
        ),
        "operator_approved_live_attach": (
            "the operator approved attaching to the running server"
        ),
        "live_target_attach_not_supported": (
            "direct attach to a detected live runtime target is not implemented yet"
        ),
        "managed_runtime_missing_probe_url": (
            "managed runtime settings are missing sync_runtime_probe_url"
        ),
        "managed_runtime_python_only": (
            "managed runtime server commands currently support Python runtimes only"
        ),
        "no_pytest_signal": "no pytest signal or managed runtime configuration was found",
    }
    if not reason:
        return ""
    return labels.get(reason, reason.replace("_", " "))


def describe_trace_collection(mode: RuntimeMode | str) -> str:
    """Describe what trace collection means for the selected runtime mode."""
    labels = {
        "attach_live_python": (
            "reuse a RepoGraph-traced live Python process and capture only the current attach delta"
        ),
        "attach_live_node": "capture runtime evidence from an attached live Node process",
        "managed_python_server": (
            "capture Python call events while the managed server runs and scenarios execute"
        ),
        "managed_node_server": "capture runtime evidence while a managed Node server runs",
        "managed_browser_scenario": (
            "capture runtime evidence while managed browser scenarios execute"
        ),
        "traced_tests": "capture Python call events during test execution",
        "none": "no trace collection will run",
        "existing_inputs": "reuse previously collected trace or coverage inputs",
    }
    return labels.get(str(mode), "capture runtime evidence for the selected mode")


def describe_live_target(target: LiveTarget | Mapping[str, Any]) -> str:
    """Return a compact one-line description of a detected live target."""
    if isinstance(target, LiveTarget):
        runtime = target.runtime
        kind = target.kind
        pid = target.pid
        port = target.port
    else:
        runtime = str(target.get("runtime") or "unknown")
        kind = str(target.get("kind") or "target")
        pid = target.get("pid")
        port = target.get("port")

    parts = [runtime, kind.replace("_", " ")]
    if pid not in (None, "", 0):
        parts.append(f"pid={pid}")
    if port not in (None, "", 0):
        parts.append(f"port={port}")
    return " ".join(parts)


def _coverage_json_present(repo_root: str) -> bool:
    return (Path(repo_root) / "coverage.json").is_file()


def _trace_inventory(repograph_dir: str) -> dict[str, int]:
    files = collect_trace_files(repograph_dir)
    total_records = 0
    for trace_file in files:
        try:
            with trace_file.open(encoding="utf-8", errors="replace") as fh:
                total_records += sum(1 for _ in fh)
        except OSError:
            continue
    return {
        "trace_file_count": len(files),
        "trace_record_count": total_records,
    }


def dynamic_input_state(repo_root: str, repograph_dir: str) -> DynamicInputInventory:
    """Return the currently available runtime/coverage inputs."""
    inventory = _trace_inventory(repograph_dir)
    coverage_json_present = _coverage_json_present(repo_root)
    return DynamicInputInventory(
        trace_file_count=int(inventory["trace_file_count"]),
        trace_record_count=int(inventory["trace_record_count"]),
        coverage_json_present=coverage_json_present,
        inputs_present=bool(inventory["trace_file_count"] > 0 or coverage_json_present),
    )


def _list_process_rows() -> list[tuple[int, str]]:
    result = subprocess.run(
        ["ps", "-ax", "-o", "pid=", "-o", "command="],
        capture_output=True,
        text=True,
        check=True,
    )
    rows: list[tuple[int, str]] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            pid_text, command = line.split(maxsplit=1)
        except ValueError:
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        rows.append((pid, command.strip()))
    return rows


def _extract_port(command: str) -> int | None:
    patterns = (
        r"--port(?:=|\s+)(\d{2,5})",
        r"-p\s+(\d{2,5})",
        r"PORT=(\d{2,5})",
    )
    for pattern in patterns:
        match = re.search(pattern, command)
        if match:
            return int(match.group(1))
    return None


def _command_references_repo(command: str, repo_root: str) -> bool:
    return repo_root in command.replace("\\", "/")


def _is_internal_repograph_runtime_artifact(command: str, repo_root: str) -> bool:
    """Return ``True`` for RepoGraph-owned internal runtime helper commands.

    Live-target detection should only consider user/runtime entry processes that
    represent real attach candidates. Internal helper launchers under
    ``.repograph/`` are generated artifacts used by managed-runtime workflows
    and should never compete with a genuine live server during attach
    selection.
    """
    normalized = command.replace("\\", "/")
    return f"{repo_root}/.repograph/" in normalized


def _classify_live_target(command: str, repo_root: str) -> LiveTarget | None:
    normalized = command.replace("\\", "/")
    if not _command_references_repo(normalized, repo_root):
        return None
    if _is_internal_repograph_runtime_artifact(normalized, repo_root):
        return None

    lowered = normalized.lower()
    runtime: Literal["python", "node"] | None = None
    kind: str | None = None

    if "uvicorn" in lowered:
        runtime, kind = "python", "uvicorn"
    elif "gunicorn" in lowered:
        runtime, kind = "python", "gunicorn"
    elif "flask run" in lowered or ("-m flask" in lowered and " run" in lowered):
        runtime, kind = "python", "flask"
    elif "manage.py" in lowered and "runserver" in lowered:
        runtime, kind = "python", "django"
    elif "-m http.server" in lowered:
        runtime, kind = "python", "http_server"
    elif re.search(r"/(?:app|server|main|run)\.py\b", lowered):
        runtime, kind = "python", "python_server_script"
    elif "next dev" in lowered or "next start" in lowered:
        runtime, kind = "node", "next"
    elif re.search(r"\bvite\b", lowered):
        runtime, kind = "node", "vite"
    elif "npm run dev" in lowered or "npm run start" in lowered:
        runtime, kind = "node", "npm_script"
    elif re.search(r"/(?:server|app|main)\.(?:js|ts)\b", lowered):
        runtime, kind = "node", "node_server_script"

    if runtime is None or kind is None:
        return None

    return LiveTarget(
        pid=0,
        runtime=runtime,
        kind=kind,
        command=command,
        association="command_path",
        port=_extract_port(command),
    )


def detect_live_targets(
    repo_root: str,
    *,
    process_rows: list[tuple[int, str]] | None = None,
) -> tuple[LiveTarget, ...]:
    """Detect live runtime processes that are confidently associated with the repo.

    Detection is intentionally high-precision and low-recall: a command must
    clearly reference the repo path before it is considered a target. This
    avoids accidental attachment to unrelated local processes while the richer
    attach workflow is still under development.
    """
    resolved_root = str(Path(repo_root).resolve()).replace("\\", "/")
    rows = process_rows if process_rows is not None else _list_process_rows()
    targets: list[LiveTarget] = []
    for pid, command in rows:
        target = _classify_live_target(command, resolved_root)
        if target is None:
            continue
        targets.append(
            LiveTarget(
                pid=pid,
                runtime=target.runtime,
                kind=target.kind,
                command=target.command,
                association=target.association,
                port=target.port,
            )
        )
    targets.sort(key=lambda item: (item.runtime, item.kind, item.pid))
    return tuple(targets)


def _repo_has_pytest_signal(repo_root: str) -> bool:
    pyproject = Path(repo_root) / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
    except Exception:
        return False
    tool = data.get("tool")
    if not isinstance(tool, dict):
        return False
    pytest_cfg = tool.get("pytest")
    return isinstance(pytest_cfg, dict) and "ini_options" in pytest_cfg


def _repo_has_tests_dir(repo_root: str) -> str | None:
    for candidate in ("tests", "test", "spec"):
        tdir = Path(repo_root) / candidate
        if tdir.is_dir() and any(tdir.rglob("*.py")):
            return candidate
    return None


def _command_looks_like_python(command: tuple[str, ...]) -> bool:
    if not command:
        return False
    head = Path(command[0]).name.lower()
    if head.startswith("python") or head in {"uv", "poetry"}:
        return True
    return any(part.endswith(".py") for part in command)


def _resolve_managed_runtime_config(
    settings: Any,
) -> tuple[tuple[str, ...], str, tuple[str, ...], tuple[str, ...], int, str]:
    command = tuple(settings.sync_runtime_server_command or [])
    probe_url = str(settings.sync_runtime_probe_url or "").strip()
    scenario_urls = tuple(settings.sync_runtime_scenario_urls or [])
    scenario_driver_command = tuple(settings.sync_runtime_scenario_driver_command or [])
    ready_timeout = int(settings.sync_runtime_ready_timeout or 15)

    if not command:
        return (), "", (), (), ready_timeout, ""
    if not probe_url:
        return (), "", (), (), ready_timeout, "managed_runtime_missing_probe_url"
    if not _command_looks_like_python(command):
        return (), "", (), (), ready_timeout, "managed_runtime_python_only"

    planned_scenarios = scenario_urls or (probe_url,)
    return command, probe_url, planned_scenarios, scenario_driver_command, ready_timeout, ""


def _target_command_identity(command: str) -> str:
    """Return a stable identity string for one detected live-target command.

    Repo-scoped live servers sometimes appear as more than one OS process for
    the same logical command target. When that happens, attach planning should
    distinguish "one logical server with duplicate helper/child processes" from
    "multiple genuinely different live servers".
    """
    normalized = command.replace("\\", "/").strip()
    try:
        tokens = shlex.split(normalized)
    except ValueError:
        tokens = normalized.split()
    for token in tokens:
        if token.endswith((".py", ".js", ".ts", ".tsx", ".jsx")):
            return token
    return normalized


def _selected_attach_identity(decision: RuntimeAttachDecision) -> tuple[str, str, str, str, int]:
    """Return the logical identity used to collapse equivalent attach targets."""
    target = decision.target
    if target is None:
        return (
            decision.strategy_id,
            decision.attach_mode,
            "",
            "",
            -1,
        )
    return (
        decision.strategy_id,
        decision.attach_mode,
        target.runtime,
        _target_command_identity(target.command),
        target.port if target.port is not None else -1,
    )


def _selected_attach_rank(
    decision: RuntimeAttachDecision,
    *,
    repograph_dir: str,
) -> tuple[int, float, int]:
    """Return a deterministic ordering for equivalent attach candidates."""
    target = decision.target
    if target is None:
        return (0, 0.0, 0)
    session = read_live_trace_session(repograph_dir, target.pid)
    return (
        1 if target.port is not None else 0,
        float(session.started_at) if session is not None else 0.0,
        int(target.pid),
    )


def _coalesce_equivalent_selected_attach_decisions(
    selected: list[RuntimeAttachDecision],
    *,
    repograph_dir: str,
) -> RuntimeAttachDecision | None:
    """Collapse duplicate selected processes that represent one logical target.

    This intentionally handles only the narrow case where every selected target
    resolves to the same logical command identity. Distinct live servers remain
    ambiguous on purpose.
    """
    if not selected:
        return None
    groups: dict[tuple[str, str, str, str, int], list[RuntimeAttachDecision]] = {}
    for decision in selected:
        groups.setdefault(_selected_attach_identity(decision), []).append(decision)
    if len(groups) != 1:
        return None
    candidates = next(iter(groups.values()))
    chosen = max(
        candidates,
        key=lambda decision: _selected_attach_rank(decision, repograph_dir=repograph_dir),
    )
    return replace(chosen, candidate_count=len(candidates))


def _resolve_attach_decision(
    detected_targets: tuple[LiveTarget, ...],
    *,
    repograph_dir: str,
    settings: Any,
    attach_policy: RuntimeAttachPolicy,
) -> RuntimeAttachDecision:
    if not detected_targets:
        return RuntimeAttachDecision(policy=attach_policy)

    evaluated: list[RuntimeAttachDecision] = []
    for target in detected_targets:
        strategy = find_attach_strategy_for_target(target)
        attach_mode: RuntimeMode = (
            "attach_live_python" if target.runtime == "python" else "attach_live_node"
        )
        if strategy is None:
            evaluated.append(
                RuntimeAttachDecision(
                    outcome="unsupported",
                    reason=(
                        "live_node_attach_not_implemented"
                        if target.runtime == "node"
                        else "live_target_attach_not_supported"
                    ),
                    attach_mode=attach_mode,
                    candidate_count=1,
                    target=target,
                    policy=attach_policy,
                )
            )
            continue
        decision = strategy.evaluate(target, repograph_dir, settings)
        evaluated.append(
            replace(
                decision,
                candidate_count=decision.candidate_count or 1,
                target=decision.target or target,
                policy=attach_policy,
            )
        )

    selected = [decision for decision in evaluated if decision.outcome == "selected"]
    if len(selected) == 1:
        return selected[0]
    if len(selected) > 1:
        equivalent = _coalesce_equivalent_selected_attach_decisions(
            selected,
            repograph_dir=repograph_dir,
        )
        if equivalent is not None:
            return equivalent
        return RuntimeAttachDecision(
            outcome="ambiguous",
            reason="multiple_live_targets_detected",
            candidate_count=len(selected),
            policy=attach_policy,
        )

    if len(detected_targets) > 1:
        return RuntimeAttachDecision(
            outcome="ambiguous",
            reason="multiple_live_targets_detected",
            candidate_count=len(detected_targets),
            policy=attach_policy,
        )

    return evaluated[0]


def _apply_attach_policy(
    attach_decision: RuntimeAttachDecision,
    *,
    attach_policy: RuntimeAttachPolicy,
    approval_resolver: Callable[[RuntimeAttachDecision], RuntimeAttachApproval] | None,
) -> RuntimeAttachDecision:
    if not attach_decision.present or attach_decision.outcome != "selected":
        return replace(attach_decision, policy=attach_policy)

    if attach_policy == "always":
        approval = RuntimeAttachApproval(
            outcome="approved",
            reason="live_attach_enabled_by_policy",
        )
        return replace(attach_decision, policy=attach_policy, approval=approval)

    if attach_policy == "never":
        approval = RuntimeAttachApproval(
            outcome="declined",
            reason="live_attach_disabled_by_policy",
        )
        return replace(attach_decision, policy=attach_policy, approval=approval)

    if approval_resolver is None:
        approval = RuntimeAttachApproval(
            outcome="declined",
            reason="live_attach_prompt_unavailable",
        )
        return replace(attach_decision, policy=attach_policy, approval=approval)

    try:
        approval = approval_resolver(attach_decision)
    except Exception:
        approval = RuntimeAttachApproval(
            outcome="declined",
            reason="live_attach_prompt_failed",
        )
    if approval.outcome == "not_applicable":
        approval = RuntimeAttachApproval(
            outcome="declined",
            reason="live_attach_prompt_failed",
        )
    return replace(attach_decision, policy=attach_policy, approval=approval)


def _approved_attach_plan(
    attach_decision: RuntimeAttachDecision,
    *,
    detected_targets: tuple[LiveTarget, ...],
    settings: Any,
) -> RuntimePlan:
    target = attach_decision.target
    if target is None:
        raise RuntimeError("approved attach execution requires a selected target")
    attach_probe_url = default_probe_url(
        target,
        str(settings.sync_runtime_probe_url or ""),
    )
    attach_scenarios = tuple(settings.sync_runtime_scenario_urls or ()) or ((attach_probe_url,) if attach_probe_url else ())
    return RuntimePlan(
        mode=attach_decision.attach_mode,
        resolution="live_target_attach",
        command=(),
        detected_targets=detected_targets,
        attach_decision=attach_decision,
        probe_url=attach_probe_url,
        scenario_urls=attach_scenarios,
        scenario_driver_command=tuple(settings.sync_runtime_scenario_driver_command or ()),
        ready_timeout=int(settings.sync_runtime_ready_timeout or 15),
    )


def resolve_runtime_plan(
    repo_root: str,
    *,
    repograph_dir: str | None = None,
    pytest_targets: list[str] | None = None,
    process_rows: list[tuple[int, str]] | None = None,
    attach_policy: RuntimeAttachPolicy | None = None,
    attach_approval_resolver: Callable[[RuntimeAttachDecision], RuntimeAttachApproval] | None = None,
) -> RuntimePlan:
    """Resolve the runtime execution strategy for a full-power sync.

    The plan object makes the runtime decision explicit so attach, managed
    runtime, traced tests, and no-op cases all propagate through one contract
    instead of re-growing ad hoc branches in the runner.
    """
    resolved_repograph_dir = repograph_dir or str(repograph_dir_fn(repo_root))
    settings = load_settings(repo_root)
    resolved_attach_policy: RuntimeAttachPolicy = attach_policy or getattr(
        settings,
        "sync_runtime_attach_policy",
        "prompt",
    )
    detected_targets = detect_live_targets(repo_root, process_rows=process_rows)
    attach_decision = _resolve_attach_decision(
        detected_targets,
        repograph_dir=resolved_repograph_dir,
        settings=settings,
        attach_policy=resolved_attach_policy,
    )
    attach_decision = _apply_attach_policy(
        attach_decision,
        attach_policy=resolved_attach_policy,
        approval_resolver=attach_approval_resolver,
    )
    fallback_reason = attach_decision.reason
    if attach_decision.approval.declined:
        fallback_reason = attach_decision.approval.reason
    managed_command, probe_url, scenario_urls, scenario_driver_command, ready_timeout, managed_error = (
        _resolve_managed_runtime_config(settings)
    )

    if pytest_targets is not None:
        return RuntimePlan(
            mode="traced_tests",
            resolution="deprecated_alias",
            command=(sys.executable, "-m", "pytest", *pytest_targets),
            fallback_reason=managed_error or fallback_reason,
            detected_targets=detected_targets,
            attach_decision=attach_decision,
        )

    if attach_decision.approved_for_execution:
        return _approved_attach_plan(
            attach_decision,
            detected_targets=detected_targets,
            settings=settings,
        )

    if managed_command:
        return RuntimePlan(
            mode="managed_python_server",
            resolution="managed_runtime_config",
            command=managed_command,
            fallback_reason=fallback_reason,
            detected_targets=detected_targets,
            attach_decision=attach_decision,
            probe_url=probe_url,
            scenario_urls=scenario_urls,
            scenario_driver_command=scenario_driver_command,
            ready_timeout=ready_timeout,
        )

    override = load_sync_test_command(repo_root)
    if override:
        return RuntimePlan(
            mode="traced_tests",
            resolution="config_override",
            command=tuple(override),
            fallback_reason=managed_error or fallback_reason,
            detected_targets=detected_targets,
            attach_decision=attach_decision,
        )

    if _repo_has_pytest_signal(repo_root):
        tests_dir = Path(repo_root) / "tests"
        if tests_dir.is_dir():
            return RuntimePlan(
                mode="traced_tests",
                resolution="pyproject_tests_dir",
                command=(sys.executable, "-m", "pytest", "tests"),
                fallback_reason=managed_error or fallback_reason,
                detected_targets=detected_targets,
                attach_decision=attach_decision,
            )
        return RuntimePlan(
            mode="traced_tests",
            resolution="pyproject",
            command=(sys.executable, "-m", "pytest"),
            fallback_reason=managed_error or fallback_reason,
            detected_targets=detected_targets,
            attach_decision=attach_decision,
        )

    auto_dir = _repo_has_tests_dir(repo_root)
    if auto_dir:
        return RuntimePlan(
            mode="traced_tests",
            resolution=f"auto_detected_{auto_dir}",
            command=(sys.executable, "-m", "pytest", auto_dir),
            fallback_reason=managed_error or fallback_reason,
            detected_targets=detected_targets,
            attach_decision=attach_decision,
        )

    return RuntimePlan(
        mode="none",
        resolution="managed_runtime_config_invalid" if managed_error else ("live_target_detected" if detected_targets else ""),
        command=(),
        skip_reason=(
            managed_error
            or (attach_decision.reason if attach_decision.present else "no_pytest_signal")
        ),
        fallback_reason=managed_error or fallback_reason,
        detected_targets=detected_targets,
        attach_decision=attach_decision,
    )
