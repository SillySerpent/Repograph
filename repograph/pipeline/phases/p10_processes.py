"""Phase 10 — Processes: entry point scoring and BFS pathway tracing."""
from __future__ import annotations

import json
import re

from repograph.core.models import ProcessNode, NodeID
from repograph.core.confidence import geometric_mean_confidence
from repograph.graph_store.store import GraphStore
from repograph.plugins.static_analyzers.dead_code.plugin import rollup_override_incoming_callers
from repograph.plugins.static_analyzers.pathways.scorer import score_function_verbose as _score_fn_verbose
from repograph.plugins.static_analyzers.pathways.assembler import _auto_name  # canonical plugin-owned implementation
from repograph.plugins.static_analyzers.pathways.pathway_bfs import (
    MIN_CONFIDENCE,
    bfs_pathway_function_ids,
    build_outgoing_index,
)
from repograph.utils.fs import _is_test_file  # single source of truth


def run(store: GraphStore) -> None:
    """Score entry points, run BFS from top candidates, store Process nodes."""
    functions = store.get_all_functions()
    if not functions:
        return

    call_edges = store.get_all_call_edges()

    # Caller count per function (how many functions call this one)
    caller_counts: dict[str, int] = {}
    callee_counts: dict[str, int] = {}
    for fn in functions:
        caller_counts[fn["id"]] = 0
        callee_counts[fn["id"]] = 0
    for e in call_edges:
        callee_counts[e["from"]] = callee_counts.get(e["from"], 0) + 1
        caller_counts[e["to"]] = caller_counts.get(e["to"], 0) + 1

    rollup_override_incoming_callers(store, caller_counts)

    # Build outgoing call index
    outgoing = build_outgoing_index(call_edges)

    # Build the set of function IDs that are concrete implementations of
    # abstract methods (ABC / Protocol).  These receive a scoring boost in
    # score_function() so all strategy/plugin variants surface in pathways.
    abc_implementor_ids = _build_abc_implementor_ids(store)

    test_func_ids: set[str] = set()
    for fn in functions:
        fp = fn.get("file_path", "") or ""
        if fn.get("is_test") or _is_test_file(fp):
            test_func_ids.add(fn["id"])

    # Score every function
    functions_by_id = {f["id"]: f for f in functions}
    scored: list[tuple[float, dict]] = []
    for fn in functions:
        is_abc = fn["id"] in abc_implementor_ids
        bd = _score_fn_verbose(
            fn,
            callee_counts.get(fn["id"], 0),
            caller_counts.get(fn["id"], 0),
            abc_implementor=is_abc,
        )
        score = bd.final_score
        if score > 0:
            scored.append((score, fn))
            is_ep = _compute_is_entry_point(
                fn, score, call_edges, test_func_ids, caller_counts, callee_counts,
            )
            store.update_function_flags(
                fn["id"],
                is_entry_point=is_ep,
                entry_score=score,
                entry_score_base=bd.base_score,
                entry_score_multipliers=json.dumps(bd.multipliers),
                entry_callee_count=bd.callees_count,
                entry_caller_count=bd.callers_count,
            )

    scored.sort(key=lambda x: -x[0])

    # Take top N candidates — exclude test functions from BFS pathway tracing.
    # Test functions are already scored 0.0 by the scorer, but we guard here
    # as well to be safe and to keep the production pathway list clean.
    file_count = len({fn["file_path"] for fn in functions})
    top_n = max(10, file_count // 20)
    # is_module_caller sentinels are internal; never start BFS from them (BUG-002).
    top_candidates = [
        (sc, fn) for sc, fn in scored[:top_n * 2]
        if not _is_test_file(fn.get("file_path", "") or "")
        and not fn.get("is_module_caller")
        and _compute_is_entry_point(
            fn, sc, call_edges, test_func_ids, caller_counts, callee_counts,
        )
    ][:top_n]

    # BFS from each candidate
    for score, fn in top_candidates:
        steps = bfs_pathway_function_ids(
            fn["id"],
            outgoing,
            functions_by_id,
            fn.get("file_path", "") or "",
        )
        if len(steps) < 2:
            continue

        confidences = [
            e["confidence"]
            for step_id in steps
            for e in outgoing.get(step_id, [])
            if e["to"] in {s for s in steps}
        ]
        path_conf = geometric_mean_confidence(confidences) if confidences else score / 10.0
        path_conf = min(1.0, path_conf)

        proc_id = f"process:{fn['id']}"
        proc = ProcessNode(
            id=proc_id,
            entry_id=fn["id"],
            step_count=len(steps),
            confidence=path_conf,
        )
        _persist_process(store, proc, steps, fn, path_conf, functions_by_id)

    # Second pass: pytest ``test_*`` entry pathways (also appended after pathway rebuild).
    append_pytest_coverage_pathways(store)




def _in_route_style_file(fn: dict) -> bool:
    fp = (fn.get("file_path", "") or "").replace("\\", "/")
    return any(
        f"/{d}/" in fp or fp.startswith(f"{d}/")
        for d in ("routes", "handlers", "views", "api", "endpoints", "controllers")
    )


def _compute_is_entry_point(
    fn: dict,
    score: float,
    call_edges: list[dict],
    test_func_ids: set[str],
    caller_counts: dict[str, int],
    callee_counts: dict[str, int],
) -> bool:
    """Whether this function should be marked ``is_entry_point``.

    Library code with only test callers is not an entry surface.  Route-style
    handlers that only tests call are kept when they **call into** other
    symbols (non-zero fan-out), so pathways can start from ``login_handler``
    but stub handlers like ``logout_handler`` (no callees) stay eligible for
    dead-code classification.
    """
    if score <= 0:
        return False
    only_test = _all_incoming_callers_are_test(fn["id"], call_edges, test_func_ids)
    if not only_test:
        return True
    return _in_route_style_file(fn) and callee_counts.get(fn["id"], 0) > 0


def _all_incoming_callers_are_test(
    fn_id: str,
    call_edges: list[dict],
    test_func_ids: set[str],
) -> bool:
    """True when every CALLS edge targeting ``fn_id`` originates from a test function."""
    incoming = [e for e in call_edges if e["to"] == fn_id]
    if not incoming:
        return False
    return all(e["from"] in test_func_ids for e in incoming)


def _infer_role(func: dict, order: int) -> str:
    """Assign a role label based on position and file path."""
    file_path = func.get("file_path", "")
    if order == 0:
        return "entry"
    if re.search(r"/(routes|handlers|views|api|endpoints|controllers)/", file_path):
        return "handler"
    if re.search(r"/(services|service)/", file_path):
        return "service"
    if re.search(r"/(adapters|repositories|db|models|database)/", file_path):
        return "adapter"
    if order <= 2:
        return "handler"
    return "service"


def _persist_process(
    store: GraphStore,
    proc: ProcessNode,
    steps: list[str],
    entry_fn: dict,
    confidence: float,
    functions_by_id: dict[str, dict],
    *,
    min_pathway_steps: int = 3,
) -> None:
    """Store a Process as a minimal Pathway node."""
    from repograph.core.models import PathwayDoc, PathwayStep
    from datetime import datetime, timezone

    # Enforce minimum pathway depth — a 2-step pathway is just a single
    # function call and provides no architectural insight.
    if len(steps) < min_pathway_steps:
        return

    # functions_by_id is passed in — no DB round-trip needed here
    pathway_steps = []
    for i, fid in enumerate(steps):
        fn = functions_by_id.get(fid)
        if not fn:
            continue
        role = _infer_role(fn, i)
        # Mark last step as terminal
        if i == len(steps) - 1:
            role = "terminal"
        pathway_steps.append(PathwayStep(
            order=i,
            function_id=fid,
            function_name=fn.get("name", ""),
            file_path=fn.get("file_path", ""),
            line_start=fn.get("line_start", 0),
            role=role,
            calls_next=[],
        ))

    if not pathway_steps:
        return

    entry_fn_data = functions_by_id.get(entry_fn["id"], entry_fn)
    pathway_id = f"pathway:{entry_fn['id']}"
    auto_name = _auto_name(
        entry_fn.get("name", "unknown"),
        entry_fn.get("qualified_name", ""),
        entry_fn.get("file_path", ""),
    )

    # Detect test pathways — mark source so consumers can filter
    entry_file = entry_fn.get("file_path", "")
    is_test = _is_test_file(entry_file)
    source = "auto_detected_test" if is_test else "auto_detected"

    from repograph.plugins.static_analyzers.pathways.descriptions import generate_description

    _pf = list(dict.fromkeys(s.file_path for s in pathway_steps))
    _desc = generate_description(
        entry_fn_data,
        _pf,
        store,
        [],
        step_count=len(pathway_steps),
        file_count=len(_pf),
    )

    doc = PathwayDoc(
        id=pathway_id,
        name=auto_name,
        display_name=auto_name.replace("_", " ").title(),
        description=_desc,
        entry_file=entry_file,
        entry_function=entry_fn.get("qualified_name", ""),
        terminal_type="return",
        steps=pathway_steps,
        variable_threads=[],
        participating_files=list(dict.fromkeys(s.file_path for s in pathway_steps)),
        confidence=confidence,
        source=source,
        context_doc="",  # filled by context generator later
        generated_at=datetime.now(timezone.utc),
    )

    try:
        store.upsert_pathway(doc)
        for step in pathway_steps:
            store.insert_step_in_pathway(step.function_id, pathway_id, step.order, step.role)
    except Exception:
        pass


def append_pytest_coverage_pathways(store: GraphStore) -> None:
    """Persist BFS pathways starting at ``test_*`` functions (``auto_detected_test``).

    Called from phase 10 and again after :func:`run_pathway_build`, which clears
    pathways and rebuilds production-only — without this, test pathways vanish.
    """
    functions = store.get_all_functions()
    if not functions:
        return
    call_edges = store.get_all_call_edges()
    outgoing = build_outgoing_index(call_edges)
    functions_by_id = {f["id"]: f for f in functions}
    file_count = len({fn["file_path"] for fn in functions})
    top_n = max(10, file_count // 20)
    test_starters: list[dict] = []
    for fn in functions:
        if not _is_test_file(fn.get("file_path", "") or ""):
            continue
        if not (fn.get("name", "") or "").startswith("test_"):
            continue
        if outgoing.get(fn["id"]):
            test_starters.append(fn)
    test_limit = max(top_n, 10)
    for fn in test_starters[:test_limit]:
        steps = bfs_pathway_function_ids(
            fn["id"],
            outgoing,
            functions_by_id,
            fn.get("file_path", "") or "",
        )
        if len(steps) < 2:
            continue
        confidences = [
            e["confidence"]
            for step_id in steps
            for e in outgoing.get(step_id, [])
            if e["to"] in {s for s in steps}
        ]
        path_conf = (
            geometric_mean_confidence(confidences) if confidences else MIN_CONFIDENCE
        )
        path_conf = min(1.0, path_conf)
        proc_id = f"process:{fn['id']}"
        proc = ProcessNode(
            id=proc_id,
            entry_id=fn["id"],
            step_count=len(steps),
            confidence=path_conf,
        )
        _persist_process(
            store, proc, steps, fn, path_conf, functions_by_id,
            min_pathway_steps=2,
        )


def _build_abc_implementor_ids(store: GraphStore) -> set[str]:
    """Return IDs of functions that are concrete implementations of abstract methods.

    A function qualifies when:
    a) Its class has an EXTENDS or IMPLEMENTS edge to another class in the repo, AND
       a function with the same bare name exists on that base class.
    b) OR 3+ classes in 3+ different non-test files each define a method with
       the same bare name — the polymorphic-pattern heuristic.

    These functions receive a scoring boost (``_ABC_IMPL_MULT``) so all concrete
    implementations of a shared interface surface together in the pathway list.
    """
    implementor_ids: set[str] = set()
    try:
        # Find classes that extend/implement another in-repo class, and the
        # method names defined on the base class.
        sub_rows = store.query(
            "MATCH (sub:Class)-[:EXTENDS|IMPLEMENTS]->(base:Class) "
            "RETURN sub.name, base.name"
        )
        if sub_rows:
            # For each (subclass, base) pair, find subclass functions whose
            # name also appears as a function on the base class.
            for sub_name, base_name in sub_rows:
                if not sub_name or not base_name:
                    continue
                try:
                    rows = store.query(
                        "MATCH (fs:Function), (fb:Function) "
                        "WHERE fs.qualified_name STARTS WITH $sub_prefix "
                        "  AND fb.qualified_name STARTS WITH $base_prefix "
                        "  AND fs.name = fb.name "
                        "RETURN fs.id",
                        {"sub_prefix": f"{sub_name}.", "base_prefix": f"{base_name}."},
                    )
                    for row in rows:
                        if row[0]:
                            implementor_ids.add(row[0])
                except Exception:
                    continue

        # Polymorphic-pattern heuristic: 3+ non-test functions sharing the same
        # bare name across 3+ distinct files are almost certainly implementations
        # of a shared interface (strategies, plugins, handlers, etc.).
        try:
            poly_rows = store.query(
                "MATCH (f:Function) "
                "WHERE NOT f.file_path CONTAINS 'test' "
                "WITH f.name AS nm, collect(f.id) AS ids, count(DISTINCT f.file_path) AS fc "
                "WHERE fc >= 3 "
                "UNWIND ids AS fid "
                "RETURN fid"
            )
            for row in poly_rows:
                if row[0]:
                    implementor_ids.add(row[0])
        except Exception:
            pass

    except Exception:
        pass

    return implementor_ids




