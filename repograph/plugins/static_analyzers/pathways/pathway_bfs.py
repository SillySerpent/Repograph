# Canonical BFS traversal helpers owned by the pathways plugin.
"""Shared breadth-first pathway traversal over CALLS edges.

Used by Phase 10 and kept consistent with pathway assembly rules (fan-out,
confidence floor, cross-language isolation).
"""
from __future__ import annotations

import os
from collections import deque

# Single source of truth — imported by p10_processes and pathways.assembler
MAX_PATHWAY_STEPS = 25
MAX_FANOUT = 4
MIN_CONFIDENCE = 0.5
MAX_PATHWAY_DEPTH = 15


def language_family(file_path: str) -> str:
    """Coarse language bucket for cross-language pathway filtering."""
    ext = os.path.splitext(file_path or "")[1].lower()
    if ext == ".py":
        return "python"
    if ext in (".js", ".jsx", ".ts", ".tsx"):
        return "web"
    return "other"


def should_skip_cross_language_step(entry_file_path: str, callee_file_path: str) -> bool:
    """True when a BFS step should not cross between Python and JS/TS."""
    ef = language_family(entry_file_path)
    cf = language_family(callee_file_path)
    if ef == "python" and cf == "web":
        return True
    if ef == "web" and cf == "python":
        return True
    return False


def bfs_pathway_function_ids(
    entry_id: str,
    outgoing: dict[str, list[dict]],
    functions_by_id: dict[str, dict],
    entry_file_path: str,
    *,
    max_steps: int = MAX_PATHWAY_STEPS,
    max_fanout: int = MAX_FANOUT,
    max_depth: int = MAX_PATHWAY_DEPTH,
    skip_cross_language: bool = True,
) -> list[str]:
    """BFS from entry_id through CALLS edges; returns ordered function IDs.

    Each ``outgoing[from_id]`` item must include ``to`` and ``confidence`` keys
    (Phase 10 / ``get_all_call_edges`` shape).
    """
    visited: list[str] = []
    seen: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(entry_id, 0)])

    while queue and len(visited) < max_steps:
        func_id, depth = queue.popleft()
        if func_id in seen or depth > max_depth:
            continue
        seen.add(func_id)
        if func_id in functions_by_id:
            visited.append(func_id)

        edges = sorted(
            outgoing.get(func_id, []),
            key=lambda e: -e.get("confidence", 0),
        )[:max_fanout]

        for e in edges:
            tgt = e.get("to")
            if not tgt or tgt in seen:
                continue
            callee = functions_by_id.get(tgt, {})
            callee_fp = callee.get("file_path", "") or ""
            if skip_cross_language and should_skip_cross_language_step(
                entry_file_path, callee_fp
            ):
                continue
            queue.append((tgt, depth + 1))

    return visited


def build_outgoing_index(call_edges: list[dict]) -> dict[str, list[dict]]:
    """Index call edges by caller function id (Phase 10 shape)."""
    outgoing: dict[str, list[dict]] = {}
    for e in call_edges:
        outgoing.setdefault(e["from"], []).append(e)
    return outgoing
