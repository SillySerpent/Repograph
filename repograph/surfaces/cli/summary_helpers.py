"""Helpers for the compact `repograph summary` surface."""
from __future__ import annotations

from typing import Any

from repograph.plugins.exporters.agent_guide.generator import _extract_repo_summary

__all__ = [
    "SUMMARY_TOP_LEVEL_KEYS",
    "SUMMARY_TRUST_KEYS",
    "SUMMARY_ENTRY_POINT_KEYS",
    "SUMMARY_PATHWAY_KEYS",
    "SUMMARY_RISK_KEYS",
    "SUMMARY_HOTSPOT_KEYS",
    "build_summary_payload",
]

_SUMMARY_ENTRY_LIMIT = 5
_SUMMARY_PATHWAY_LIMIT = 5
_SUMMARY_HOTSPOT_LIMIT = 5

SUMMARY_TOP_LEVEL_KEYS = (
    "repo",
    "purpose",
    "stats",
    "health",
    "dynamic_analysis",
    "trust",
    "top_entry_points",
    "top_pathways",
    "major_risks",
    "structural_hotspots",
    "warnings",
    "dead_code_count",
    "dead_code_sample",
    "high_severity_duplicates",
    "duplicate_sample",
    "doc_warning_count",
)

SUMMARY_TRUST_KEYS = (
    "status",
    "sync_status",
    "sync_mode",
    "warnings",
    "analysis_readiness",
)

SUMMARY_ENTRY_POINT_KEYS = (
    "name",
    "file",
    "score",
    "callers",
    "callees",
    "entry_score_base",
    "entry_score_multipliers",
)

SUMMARY_PATHWAY_KEYS = (
    "name",
    "entry",
    "steps",
    "importance",
    "confidence",
    "source",
)

SUMMARY_RISK_KEYS = (
    "kind",
    "severity",
    "count",
    "summary",
)

