"""Phase 3b — Framework Tags: persist framework adapter outputs to the graph.

This phase runs immediately after p03_parse.  It iterates the plugin_artifacts
collected by each framework adapter during parsing and writes layer/role/HTTP
fields onto the relevant Function nodes via store.update_function_layer_role().

Keeping this in a separate phase (not inline in p03) preserves p03's clean
single responsibility (parse → persist nodes) and allows framework tagging to
be skipped or replaced independently.
"""
from __future__ import annotations

from repograph.core.models import ParsedFile
from repograph.graph_store.store import GraphStore
from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="pipeline")


def run(parsed: list[ParsedFile], store: GraphStore) -> None:
    """Write layer/role/http fields for every route function found by framework adapters.

    Iterates plugin_artifacts on each ParsedFile looking for the standard
    adapter output schema keys (``route_functions``, ``page_components``).
    Unknown plugin artifact formats are logged and skipped.
    """
    tagged = 0
    for pf in parsed:
        for plugin_id, artifact in pf.plugin_artifacts.items():
            if not isinstance(artifact, dict):
                continue

            route_functions: list[dict] = artifact.get("route_functions") or []
            for entry in route_functions:
                if not isinstance(entry, dict):
                    _logger.debug(
                        "p03b: unexpected route_functions entry format — skipping",
                        plugin_id=plugin_id,
                        entry=str(entry),
                    )
                    continue
                qn: str = entry.get("qualified_name") or ""
                http_method: str = entry.get("http_method") or ""
                route_path: str = entry.get("route_path") or ""
                if not qn:
                    continue
                # Look up the function node by qualified_name within this file.
                fn_id = _resolve_fn_id(pf, qn, store)
                if fn_id is None:
                    _logger.debug(
                        "p03b: could not resolve function id for qualified_name",
                        plugin_id=plugin_id,
                        qualified_name=qn,
                        file_path=pf.file_record.path if pf.file_record else "",
                    )
                    continue
                store.update_function_layer_role(
                    fn_id,
                    layer="api",
                    role="handler",
                    http_method=http_method,
                    route_path=route_path,
                )
                tagged += 1

            # Mark page/layout components as ui layer.
            page_components: list[str] = artifact.get("page_components") or []
            if page_components and pf.file_record:
                # Page components in JS/TS are file-level — tag the file's layer.
                try:
                    store.update_file_layer(pf.file_record.id, layer="ui")
                except Exception:
                    _logger.debug(
                        "p03b: could not update file layer",
                        plugin_id=plugin_id,
                        file_id=pf.file_record.id,
                    )

    _logger.debug("p03b: tagged functions via framework adapters", count=tagged)


def _resolve_fn_id(pf: ParsedFile, qualified_name: str, store: GraphStore) -> str | None:
    """Return the node ID for a function by qualified_name within the parsed file.

    First checks the in-memory parsed function list (fast, no DB query).
    Falls back to a DB query if not found in memory (e.g., when running on
    an incremental reparse where pf.functions may be empty).
    """
    for fn in pf.functions:
        if fn.qualified_name == qualified_name:
            return fn.id

    # Fallback: query the store.
    if pf.file_record:
        rows = store.query(
            "MATCH (f:Function {qualified_name: $qn, file_path: $fp}) RETURN f.id LIMIT 1",
            {"qn": qualified_name, "fp": pf.file_record.path},
        )
        if rows and rows[0][0]:
            return str(rows[0][0])
    return None
