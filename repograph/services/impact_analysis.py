"""Change impact analysis: given a set of changed file paths, compute which functions
and their transitive callers are most likely to be affected.

The analysis walks the CALLS graph (and MAKES_HTTP_CALL edges for cross-language impact)
up to ``max_hops`` steps from each directly-changed function, scoring each reached
function by its ``entry_score`` field multiplied by a decay factor that diminishes
with hop distance.

Usage (programmatic)::

    from repograph.services.impact_analysis import compute_impact
    results = compute_impact(store, changed_paths=["app/models/user.py"])

Usage (CLI)::

    repograph impact --diff HEAD~1
    repograph impact --files app/models/user.py app/auth.py
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class ImpactedFunction:
    """A function affected by a set of file changes."""

    fn_id: str
    qualified_name: str
    file_path: str
    hop: int
    """0 = directly in a changed file; N = N hops away via call edges."""
    impact_score: float
    """entry_score × hop_decay — higher is more critical."""
    via_http: bool = False
    """True when this function was reached via a MAKES_HTTP_CALL edge."""
    edge_path: list[str] = field(default_factory=list)
    """Function IDs from the changed function to this one (inclusive)."""


_HOP_DECAY = 0.7
"""Confidence multiplier applied per hop distance."""


def compute_impact(
    store,
    *,
    changed_paths: list[str],
    max_hops: int = 5,
) -> list[ImpactedFunction]:
    """Return a ranked list of functions impacted by changes in ``changed_paths``.

    Parameters
    ----------
    store:
        Open ``GraphStore`` instance.
    changed_paths:
        Repo-relative file paths that changed (e.g. from ``git diff --name-only``).
    max_hops:
        Maximum number of CALLS/MAKES_HTTP_CALL hops to traverse.  Defaults to 5.
        Set to 1 for direct-callers only.

    Returns
    -------
    List of :class:`ImpactedFunction` objects sorted by *descending* impact_score.
    The list is deduplicated — each function appears once at its shortest hop distance.
    """
    if not changed_paths:
        return []

    # ── Step 1: find functions directly in changed files ────────────────────
    direct_fns: list[dict] = []
    for path in changed_paths:
        try:
            rows = store.query(
                "MATCH (f:Function) WHERE f.file_path = $fp "
                "RETURN f.id, f.qualified_name, f.file_path, f.entry_score",
                {"fp": path},
            )
            for r in rows:
                direct_fns.append({
                    "id": r[0],
                    "qualified_name": r[1] or "",
                    "file_path": r[2] or "",
                    "entry_score": float(r[3] or 0.0),
                })
        except Exception:
            continue

    if not direct_fns:
        return []

    # ── Step 2: BFS over callers + HTTP callers ──────────────────────────────
    # Queue entries: (fn_id, hop, via_http, path_so_far, accumulated_score)
    visited: dict[str, tuple[int, float, bool, list[str]]] = {}
    # fn_id -> (hop, score, via_http, edge_path)

    queue: deque[tuple[str, int, bool, list[str], float]] = deque()

    # Seed with direct functions (hop=0)
    for fn in direct_fns:
        fn_id = fn["id"]
        score = max(fn["entry_score"], 0.01)  # floor so unreachable fns get a signal
        if fn_id not in visited:
            visited[fn_id] = (0, score, False, [fn_id])
            queue.append((fn_id, 0, False, [fn_id], score))

    while queue:
        fn_id, hop, via_http, path_so_far, score = queue.popleft()

        if hop >= max_hops:
            continue

        # Callers via CALLS
        try:
            callers = store.get_callers(fn_id)
        except Exception:
            callers = []

        for c in callers:
            cid = c["id"]
            c_score = score * _HOP_DECAY * float(c.get("confidence", 1.0))
            new_hop = hop + 1
            new_path = path_so_far + [cid]
            if cid not in visited or visited[cid][0] > new_hop:
                visited[cid] = (new_hop, c_score, False, new_path)
                queue.append((cid, new_hop, False, new_path, c_score))

        # Cross-language callers via MAKES_HTTP_CALL (reverse: who calls fn_id via HTTP?)
        try:
            http_rows = store.query(
                "MATCH (caller:Function)-[e:MAKES_HTTP_CALL]->(f:Function {id: $id}) "
                "RETURN caller.id, e.confidence",
                {"id": fn_id},
            )
        except Exception:
            http_rows = []

        for r in http_rows:
            cid = r[0]
            if not cid:
                continue
            c_score = score * _HOP_DECAY * float(r[1] or 0.8)
            new_hop = hop + 1
            new_path = path_so_far + [cid]
            if cid not in visited or visited[cid][0] > new_hop:
                visited[cid] = (new_hop, c_score, True, new_path)
                queue.append((cid, new_hop, True, new_path, c_score))

    # ── Step 3: resolve qualified_name / file_path for all visited IDs ───────
    all_ids = list(visited.keys())
    id_to_meta: dict[str, dict] = {}
    chunk_size = 48
    for i in range(0, len(all_ids), chunk_size):
        chunk = all_ids[i : i + chunk_size]
        try:
            rows = store.query(
                "MATCH (f:Function) WHERE f.id IN $ids "
                "RETURN f.id, f.qualified_name, f.file_path, f.entry_score",
                {"ids": chunk},
            )
            for r in rows:
                id_to_meta[r[0]] = {
                    "qualified_name": r[1] or "",
                    "file_path": r[2] or "",
                    "entry_score": float(r[3] or 0.0),
                }
        except Exception:
            continue

    # ── Step 4: assemble results ─────────────────────────────────────────────
    results: list[ImpactedFunction] = []
    for fn_id, (hop, score, via_http, edge_path) in visited.items():
        meta = id_to_meta.get(fn_id, {})
        results.append(ImpactedFunction(
            fn_id=fn_id,
            qualified_name=meta.get("qualified_name", fn_id),
            file_path=meta.get("file_path", ""),
            hop=hop,
            impact_score=score,
            via_http=via_http,
            edge_path=edge_path,
        ))

    results.sort(key=lambda x: (-x.impact_score, x.hop, x.qualified_name))
    return results


def format_impact_table(results: list[ImpactedFunction]) -> str:
    """Return a plain-text table of impacted functions for CLI display."""
    if not results:
        return "No impacted functions found."
    lines = [
        f"{'Score':>6}  {'Hop':>3}  {'HTTP':>4}  Qualified Name",
        "-" * 72,
    ]
    for r in results[:50]:  # cap display at 50
        http_flag = "  ✓ " if r.via_http else "    "
        lines.append(
            f"{r.impact_score:6.3f}  {r.hop:>3}  {http_flag}  {r.qualified_name}"
            f"  [{r.file_path}]"
        )
    if len(results) > 50:
        lines.append(f"  ... and {len(results) - 50} more")
    return "\n".join(lines)
