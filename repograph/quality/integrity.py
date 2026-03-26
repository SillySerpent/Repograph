"""Post-sync structural integrity checks (Q1–Q6) over an open GraphStore.

These checks do not mutate the database. They validate referential consistency
and stats alignment with :meth:`GraphStore.get_stats`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from repograph.quality.types import InvariantResult, Violation

if TYPE_CHECKING:
    from repograph.graph_store.store import GraphStore


def _safe_count(store: Any, cypher: str, params: dict | None = None) -> int | None:
    try:
        rows = store.query(cypher, params or {})
        if not rows:
            return 0
        v = rows[0][0]
        return int(v) if v is not None else 0
    except Exception:
        return None


def _check_q1_calls_endpoints(store: Any) -> list[Violation]:
    """Q1: Every CALLS relationship has both endpoints as Function nodes."""
    out: list[Violation] = []
    typed = _safe_count(
        store,
        "MATCH (a:Function)-[r:CALLS]->(b:Function) RETURN count(*)",
    )
    total = _safe_count(store, "MATCH ()-[r:CALLS]->() RETURN count(*)")
    if typed is None or total is None:
        out.append(
            Violation(
                "Q1",
                "Could not count CALLS edges (query failed).",
                detail={"typed": typed, "total": total},
            )
        )
        return out
    if typed != total:
        out.append(
            Violation(
                "Q1",
                "CALLS edge count with Function endpoints does not match total CALLS count.",
                detail={"function_endpoints": typed, "all_calls_rels": total},
            )
        )
    return out


def _check_q2_structural_edges(store: Any) -> list[Violation]:
    """Q2: DEFINES, DEFINES_CLASS, HAS_METHOD use existing File/Function/Class nodes."""
    out: list[Violation] = []
    checks = [
        (
            "DEFINES",
            "MATCH (a:File)-[r:DEFINES]->(b:Function) RETURN count(*)",
            "MATCH ()-[r:DEFINES]->() RETURN count(*)",
        ),
        (
            "DEFINES_CLASS",
            "MATCH (a:File)-[r:DEFINES_CLASS]->(b:Class) RETURN count(*)",
            "MATCH ()-[r:DEFINES_CLASS]->() RETURN count(*)",
        ),
        (
            "HAS_METHOD",
            "MATCH (a:Class)-[r:HAS_METHOD]->(b:Function) RETURN count(*)",
            "MATCH ()-[r:HAS_METHOD]->() RETURN count(*)",
        ),
    ]
    for name, typed_cypher, total_cypher in checks:
        typed = _safe_count(store, typed_cypher)
        total = _safe_count(store, total_cypher)
        if typed is None or total is None:
            out.append(
                Violation(
                    "Q2",
                    f"Could not count {name} edges.",
                    detail={"rel": name},
                )
            )
            continue
        if typed != total:
            out.append(
                Violation(
                    "Q2",
                    f"{name} typed edge count does not match total {name} relationships.",
                    detail={"rel": name, "typed": typed, "total": total},
                )
            )
    return out


def _check_q3_imports(store: Any) -> list[Violation]:
    """Q3: IMPORTS relationships connect two File nodes."""
    out: list[Violation] = []
    typed = _safe_count(
        store,
        "MATCH (a:File)-[r:IMPORTS]->(b:File) RETURN count(*)",
    )
    total = _safe_count(store, "MATCH ()-[r:IMPORTS]->() RETURN count(*)")
    if typed is None or total is None:
        out.append(Violation("Q3", "Could not count IMPORTS edges."))
        return out
    if typed != total:
        out.append(
            Violation(
                "Q3",
                "IMPORTS edge count with File endpoints does not match total IMPORTS count.",
                detail={"file_endpoints": typed, "all_imports_rels": total},
            )
        )
    return out


def _check_q4_topology_edges(store: Any) -> list[Violation]:
    """Q4: Community/pathway/process topology rels reference existing typed nodes."""
    out: list[Violation] = []
    checks = [
        (
            "MEMBER_OF",
            "MATCH (a:Function)-[r:MEMBER_OF]->(b:Community) RETURN count(*)",
            "MATCH ()-[r:MEMBER_OF]->() RETURN count(*)",
        ),
        (
            "CLASS_IN",
            "MATCH (a:Class)-[r:CLASS_IN]->(b:Community) RETURN count(*)",
            "MATCH ()-[r:CLASS_IN]->() RETURN count(*)",
        ),
        (
            "STEP_IN_PATHWAY",
            "MATCH (a:Function)-[r:STEP_IN_PATHWAY]->(b:Pathway) RETURN count(*)",
            "MATCH ()-[r:STEP_IN_PATHWAY]->() RETURN count(*)",
        ),
        (
            "STEP_IN_PROCESS",
            "MATCH (a:Function)-[r:STEP_IN_PROCESS]->(b:Process) RETURN count(*)",
            "MATCH ()-[r:STEP_IN_PROCESS]->() RETURN count(*)",
        ),
        (
            "VAR_IN_PATHWAY",
            "MATCH (a:Variable)-[r:VAR_IN_PATHWAY]->(b:Pathway) RETURN count(*)",
            "MATCH ()-[r:VAR_IN_PATHWAY]->() RETURN count(*)",
        ),
    ]
    for name, typed_cypher, total_cypher in checks:
        typed = _safe_count(store, typed_cypher)
        total = _safe_count(store, total_cypher)
        if typed is None or total is None:
            out.append(
                Violation(
                    "Q4",
                    f"Could not count {name} edges.",
                    detail={"rel": name},
                )
            )
            continue
        if typed != total:
            out.append(
                Violation(
                    "Q4",
                    f"{name} typed edge count does not match total {name} relationships.",
                    detail={"rel": name, "typed": typed, "total": total},
                )
            )
    return out


def _check_q5_function_id_unique(store: Any) -> list[Violation]:
    """Q5: No duplicate Function primary keys (ids)."""
    out: list[Violation] = []
    try:
        dups = store.query(
            "MATCH (f:Function) WITH f.id AS id, count(*) AS c WHERE c > 1 RETURN id, c"
        )
    except Exception as exc:
        return [
            Violation(
                "Q5",
                "Could not verify Function id uniqueness.",
                detail={"error": str(exc)},
            )
        ]
    if dups:
        out.append(
            Violation(
                "Q5",
                "Duplicate Function node ids detected.",
                detail={"duplicates": [[r[0], r[1]] for r in dups]},
            )
        )
    return out


def _check_q6_stats_consistency(store: Any) -> list[Violation]:
    """Q6: ``get_stats()`` matches independent COUNT queries (same rules as get_stats)."""
    out: list[Violation] = []
    try:
        stats = store.get_stats()
    except Exception as exc:
        out.append(
            Violation(
                "Q6",
                "get_stats() failed.",
                detail={"error": str(exc)},
            )
        )
        return out

    label_map = {
        "File": "files",
        "Class": "classes",
        "Variable": "variables",
        "Import": "imports",
        "Pathway": "pathways",
        "Community": "communities",
    }
    for label, key in label_map.items():
        n = _safe_count(store, f"MATCH (n:{label}) RETURN count(n)")
        if n is None:
            out.append(
                Violation(
                    "Q6",
                    f"COUNT failed for {label}.",
                    detail={"label": label, "key": key},
                )
            )
            continue
        if stats.get(key) != n:
            out.append(
                Violation(
                    "Q6",
                    f"get_stats()['{key}'] does not match MATCH count for {label}.",
                    detail={"key": key, "get_stats": stats.get(key), "count": n},
                )
            )

    fn_n = _safe_count(
        store,
        "MATCH (f:Function) WHERE f.is_module_caller IS NULL OR f.is_module_caller = false "
        "RETURN count(f)",
    )
    if fn_n is None:
        out.append(Violation("Q6", "Function count query failed."))
    elif stats.get("functions") != fn_n:
        out.append(
            Violation(
                "Q6",
                "get_stats()['functions'] does not match filtered Function count.",
                detail={"get_stats": stats.get("functions"), "count": fn_n},
            )
        )
    return out


def run_sync_invariants(store: "GraphStore") -> InvariantResult:
    """Run structural checks Q1–Q6. Does not modify the store."""
    violations: list[Violation] = []
    violations.extend(_check_q1_calls_endpoints(store))
    violations.extend(_check_q2_structural_edges(store))
    violations.extend(_check_q3_imports(store))
    violations.extend(_check_q4_topology_edges(store))
    violations.extend(_check_q5_function_id_unique(store))
    violations.extend(_check_q6_stats_consistency(store))
    return InvariantResult(violations=violations)
