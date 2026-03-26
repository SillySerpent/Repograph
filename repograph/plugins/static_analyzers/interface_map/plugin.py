"""Interface / implementation map from inheritance edges (IMP-02)."""
from __future__ import annotations

from repograph.graph_store.store import GraphStore


def get_interface_map(store: GraphStore) -> list[dict]:
    """Return EXTENDS/IMPLEMENTS pairs grouped by base class name.

    Args:
        store: Open graph store.

    Returns:
        List of ``{interface, implementations: [...]}`` dicts.
    """
    try:
        rows = store.query(
            """
            MATCH (sub:Class)-[:EXTENDS|IMPLEMENTS]->(base:Class)
            RETURN base.name, base.qualified_name, base.file_path,
                   sub.name, sub.qualified_name, sub.file_path
            """
        )
    except Exception:
        return []

    by_base: dict[str, dict] = {}
    for r in rows:
        bname = r[0] or ""
        if bname not in by_base:
            by_base[bname] = {
                "interface": bname,
                "interface_file": r[2] or "",
                "implementations": [],
            }
        by_base[bname]["implementations"].append({
            "class": r[3],
            "qualified_name": r[4],
            "file_path": r[5],
        })
    return sorted(by_base.values(), key=lambda x: -len(x["implementations"]))
