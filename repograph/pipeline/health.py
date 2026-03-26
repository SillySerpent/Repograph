"""Index health report — persisted to ``.repograph/meta/health.json`` after sync."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from repograph.graph_store.store import GraphStore
from repograph.trust.contract import CONTRACT_VERSION


def build_health_report(
    store: GraphStore,
    stats: dict[str, int],
    *,
    repo_root: str,
    repograph_dir: str,
    sync_mode: str,
    files_walked: int | None = None,
    strict: bool = False,
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
) -> dict[str, Any]:
    """Persist a loud failure marker after a pipeline or phase crash."""
    return {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sync_mode": sync_mode,
        "repo_root": os.path.abspath(repo_root),
        "stats": dict(partial_stats) if partial_stats else {},
        "status": "failed",
        "error_phase": error_phase,
        "error_message": (error_message or "")[:4000],
        "strict": strict,
        "call_edges_total": None,
        "call_edges_by_reason": None,
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
