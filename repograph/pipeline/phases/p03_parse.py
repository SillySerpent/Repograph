"""Phase 3 — Parse: run tree-sitter parsers on all discovered files."""
from __future__ import annotations

from repograph.core.models import FileRecord, ParsedFile, NodeID
from repograph.graph_store.store import GraphStore
from repograph.parsing.symbol_table import SymbolTable
from repograph.plugins.parsers.registry import parse_file


def run(
    files: list[FileRecord],
    store: GraphStore,
    symbol_table: SymbolTable,
) -> list[ParsedFile]:
    """
    Parse every file, persist all nodes to the graph store,
    and populate the symbol table for cross-file resolution.
    Returns the list of ParsedFile objects for downstream phases.
    """
    parsed: list[ParsedFile] = []
    file_paths = [fr.path for fr in files]
    store.preload_runtime_overlay_for_file_paths(file_paths)
    try:
        for fr in files:
            _p03_parse_one_file(fr, store, symbol_table, parsed)
    finally:
        store.clear_runtime_overlay_prefetch()
    return parsed


def _p03_parse_one_file(
    fr: FileRecord,
    store: GraphStore,
    symbol_table: SymbolTable,
    parsed: list[ParsedFile],
) -> None:
    pf = parse_file(fr)
    parsed.append(pf)

    # Persist File node
    from repograph.core.models import FileNode
    from datetime import datetime, timezone
    file_node = FileNode(
        id=NodeID.make_file_id(fr.path),
        path=fr.path,
        abs_path=fr.abs_path,
        name=fr.name,
        extension=fr.extension,
        language=fr.language,
        size_bytes=fr.size_bytes,
        line_count=fr.line_count,
        source_hash=fr.source_hash,
        is_test=fr.is_test,
        is_config=fr.is_config,
        indexed_at=datetime.now(timezone.utc),
    )
    store.upsert_file(file_node)

    # Persist functions (without HAS_METHOD yet — classes don't exist in DB yet)
    file_id = NodeID.make_file_id(fr.path)
    for fn in pf.functions:
        store.upsert_function(fn)
        store.insert_defines_edge(file_id, fn.id)
        symbol_table.add_function(fn)

    # Persist classes — MUST happen before HAS_METHOD edges so the MATCH
    # in insert_has_method_edge finds the Class node.
    for cls in pf.classes:
        store.upsert_class(cls)
        store.insert_defines_class_edge(file_id, cls.id)
        symbol_table.add_class(cls)

    # Wire HAS_METHOD now that all Class nodes for this file are in the DB.
    # Iterating functions again is O(n) and avoids a two-pass architecture.
    for fn in pf.functions:
        if fn.is_method and "." in fn.qualified_name:
            # Everything before the last dot is the class qualified_name
            class_qname = fn.qualified_name.rsplit(".", 1)[0]
            class_id = NodeID.make_class_id(fn.file_path, class_qname)
            store.insert_has_method_edge(class_id, fn.id)

    # Persist imports
    for imp in pf.imports:
        store.upsert_import(imp)

    # Persist variables
    for var in pf.variables:
        store.upsert_variable(var)
