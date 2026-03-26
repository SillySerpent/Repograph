"""Phase 6 — Heritage: resolve class inheritance, create EXTENDS edges."""
from __future__ import annotations

from repograph.core.models import ParsedFile, ExtendsEdge, ImplementsEdge, NodeID
from repograph.core.confidence import CONF_HERITAGE_DIRECT, CONF_HERITAGE_FUZZY
from repograph.graph_store.store import GraphStore
from repograph.parsing.symbol_table import SymbolTable

# Python stdlib bases that are always external — skip graph edges for these
_STDLIB_BASES = frozenset({
    "object", "Exception", "BaseException", "ValueError", "TypeError",
    "RuntimeError", "OSError", "IOError", "KeyError", "IndexError",
    "AttributeError", "NotImplementedError", "StopIteration",
    "GeneratorExit", "SystemExit", "KeyboardInterrupt",
})

# Bases that signal interface/protocol conformance → IMPLEMENTS edge
_PROTOCOL_BASES = frozenset({
    "ABC", "Protocol", "ABCMeta",
})


def run(
    parsed_files: list[ParsedFile],
    store: GraphStore,
    symbol_table: SymbolTable,
) -> None:
    """
    For each class with base classes, resolve them and create EXTENDS or IMPLEMENTS edges.
    Pure stdlib bases (object, Exception, etc.) are skipped.
    Protocol/ABC bases create IMPLEMENTS edges where the base is resolvable in-repo,
    or simply mark the class without an edge when the base is stdlib only.
    """
    file_imports: dict[str, list] = {
        pf.file_record.path: pf.imports for pf in parsed_files
    }

    for pf in parsed_files:
        imports = file_imports.get(pf.file_record.path, [])

        for cls in pf.classes:
            for base_name in cls.base_names:
                if base_name in _STDLIB_BASES:
                    continue  # pure stdlib — no graph edge needed

                is_protocol_base = base_name in _PROTOCOL_BASES

                base_id, confidence = _resolve_base(
                    base_name, cls.file_path, symbol_table, imports
                )

                if base_id:
                    if is_protocol_base:
                        # Protocol/ABC conformance → IMPLEMENTS edge
                        edge = ImplementsEdge(
                            from_class_id=cls.id,
                            to_class_id=base_id,
                            confidence=confidence,
                        )
                        try:
                            store.insert_implements_edge(edge)
                        except Exception:
                            pass
                    else:
                        # Normal inheritance → EXTENDS edge
                        edge = ExtendsEdge(
                            from_class_id=cls.id,
                            to_class_id=base_id,
                            confidence=confidence,
                        )
                        try:
                            store.insert_extends_edge(edge)
                        except Exception:
                            pass
                elif is_protocol_base:
                    # Protocol base not resolvable in-repo (e.g. from typing import Protocol)
                    # Still useful to record the fact — but no graph edge can be created
                    pass


def _resolve_base(
    base_name: str,
    file_path: str,
    symbol_table: SymbolTable,
    imports: list,
) -> tuple[str | None, float]:
    # Same file
    entries = symbol_table.lookup_in_file(file_path, base_name)
    if entries:
        cls_entries = [e for e in entries if e.node_type == "class"]
        if cls_entries:
            return cls_entries[0].node_id, CONF_HERITAGE_DIRECT

    # Import resolved
    import_entries = symbol_table.lookup_imported_symbol(file_path, imports, base_name)
    cls_import = [e for e in import_entries if e.node_type == "class"]
    if cls_import:
        return cls_import[0].node_id, CONF_HERITAGE_DIRECT

    # Fuzzy global
    global_entries = symbol_table.lookup_global(base_name)
    cls_global = [e for e in global_entries if e.node_type == "class"]
    if cls_global:
        return cls_global[0].node_id, CONF_HERITAGE_FUZZY

    return None, 0.0
