"""Overlay runtime trace findings onto the static graph.

Takes the JSONL traces produced by SysTracer (or any jsonl_call_trace
compatible tracer) and:

1. Resolves observed call targets against the **existing** graph (read-only).
2. Compares to static ``CALLS`` to list edges that look missing from static analysis.
3. Returns structured findings (``observed_live_but_static_dead``, ``dynamic_call_edge``, …).

**Persistence:** findings are **not** written to ``graph.db`` here — only returned to
callers (e.g. sync hook logging, ``repograph trace report``). Durable inputs are the
``.jsonl`` files under ``.repograph/runtime/``.

This module is the pure logic layer — the DynamicAnalyzerPlugin in
plugins/dynamic_analyzers/runtime_overlay/plugin.py calls it.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repograph.runtime.trace_format import collect_trace_files, iter_records


def _norm_rel_path(p: str) -> str:
    return p.replace("\\", "/").strip()


def _build_function_indexes(store: Any) -> tuple[dict[str, str], dict[tuple[str, str], str], dict[str, str]]:
    """Maps for resolving JSONL ``fn`` strings to graph function ids.

    SysTracer emits ``fn`` like ``pkg.subpkg.module.build_plugin`` (``__name__`` +
    ``co_qualname``). The graph often stores top-level ``qualified_name`` as
    ``build_plugin`` only. Indexing ``(file_path, name)`` disambiguates duplicate
    simple names across files.
    """
    fn_qname_to_id: dict[str, str] = {}
    file_and_name_to_id: dict[tuple[str, str], str] = {}
    fn_name_to_id: dict[str, str] = {}
    try:
        for fn in store.get_all_functions():
            fid = fn.get("id", "")
            if not fid:
                continue
            fp = _norm_rel_path(fn.get("file_path") or "")
            nm = fn.get("name", "") or ""
            qn = fn.get("qualified_name", "") or ""
            if qn:
                fn_qname_to_id[qn] = fid
            if fp and nm:
                file_and_name_to_id[(fp, nm)] = fid
            if nm:
                fn_name_to_id[nm] = fid
    except Exception:
        pass
    return fn_qname_to_id, file_and_name_to_id, fn_name_to_id


def _resolve_trace_to_fn_id(
    fn_qn: str,
    file_path: str,
    *,
    fn_qname_to_id: dict[str, str],
    file_and_name_to_id: dict[tuple[str, str], str],
    fn_name_to_id: dict[str, str],
) -> str:
    """Map a trace ``fn`` (+ callee ``file``) to a graph function id."""
    if not fn_qn:
        return ""
    tail = fn_qn.split(".")[-1]
    fp = _norm_rel_path(file_path or "")
    if fn_qn in fn_qname_to_id:
        return fn_qname_to_id[fn_qn]
    if fp and tail:
        hit = file_and_name_to_id.get((fp, tail))
        if hit:
            return hit
    if tail in fn_qname_to_id:
        return fn_qname_to_id[tail]
    return fn_name_to_id.get(tail, "")


def overlay_traces(
    trace_dir: Path,
    store: Any,
    repo_root: str = "",
) -> dict[str, Any]:
    """Consume all trace files in *trace_dir* and return an overlay report.

    Parameters
    ----------
    trace_dir:
        Directory containing ``.jsonl`` trace files.
    store:
        Open GraphStore — used for symbol lookups and to mark observed nodes.
    repo_root:
        Repository root for path normalisation (optional).

    Returns
    -------
    dict with keys:
        observed_fn_count   — unique function IDs observed at runtime
        new_edge_count      — call edges not present in the static graph
        trace_file_count    — number of trace files consumed
        observed_fns        — list of observed qualified names (top 50)
        new_edges           — list of {caller, callee, file, line} (top 50)
        findings            — list of finding dicts (StaticAnalyzerPlugin schema)
    """
    trace_files = collect_trace_files(trace_dir.parent)
    if not trace_files:
        return _empty_report()

    # Build static call edge set for new-edge detection
    static_edges: set[tuple[str, str]] = set()
    try:
        for e in store.get_all_call_edges():
            static_edges.add((e.get("from", ""), e.get("to", "")))
    except Exception:
        pass

    fn_qname_to_id, file_and_name_to_id, fn_name_to_id = _build_function_indexes(store)

    observed_fns: set[str] = set()          # qualified names
    observed_fn_ids: set[str] = set()       # graph IDs
    call_counts: dict[str, int] = defaultdict(int)
    calls_by_function_id: dict[str, int] = defaultdict(int)
    new_edges: list[dict] = []
    total_call_records = 0
    resolved_call_records = 0
    unresolved_examples: set[str] = set()

    for trace_file in trace_files:
        for record in iter_records(trace_file):
            if record.get("kind") != "call":
                continue
            total_call_records += 1

            fn_qn = record.get("fn", "")
            caller_qn = record.get("caller", "")
            file_path = record.get("file", "")
            line = record.get("line", 0)

            if fn_qn:
                observed_fns.add(fn_qn)
                call_counts[fn_qn] += 1

                # Resolve to graph function id (for in-memory findings only)
                fn_id = _resolve_trace_to_fn_id(
                    fn_qn,
                    file_path,
                    fn_qname_to_id=fn_qname_to_id,
                    file_and_name_to_id=file_and_name_to_id,
                    fn_name_to_id=fn_name_to_id,
                )
                if fn_id:
                    observed_fn_ids.add(fn_id)
                    calls_by_function_id[fn_id] += 1
                    resolved_call_records += 1
                elif fn_qn and len(unresolved_examples) < 50:
                    unresolved_examples.add(fn_qn)

            # Detect new dynamic edges
            if fn_qn and caller_qn:
                fn_id = _resolve_trace_to_fn_id(
                    fn_qn,
                    file_path,
                    fn_qname_to_id=fn_qname_to_id,
                    file_and_name_to_id=file_and_name_to_id,
                    fn_name_to_id=fn_name_to_id,
                )
                caller_id = _resolve_trace_to_fn_id(
                    caller_qn,
                    "",
                    fn_qname_to_id=fn_qname_to_id,
                    file_and_name_to_id=file_and_name_to_id,
                    fn_name_to_id=fn_name_to_id,
                )
                if fn_id and caller_id and (caller_id, fn_id) not in static_edges:
                    new_edges.append({
                        "caller": caller_qn,
                        "callee": fn_qn,
                        "file": file_path,
                        "line": line,
                        "caller_id": caller_id,
                        "callee_id": fn_id,
                    })

    # Build findings list
    findings: list[dict] = []

    # Finding: function observed at runtime but marked as dead statically
    try:
        dead_ids = {
            fn.get("id", "")
            for fn in store.get_all_functions()
            if fn.get("is_dead")
        }
    except Exception:
        dead_ids = set()

    for fn_id in observed_fn_ids:
        if fn_id in dead_ids:
            findings.append({
                "kind": "observed_live_but_static_dead",
                "severity": "low",
                "function_id": fn_id,
                "description": "Function marked dead statically but observed at runtime.",
            })

    # Finding: new dynamic edge not in static graph
    for edge in new_edges[:100]:
        findings.append({
            "kind": "dynamic_call_edge",
            "severity": "info",
            "caller": edge["caller"],
            "callee": edge["callee"],
            "file": edge["file"],
            "line": edge["line"],
            "description": "Call edge observed at runtime but absent from static graph.",
        })

    return {
        "observed_fn_count": len(observed_fns),
        "new_edge_count": len(new_edges),
        "trace_file_count": len(trace_files),
        "observed_fns": sorted(observed_fns)[:50],
        "new_edges": new_edges[:50],
        "findings": findings,
        "top_calls": sorted(call_counts.items(), key=lambda x: -x[1])[:20],
        "calls_by_function_id": dict(calls_by_function_id),
        "trace_call_records": total_call_records,
        "resolved_trace_calls": resolved_call_records,
        "unresolved_trace_calls": max(0, total_call_records - resolved_call_records),
        "unresolved_examples": sorted(unresolved_examples)[:20],
    }


def _empty_report() -> dict[str, Any]:
    return {
        "observed_fn_count": 0,
        "new_edge_count": 0,
        "trace_file_count": 0,
        "observed_fns": [],
        "new_edges": [],
        "findings": [],
        "top_calls": [],
        "calls_by_function_id": {},
        "trace_call_records": 0,
        "resolved_trace_calls": 0,
        "unresolved_trace_calls": 0,
        "unresolved_examples": [],
    }


def persist_runtime_overlay_to_store(
    store: Any,
    report: dict[str, Any],
    *,
    observed_at_iso: str | None = None,
) -> int:
    """Write runtime overlay results onto ``Function`` nodes in the graph store.

    Sets ``runtime_observed*`` fields and clears static dead-code flags for
    functions that were actually executed (for the current ``source_hash``).

    Stale observations are dropped automatically on the next index: ``upsert_function``
    clears runtime fields when ``source_hash`` changes.
    """
    cb = report.get("calls_by_function_id") or {}
    if not cb:
        return 0
    ts = observed_at_iso or datetime.now(timezone.utc).isoformat()
    by_id = {f["id"]: f for f in store.get_all_functions()}
    n = 0
    for fn_id, n_calls in cb.items():
        row = by_id.get(fn_id)
        if not row:
            continue
        h = (row.get("source_hash") or "").strip()
        if not h:
            continue
        store.apply_runtime_observation(
            fn_id,
            calls=int(n_calls),
            observed_at_iso=ts,
            source_hash=h,
        )
        n += 1
    return n
