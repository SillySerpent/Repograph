"""Plugin-hook execution for post-build analysis, evidence, and exports.

Hook firing is intentionally separated from static phase orchestration so the
full, incremental, and runtime-overlay coordinators can all reuse one
well-defined hook contract and one failure-reporting policy.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from repograph.core.models import ParsedFile
from repograph.core.plugin_framework.contracts import HookName
from repograph.graph_store.store import GraphStore
from repograph.observability import span
from repograph.runtime.orchestration import dynamic_input_state
from repograph.utils import logging as rg_log

from .config import RunConfig
from .shared import handle_optional_phase_failure, phase_scope

__all__ = [
    "dynamic_findings_count",
    "fire_hooks",
    "merge_hook_summaries",
]


def fire_hooks(
    config: RunConfig,
    store: GraphStore,
    parsed: list[ParsedFile],
    *,
    run_graph_built: bool = True,
    run_dynamic: bool = True,
    run_evidence: bool = True,
    run_export: bool = True,
) -> dict[str, object]:
    """Fire all post-build plugin hooks in order."""
    from repograph.plugins.lifecycle import get_hook_scheduler

    hooks = get_hook_scheduler()
    dynamic_inputs = dynamic_input_state(config.repo_root, config.repograph_dir)
    summary: dict[str, Any] = {
        "failed_count": 0,
        "warnings_count": 0,
        "failed": [],
        "dynamic_stage": {
            "executed": False,
            "trace_file_count": dynamic_inputs.trace_file_count,
            "trace_record_count": dynamic_inputs.trace_record_count,
            "coverage_json_present": dynamic_inputs.coverage_json_present,
            "inputs_present": dynamic_inputs.inputs_present,
            "plugins": {},
        },
    }

    def _mark_failed(hook_name: str, plugin_id: str, error: str) -> None:
        summary["failed_count"] = int(summary.get("failed_count", 0)) + 1
        summary["warnings_count"] = int(summary.get("warnings_count", 0)) + 1
        failed = list(summary.get("failed") or [])
        failed.append({"hook": hook_name, "plugin_id": plugin_id, "error": error[:500]})
        summary["failed"] = failed

    def _run_stage(
        hook_name: HookName,
        failure_label: str,
        **kwargs: Any,
    ) -> list[Any]:
        try:
            with span(
                f"hook_stage.{hook_name}",
                subsystem="pipeline",
                hook=hook_name,
            ):
                results = hooks.fire(hook_name, **kwargs)
            for result in results:
                if not result.succeeded:
                    rg_log.warn(f"{hook_name}: {result.plugin_id} failed: {result.error}")
                    _mark_failed(hook_name, result.plugin_id, result.error or "")
            return list(results)
        except Exception as exc:
            _mark_failed(hook_name, "scheduler", f"{type(exc).__name__}: {exc}")
            handle_optional_phase_failure(config, failure_label, exc)
            return []

    if run_graph_built:
        with phase_scope("hook_stage.on_graph_built"):
            _run_stage(
                "on_graph_built",
                "on_graph_built hook",
                store=store,
                repo_path=config.repo_root,
                repograph_dir=config.repograph_dir,
                parsed=parsed,
                config=config,
            )

    trace_dir = Path(config.repograph_dir) / "runtime"
    if run_dynamic and dynamic_inputs.inputs_present:
        rg_log.info("Dynamic inputs found — running runtime / coverage overlay analysis")
        with phase_scope("hook_stage.on_traces_collected"):
            results = _run_stage(
                "on_traces_collected",
                "dynamic analysis hooks",
                trace_dir=trace_dir,
                store=store,
                repo_path=config.repo_root,
                repo_root=config.repo_root,
                config=config,
            )
        summary["dynamic_stage"]["executed"] = True
        summary["dynamic_stage"]["plugins"] = {
            result.plugin_id: {
                "executed": bool(result.succeeded),
                "has_result": bool(result.result),
                "result_count": (
                    len(result.result)
                    if isinstance(result.result, list)
                    else (1 if result.result else 0)
                ),
            }
            for result in results
        }
        try:
            with phase_scope("hook_stage.on_traces_analyzed"):
                hooks.fire("on_traces_analyzed", store=store, config=config)
        except Exception as exc:
            _mark_failed("on_traces_analyzed", "scheduler", f"{type(exc).__name__}: {exc}")
            handle_optional_phase_failure(config, "on_traces_analyzed hook", exc)
        findings = sum(
            len(result.result or [])
            for result in results
            if getattr(result, "succeeded", False)
        )
        summary["dynamic_findings_count"] = findings
        rg_log.success(
            f"Dynamic overlay: {findings} alert finding(s) "
            f"(0 is normal if dead-code already skipped observed symbols)"
        )

    if run_evidence:
        with phase_scope("hook_stage.on_evidence"):
            _run_stage(
                "on_evidence",
                "on_evidence hook",
                store=store,
                repo_path=config.repo_root,
                repograph_dir=config.repograph_dir,
            )

    if run_export:
        with phase_scope("hook_stage.on_export"):
            _run_stage(
                "on_export",
                "on_export hook",
                store=store,
                repograph_dir=config.repograph_dir,
                config=config,
            )
    return summary


def merge_hook_summaries(*parts: dict[str, Any]) -> dict[str, Any]:
    """Merge multiple hook-summary payloads into one reportable dict."""
    failed: list[dict[str, Any]] = []
    findings = 0
    for part in parts:
        failed.extend(list(part.get("failed") or []))
        findings += int(part.get("dynamic_findings_count") or 0)
    return {
        "failed_count": len(failed),
        "warnings_count": len(failed),
        "failed": failed,
        "dynamic_findings_count": findings,
    }


def dynamic_findings_count(hook_summary: dict[str, Any]) -> int:
    """Return the hook-reported dynamic findings count as an int."""
    value = hook_summary.get("dynamic_findings_count")
    return int(value) if isinstance(value, int) else 0
