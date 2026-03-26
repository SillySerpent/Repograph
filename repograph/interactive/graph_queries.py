"""Shared helpers for the interactive menu — graph queries without Typer/Rich."""
from __future__ import annotations

from typing import Any


def hybrid_search(store: Any, query: str, limit: int = 10) -> list[dict]:
    from repograph.search.hybrid import HybridSearch

    return HybridSearch(store).search(query, limit=limit)


def trace_variable(store: Any, variable_name: str) -> dict:
    """Match MCP tool: variable occurrences + FLOWS_INTO edges."""
    rows = store.query(
        """
        MATCH (v:Variable {name: $name})
        RETURN v.id, v.function_id, v.file_path, v.line_number,
               v.inferred_type, v.is_parameter, v.is_return
        LIMIT 50
        """,
        {"name": variable_name},
    )
    if not rows:
        return {"error": f"Variable '{variable_name}' not found"}

    occurrences = [
        {
            "variable_id": r[0],
            "function_id": r[1],
            "file_path": r[2],
            "line_number": r[3],
            "inferred_type": r[4],
            "is_parameter": r[5],
            "is_return": r[6],
        }
        for r in rows
    ]
    var_ids = {o["variable_id"] for o in occurrences}
    flows = store.get_flows_into_edges()
    relevant = [e for e in flows if e["from"] in var_ids or e["to"] in var_ids]
    return {
        "variable_name": variable_name,
        "occurrences": occurrences,
        "flows": relevant,
    }


def dependents_by_depth(store: Any, symbol: str, depth: int = 3) -> dict:
    """Symbols that call this symbol, grouped by distance (MCP get_dependents)."""
    results = store.search_functions_by_name(symbol, limit=1)
    if not results:
        return {"error": f"Symbol '{symbol}' not found"}

    fn_id = results[0]["id"]
    levels: dict[int, list[dict]] = {}
    visited: set[str] = {fn_id}
    queue: list[tuple[str, int]] = [(fn_id, 0)]

    while queue:
        cur_id, cur_depth = queue.pop(0)
        if cur_depth >= depth:
            continue
        for c in store.get_callers(cur_id):
            if c["id"] not in visited:
                visited.add(c["id"])
                levels.setdefault(cur_depth + 1, []).append(c)
                queue.append((c["id"], cur_depth + 1))

    return {"symbol": symbol, "dependents_by_depth": levels}


def dependencies_by_depth(store: Any, symbol: str, depth: int = 3) -> dict:
    """Symbols this symbol calls (MCP get_dependencies)."""
    results = store.search_functions_by_name(symbol, limit=1)
    if not results:
        return {"error": f"Symbol '{symbol}' not found"}

    fn_id = results[0]["id"]
    levels: dict[int, list[dict]] = {}
    visited: set[str] = {fn_id}
    queue: list[tuple[str, int]] = [(fn_id, 0)]

    while queue:
        cur_id, cur_depth = queue.pop(0)
        if cur_depth >= depth:
            continue
        for c in store.get_callees(cur_id):
            if c["id"] not in visited:
                visited.add(c["id"])
                levels.setdefault(cur_depth + 1, []).append(c)
                queue.append((c["id"], cur_depth + 1))

    return {"symbol": symbol, "dependencies_by_depth": levels}


def repograph_cli_path() -> str:
    """Path to `repograph` CLI (venv next to package, else PATH)."""
    import os
    import shutil

    import repograph

    pkg_root = os.path.dirname(os.path.dirname(repograph.__file__))
    venv_bin = os.path.join(pkg_root, ".venv", "bin", "repograph")
    if os.path.isfile(venv_bin):
        return venv_bin
    w = shutil.which("repograph")
    return w if w else "repograph"