SUMMARY_HOTSPOT_KEYS = (
    "module",
    "category",
    "summary",
    "function_count",
    "class_count",
    "test_function_count",
    "dead_code_count",
    "duplicate_count",
    "issue_count",
    "complexity",
)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        cleaned = (value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _summary_warning_list(report_data: dict[str, Any]) -> list[str]:
    health = report_data.get("health") or {}
    dynamic = health.get("dynamic_analysis") or {}
    warnings = list(report_data.get("report_warnings") or [])

    if health.get("status") == "degraded":
        warnings.insert(0, "Last sync completed with degraded health.")
    if health.get("partial_completion"):
        warnings.append("The last sync only partially completed.")
    if dynamic.get("requested") and not dynamic.get("executed"):
        reason = str(dynamic.get("skipped_reason") or "").strip() or "unspecified"
        warnings.append(f"Dynamic analysis was skipped ({reason}).")
    if not (report_data.get("entry_points") or []):
        warnings.append("No entry points were surfaced in the current snapshot.")
    if not (report_data.get("pathways") or []):
        warnings.append("No production pathways were surfaced in the current snapshot.")

    return _dedupe_preserve_order(warnings)


def _major_risks(report_data: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    health = report_data.get("health") or {}
    dynamic = health.get("dynamic_analysis") or {}
    dead = report_data.get("dead_code") or {}
    dead_prod = list(dead.get("definitely_dead") or []) + list(dead.get("probably_dead") or [])
    duplicates = [
        dup for dup in list(report_data.get("duplicates") or [])
        if dup.get("severity") == "high"
    ]
    doc_warnings = list(report_data.get("doc_warnings") or [])

    risks: list[dict[str, Any]] = []
    if dead_prod:
        risks.append({
            "kind": "dead_code",
            "severity": "high",
            "count": len(dead_prod),
            "summary": f"{len(dead_prod)} production dead-code candidate(s) remain in the snapshot.",
        })
    if duplicates:
        risks.append({
            "kind": "duplicates",
            "severity": "high",
            "count": len(duplicates),
            "summary": f"{len(duplicates)} high-severity duplicate symbol group(s) need review.",
        })
    if doc_warnings:
        risks.append({
            "kind": "doc_warnings",
            "severity": "medium",
            "count": len(doc_warnings),
            "summary": f"{len(doc_warnings)} high-severity doc/symbol mismatch warning(s) are present.",
        })
    if health.get("status") == "degraded":
        risks.append({
            "kind": "health",
            "severity": "high",
            "count": 1,
            "summary": "The last sync completed in degraded mode.",
        })
    if dynamic.get("requested") and not dynamic.get("executed"):
        risks.append({
            "kind": "dynamic_analysis",
            "severity": "medium",
            "count": 1,
            "summary": "Dynamic analysis was requested but not executed.",
        })
    if not risks and warnings:
        risks.append({
            "kind": "warnings",
            "severity": "low",
            "count": len(warnings),
            "summary": warnings[0],
        })

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(risks, key=lambda item: (severity_rank.get(item["severity"], 9), -int(item["count"])))


def _structural_hotspots(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for module in modules:
        issue_count = int(module.get("dead_code_count") or 0) + int(module.get("duplicate_count") or 0)
        complexity = (
            int(module.get("function_count") or 0)
            + int(module.get("class_count") or 0) * 2
            + int(module.get("test_function_count") or 0)
        )
        if module.get("path") == "__root__" and complexity == 0 and issue_count == 0:
            continue
        if complexity == 0 and issue_count == 0:
            continue
        candidates.append({
            "module": module.get("display") or module.get("path", ""),
            "category": module.get("category", "production"),
            "summary": module.get("summary", ""),
            "function_count": int(module.get("function_count") or 0),
            "class_count": int(module.get("class_count") or 0),
            "test_function_count": int(module.get("test_function_count") or 0),
            "dead_code_count": int(module.get("dead_code_count") or 0),
            "duplicate_count": int(module.get("duplicate_count") or 0),
            "issue_count": issue_count,
            "complexity": complexity,
        })

    candidates.sort(
        key=lambda item: (
            -item["issue_count"],
            0 if item["category"] == "production" else 1,
            -item["complexity"],
            item["module"],
        )
    )
    return candidates[:_SUMMARY_HOTSPOT_LIMIT]


def build_summary_payload(root: str, report_data: dict[str, Any]) -> dict[str, Any]:
    """Build the stable compact summary payload from a capped full-report snapshot."""
    purpose = report_data.get("purpose") or _extract_repo_summary(root)
    health = report_data.get("health") or {}
    analysis_readiness = health.get("analysis_readiness") or {}
    dynamic_analysis = health.get("dynamic_analysis") or {}
    warnings = _summary_warning_list(report_data)
    hotspots = _structural_hotspots(list(report_data.get("modules") or []))
    dead = report_data.get("dead_code") or {}
    dead_total = sum(
        len(list(dead.get(key) or []))
        for key in (
            "definitely_dead",
            "probably_dead",
            "definitely_dead_tooling",
            "probably_dead_tooling",
        )
    )
    duplicates = list(report_data.get("duplicates") or [])
    high_duplicates = [dup for dup in duplicates if dup.get("severity") == "high"]

    trust_status = "high"
    if health.get("status") == "degraded":
        trust_status = "degraded"
    elif warnings:
        trust_status = "caution"

    return {
        "repo": report_data.get("stats", {}).get("repo") or report_data.get("meta", {}).get("repo_path", root).split("/")[-1],
        "purpose": purpose,
        "stats": report_data.get("stats", {}),
        "health": health,
        "dynamic_analysis": dynamic_analysis,
        "trust": {
            "status": trust_status,
            "sync_status": health.get("status", "unknown"),
            "sync_mode": health.get("sync_mode", ""),
            "warnings": warnings,
            "analysis_readiness": analysis_readiness,
        },
        "top_entry_points": [
            {
                "name": ep.get("qualified_name", ""),
                "file": ep.get("file_path", ""),
                "score": ep.get("entry_score", 0.0),
                "callers": ep.get("entry_caller_count"),
                "callees": ep.get("entry_callee_count"),
                "entry_score_base": ep.get("entry_score_base"),
                "entry_score_multipliers": ep.get("entry_score_multipliers"),
            }
            for ep in list(report_data.get("entry_points") or [])[:_SUMMARY_ENTRY_LIMIT]
        ],
        "top_pathways": [
            {
                "name": pathway.get("name", ""),
                "entry": pathway.get("entry_function", ""),
                "steps": pathway.get("step_count", 0),
                "importance": pathway.get("importance_score", 0.0),
                "confidence": pathway.get("confidence", 0.0),
                "source": pathway.get("source", ""),
            }
            for pathway in list(report_data.get("pathways") or [])[:_SUMMARY_PATHWAY_LIMIT]
        ],
        "major_risks": _major_risks(report_data, warnings),
        "structural_hotspots": hotspots,
        "warnings": warnings,
        "dead_code_count": dead_total,
        "dead_code_sample": [
            row.get("qualified_name", "")
            for row in (
                list(dead.get("definitely_dead") or [])
                + list(dead.get("probably_dead") or [])
                + list(dead.get("definitely_dead_tooling") or [])
                + list(dead.get("probably_dead_tooling") or [])
            )[:_SUMMARY_ENTRY_LIMIT]
        ],
        "high_severity_duplicates": len(high_duplicates),
        "duplicate_sample": [dup.get("name", "") for dup in high_duplicates[:_SUMMARY_ENTRY_LIMIT]],
        "doc_warning_count": len(list(report_data.get("doc_warnings") or [])),
    }
