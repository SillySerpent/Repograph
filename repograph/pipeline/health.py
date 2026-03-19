"""Index health report — persisted to ``.repograph/meta/health.json`` after sync."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repograph.settings import ERROR_TRUNCATION_CHARS as _ERROR_TRUNCATION_CHARS
from repograph.graph_store.store import GraphStore
from repograph.trust.contract import CONTRACT_VERSION


def _read_json_file(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _trace_inventory(repograph_dir: str) -> tuple[bool, int, int | None]:
    runtime_dir = Path(repograph_dir) / "runtime"
    if not runtime_dir.is_dir():
        return False, 0, 0

    try:
        trace_files = sorted(path for path in runtime_dir.iterdir() if path.is_file())
    except OSError:
        return True, 0, None

    record_count = 0
    for path in trace_files:
        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                record_count += sum(1 for _ in fh)
        except OSError:
            return True, len(trace_files), None
    return True, len(trace_files), record_count


def _pathway_context_counts(store: GraphStore | None) -> tuple[int | None, int | None]:
    if store is None:
        return None, None
    try:
        rows = store.query("MATCH (p:Pathway) RETURN p.context_doc")
    except Exception:
        return None, None
    total = len(rows)
    with_context = sum(1 for row in rows if (row[0] or "").strip())
    return total, with_context


def _plugin_executed(hook_summary: dict[str, Any], plugin_id: str) -> bool:
    plugins = (
        hook_summary.get("dynamic_stage", {}).get("plugins", {})
        if isinstance(hook_summary, dict)
        else {}
    )
    plugin_state = plugins.get(plugin_id)
    return bool(isinstance(plugin_state, dict) and plugin_state.get("executed"))


def _build_analysis_readiness(
    *,
    repo_root: str,
    repograph_dir: str,
    store: GraphStore | None = None,
    hook_summary: dict[str, Any] | None = None,
    dynamic_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hook_summary = hook_summary or {}
    dynamic_analysis = dynamic_analysis or {}

    runtime_dir_present, trace_file_count, trace_record_count = _trace_inventory(repograph_dir)
    if dynamic_analysis:
        trace_file_count = int(dynamic_analysis.get("trace_file_count", trace_file_count) or 0)
        trace_record_value = dynamic_analysis.get("trace_record_count", trace_record_count)
        trace_record_count = int(trace_record_value) if trace_record_value is not None else None

    coverage_json_present = bool(
        dynamic_analysis.get("coverage_json_present")
        if "coverage_json_present" in dynamic_analysis
        else os.path.isfile(os.path.join(repo_root, "coverage.json"))
    )
    runtime_overlay_applied = bool(
        dynamic_analysis.get("runtime_overlay_applied")
        if "runtime_overlay_applied" in dynamic_analysis
        else (
            trace_file_count > 0
            and _plugin_executed(hook_summary, "dynamic_analyzer.runtime_overlay")
        )
    )
    coverage_overlay_applied = bool(
        dynamic_analysis.get("coverage_overlay_applied")
        if "coverage_overlay_applied" in dynamic_analysis
        else (
            coverage_json_present
            and _plugin_executed(hook_summary, "dynamic_analyzer.coverage_overlay")
        )
    )

    pathways_total, pathways_with_context = _pathway_context_counts(store)
    diagnostics = _read_json_file(
        os.path.join(repograph_dir, "meta", "config_registry_diagnostics.json")
    ) or {}

    return {
        "runtime_trace_dir_present": runtime_dir_present,
        "trace_file_count": trace_file_count,
        "trace_record_count": trace_record_count,
        "runtime_overlay_applied": runtime_overlay_applied,
        "coverage_json_present": coverage_json_present,
        "coverage_overlay_applied": coverage_overlay_applied,
        "pathways_total": pathways_total,
        "pathways_with_context": pathways_with_context,
        "pathway_contexts_generated": bool(pathways_with_context),
        "config_registry_status": diagnostics.get("status"),
        "config_registry_registry_keys": diagnostics.get("registry_keys"),
        "config_registry_pathways_total": diagnostics.get("pathways_total"),
        "config_registry_pathways_with_context": diagnostics.get("pathways_with_context"),
        "config_registry_pathway_backed": bool(diagnostics.get("pathways_with_context")),
    }


def build_health_report(
    store: GraphStore,
    stats: dict[str, int],
    *,
    repo_root: str,
    repograph_dir: str,
    sync_mode: str,
    files_walked: int | None = None,
    strict: bool = False,
    hook_summary: dict[str, Any] | None = None,
    dynamic_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Collect post-sync diagnostic counters (best-effort, never raises)."""
    report: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sync_mode": sync_mode,
        "repo_root": os.path.abspath(repo_root),
        "stats": dict(stats),
    }
    if files_walked is not None:
        report["files_walked"] = files_walked

    try:
        rows = store.query(
            "MATCH (a:Function)-[e:CALLS]->(b:Function) RETURN count(*)"
        )
        report["call_edges_total"] = int(rows[0][0]) if rows else 0
    except Exception:
        report["call_edges_total"] = None

    try:
        rows = store.query(
            "MATCH (a:Function)-[e:CALLS]->(b:Function) "
            "RETURN e.reason, count(*)"
        )
        by_reason: dict[str, int] = {}
        for r in rows:
            reason = r[0] or ""
            by_reason[str(reason)] = int(r[1])
        report["call_edges_by_reason"] = dict(sorted(by_reason.items()))
    except Exception:
        report["call_edges_by_reason"] = None

    report["status"] = "ok"
    report["strict"] = strict
    hs = hook_summary or {}
    failed = int(hs.get("failed_count") or 0)
    report["hook_summary"] = {
        "failed_count": failed,
        "failed": hs.get("failed") or [],
        "warnings_count": int(hs.get("warnings_count") or 0),
    }
    report["dynamic_analysis"] = dict(dynamic_analysis or {})
    report["analysis_readiness"] = _build_analysis_readiness(
        repo_root=repo_root,
        repograph_dir=repograph_dir,
        store=store,
        hook_summary=hs,
        dynamic_analysis=dynamic_analysis,
    )
    report["partial_completion"] = failed > 0
    if failed > 0:
        report["status"] = "degraded"
    return report


def build_health_failure_report(
    *,
    repo_root: str,
    repograph_dir: str,
    sync_mode: str,
    error_phase: str,
    error_message: str,
    strict: bool = False,
    partial_stats: dict[str, int] | None = None,
    dynamic_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a loud failure marker after a pipeline or phase crash."""
    analysis_readiness = _build_analysis_readiness(
        repo_root=repo_root,
        repograph_dir=repograph_dir,
        dynamic_analysis=dynamic_analysis,
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sync_mode": sync_mode,
        "repo_root": os.path.abspath(repo_root),
        "stats": dict(partial_stats) if partial_stats else {},
        "status": "failed",
        "error_phase": error_phase,
        "error_message": (error_message or "")[:_ERROR_TRUNCATION_CHARS],
        "strict": strict,
        "call_edges_total": None,
        "call_edges_by_reason": None,
        "dynamic_analysis": dict(dynamic_analysis or {}),
        "analysis_readiness": analysis_readiness,
    }


def write_health_json(repograph_dir: str, report: dict[str, Any]) -> str:
    """Write ``meta/health.json``; returns absolute path."""
    meta = os.path.join(repograph_dir, "meta")
    os.makedirs(meta, exist_ok=True)
    path = os.path.join(meta, "health.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    return path


def read_health_json(repograph_dir: str) -> dict[str, Any] | None:
    """Load health report if present."""
    path = os.path.join(repograph_dir, "meta", "health.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None
