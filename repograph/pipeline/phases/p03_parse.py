"""Phase 3 — Parse: run tree-sitter parsers on all discovered files.

Parsing is split into two phases:
  1. **Parallel parse** — each file is parsed by its language parser using
     `ThreadPoolExecutor`.  Each thread has its own tree-sitter `ts.Parser`
     instance (via thread-local storage in `repograph.parsing.base`).  The
     only shared state during this phase is the read-only plugin registry and
     the per-file ParsedFile objects that are created fresh per call.

  2. **Serial store write** — after all files are parsed, the results are
     written to the graph store and symbol table in the main thread.  This
     avoids concurrent KuzuDB access and keeps symbol-table updates race-free.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from repograph.core.models import FileRecord, ParsedFile, NodeID
from repograph.graph_store.store import GraphStore
from repograph.observability import get_logger, make_thread_context
from repograph.parsing.symbol_table import SymbolTable
from repograph.plugins.parsers.registry import parse_file

_logger = get_logger(__name__, subsystem="pipeline")

# Threshold below which the ThreadPoolExecutor overhead is not worthwhile.
_PARALLEL_THRESHOLD = 5
# Cap to avoid spawning more threads than practical.
_MAX_WORKERS = 8


def run(
    files: list[FileRecord],
    store: GraphStore,
    symbol_table: SymbolTable,
) -> list[ParsedFile]:
    """Parse every file, persist all nodes to the graph store,
    and populate the symbol table for cross-file resolution.
    Returns the list of ParsedFile objects for downstream phases.
    """
    file_paths = [fr.path for fr in files]
    store.preload_runtime_overlay_for_file_paths(file_paths)
    try:
        # Phase 1: parse all files (may run in parallel)
        parsed_in_order = _parse_files_parallel(files)

        # Phase 2: serial write — all store and symbol-table mutations happen here
        parsed: list[ParsedFile] = []
        for pf in parsed_in_order:
            _write_to_store(pf, store, symbol_table, parsed)
    finally:
        store.clear_runtime_overlay_prefetch()
    return parsed


# ---------------------------------------------------------------------------
# Phase 1: parallel parse
# ---------------------------------------------------------------------------


def _parse_files_parallel(files: list[FileRecord]) -> list[ParsedFile]:
    """Parse files concurrently.  Returns results in the same order as `files`."""
    if not files:
        return []

    n = len(files)
    workers = min(os.cpu_count() or 1, n, _MAX_WORKERS)

    if workers <= 1 or n < _PARALLEL_THRESHOLD:
        # Not worth the thread-pool overhead for small batches — but still guard per-file.
        results_seq: list[ParsedFile] = []
        for fr in files:
            try:
                results_seq.append(_parse_one_file(fr))
            except Exception as exc:
                _logger.warning("p03: parse failed", path=fr.path, exc_msg=str(exc))
                results_seq.append(ParsedFile(file_record=fr))
        return results_seq

    results: list[ParsedFile | None] = [None] * n
    with ThreadPoolExecutor(max_workers=workers) as ex:
        future_to_idx = {
            ex.submit(make_thread_context().run, _parse_one_file, fr): i
            for i, fr in enumerate(files)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            exc = future.exception()
            if exc:
                _logger.warning(
                    "p03: parse failed", path=files[idx].path, exc_msg=str(exc)
                )
                results[idx] = ParsedFile(file_record=files[idx])
            else:
                results[idx] = future.result()
    # Safety: fill any None slots (should not happen in practice)
    return [r if r is not None else ParsedFile(file_record=files[i])
            for i, r in enumerate(results)]


def _parse_one_file(fr: FileRecord) -> ParsedFile:
    """Parse a single file.  Safe to call from worker threads."""
    return parse_file(fr)


# ---------------------------------------------------------------------------
# Phase 2: serial write
# ---------------------------------------------------------------------------


def _write_to_store(
    pf: ParsedFile,
    store: GraphStore,
    symbol_table: SymbolTable,
    parsed: list[ParsedFile],
) -> None:
    """Persist one ParsedFile's data to the store and symbol table."""
    parsed.append(pf)
    fr = pf.file_record

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

    file_id = NodeID.make_file_id(fr.path)

    # Persist functions (without HAS_METHOD yet — classes don't exist in DB yet)
    store.batch_upsert_functions(pf.functions)
    for fn in pf.functions:
        store.insert_defines_edge(file_id, fn.id)
        symbol_table.add_function(fn)

    # Persist classes — MUST happen before HAS_METHOD edges
    store.batch_upsert_classes(pf.classes)
    for cls in pf.classes:
        store.insert_defines_class_edge(file_id, cls.id)
        symbol_table.add_class(cls)

    # Wire HAS_METHOD now that all Class nodes for this file are in the DB
    for fn in pf.functions:
        if fn.is_method and "." in fn.qualified_name:
            class_qname = fn.qualified_name.rsplit(".", 1)[0]
            class_id = NodeID.make_class_id(fn.file_path, class_qname)
            store.insert_has_method_edge(class_id, fn.id)

    # Persist imports
    for imp in pf.imports:
        store.upsert_import(imp)

    # Persist variables
    for var in pf.variables:
        store.upsert_variable(var)
