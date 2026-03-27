"""Impact graph exporter plugin (Block I3).

Generates a Mermaid or Graphviz DOT diagram of the call graph centred on a
given entry point.  Edge weights are proportional to call confidence.  The
output is intended for CI PR comments or standalone documentation.

The plugin implements ``ExporterPlugin`` and is invoked via ``on_export``.
It can also be called standalone via the helper functions exported from this
module.
"""
from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import ExporterPlugin, PluginManifest


class ImpactGraphExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.impact_graph",
        name="Impact graph exporter",
        kind="exporter",
        description=(
            "Confidence-weighted call graph diagram (Mermaid or DOT) "
            "centred on a given entry point."
        ),
        requires=(),
        produces=("artifacts.impact_graph",),
        hooks=("on_export",),
        order=130,
    )

    def export(self, **kwargs: Any) -> dict[str, Any]:
        store = kwargs.get("store")
        entry_point: str | None = kwargs.get("entry_point")
        fmt: str = kwargs.get("format", "mermaid")  # "mermaid" | "dot"
        max_depth: int = int(kwargs.get("max_depth", 4))
        min_confidence: float = float(kwargs.get("min_confidence", 0.5))

        if store is None or not entry_point:
            return {"diagram": "", "format": fmt, "node_count": 0, "edge_count": 0}

        diagram, n_nodes, n_edges = render_impact_graph(
            store,
            entry_point=entry_point,
            fmt=fmt,
            max_depth=max_depth,
            min_confidence=min_confidence,
        )
        return {
            "diagram": diagram,
            "format": fmt,
            "node_count": n_nodes,
            "edge_count": n_edges,
        }


def build_plugin() -> ImpactGraphExporterPlugin:
    return ImpactGraphExporterPlugin()


# ---------------------------------------------------------------------------
# Standalone rendering helpers
# ---------------------------------------------------------------------------

_WEIGHT_THICK = 0.8   # confidence ≥ 0.8 → thick/bold edge
_WEIGHT_DASHED = 0.5  # confidence < 0.5 → dashed edge (should be filtered by min_confidence)


def render_impact_graph(
    store,
    *,
    entry_point: str,
    fmt: str = "mermaid",
    max_depth: int = 4,
    min_confidence: float = 0.5,
) -> tuple[str, int, int]:
    """Render a call graph centred on ``entry_point``.

    Parameters
    ----------
    store:
        Open ``GraphStore`` instance.
    entry_point:
        Qualified name or function ID of the root function.
    fmt:
        ``"mermaid"`` (default) or ``"dot"``.
    max_depth:
        Maximum number of CALLS hops to follow.
    min_confidence:
        Edges with confidence below this threshold are omitted.

    Returns
    -------
    (diagram_str, node_count, edge_count)
    """
    # Resolve entry point to a function ID
    root_fn = _resolve_entry(store, entry_point)
    if root_fn is None:
        return ("", 0, 0)

    # BFS to collect nodes and edges
    nodes: dict[str, dict] = {}  # fn_id -> fn info
    edges: list[tuple[str, str, float]] = []  # (from_id, to_id, confidence)
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(root_fn["id"], 0)]

    while queue:
        fn_id, depth = queue.pop(0)
        if fn_id in visited or depth > max_depth:
            continue
        visited.add(fn_id)

        fn = _get_fn(store, fn_id)
        if fn:
            nodes[fn_id] = fn

        if depth < max_depth:
            try:
                callees = store.get_callees(fn_id)
            except Exception:
                callees = []
            for c in callees:
                conf = float(c.get("confidence", 1.0))
                if conf < min_confidence:
                    continue
                edges.append((fn_id, c["id"], conf))
                if c["id"] not in visited:
                    queue.append((c["id"], depth + 1))

    if fmt == "dot":
        diagram = _render_dot(nodes, edges, root_fn["id"])
    else:
        diagram = _render_mermaid(nodes, edges, root_fn["id"])

    return (diagram, len(nodes), len(edges))


def _resolve_entry(store, entry_point: str) -> dict | None:
    """Find a function by ID or qualified name."""
    # Try exact ID first
    try:
        rows = store.query(
            "MATCH (f:Function {id: $id}) RETURN f.id, f.qualified_name, f.file_path",
            {"id": entry_point},
        )
        if rows:
            return {"id": rows[0][0], "qualified_name": rows[0][1], "file_path": rows[0][2]}
    except Exception:
        pass

    # Try qualified name search
    try:
        results = store.search_functions_by_name(entry_point, limit=1)
        if results:
            r = results[0]
            return {"id": r["id"], "qualified_name": r.get("qualified_name", ""), "file_path": r.get("file_path", "")}
    except Exception:
        pass

    return None


def _get_fn(store, fn_id: str) -> dict | None:
    try:
        rows = store.query(
            "MATCH (f:Function {id: $id}) RETURN f.id, f.qualified_name, f.file_path",
            {"id": fn_id},
        )
        if rows:
            return {"id": rows[0][0], "qualified_name": rows[0][1] or fn_id, "file_path": rows[0][2] or ""}
    except Exception:
        pass
    return None


def _safe_label(fn: dict) -> str:
    """Short label for diagram nodes."""
    qname = fn.get("qualified_name") or fn.get("id", "?")
    # Use only the last two name segments to keep diagrams readable
    parts = qname.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else qname


def _node_id(fn_id: str) -> str:
    """Sanitise a function ID for use as a Mermaid/DOT node identifier."""
    return fn_id.replace(":", "_").replace("/", "_").replace(".", "_").replace("-", "_")


def _render_mermaid(
    nodes: dict[str, dict],
    edges: list[tuple[str, str, float]],
    root_id: str,
) -> str:
    lines = ["flowchart LR"]

    # Node declarations
    for fn_id, fn in nodes.items():
        nid = _node_id(fn_id)
        label = _safe_label(fn)
        if fn_id == root_id:
            lines.append(f'    {nid}["{label}"]:::root')
        else:
            lines.append(f'    {nid}["{label}"]')

    # Edge declarations
    for from_id, to_id, conf in edges:
        from_nid = _node_id(from_id)
        to_nid = _node_id(to_id)
        if conf >= _WEIGHT_THICK:
            lines.append(f"    {from_nid} ==> {to_nid}")
        else:
            lines.append(f"    {from_nid} --> {to_nid}")

    # Style root node
    lines.append("    classDef root fill:#f96,stroke:#c60,color:#000")

    return "\n".join(lines)


def _render_dot(
    nodes: dict[str, dict],
    edges: list[tuple[str, str, float]],
    root_id: str,
) -> str:
    lines = [
        "digraph impact {",
        '    rankdir=LR;',
        '    node [shape=box, fontname="monospace", fontsize=10];',
    ]

    # Node declarations
    for fn_id, fn in nodes.items():
        nid = _node_id(fn_id)
        label = _safe_label(fn).replace('"', '\\"')
        if fn_id == root_id:
            lines.append(f'    {nid} [label="{label}", style=filled, fillcolor="#ff9966"];')
        else:
            lines.append(f'    {nid} [label="{label}"];')

    # Edge declarations
    for from_id, to_id, conf in edges:
        from_nid = _node_id(from_id)
        to_nid = _node_id(to_id)
        width = max(1, int(conf * 3))  # 1–3 pen width
        style = "bold" if conf >= _WEIGHT_THICK else "solid"
        lines.append(
            f'    {from_nid} -> {to_nid} '
            f'[penwidth={width}, style={style}, label="{conf:.2f}"];'
        )

    lines.append("}")
    return "\n".join(lines)
