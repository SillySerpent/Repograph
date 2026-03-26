"""Phase 8 — Types: extract type annotations and resolve to class nodes.

This phase:
1. Iterates all function parameter and return type annotations.
2. Resolves each annotated type name to a Class node via the SymbolTable.
3. Marks resolved classes as is_type_referenced=true in the graph store,
   which exempts them from dead-code detection even if they have no direct callers.

This is a real, functional implementation of type-reference tracking.
Full USES_TYPE edge materialisation (planned for a future phase) would require
storing an explicit edge table, but the is_type_referenced flag is sufficient
to solve the primary goal of preventing false dead-code positives for type-only
class usage.
"""
from __future__ import annotations

import re

from repograph.core.models import ParsedFile
from repograph.graph_store.store import GraphStore
from repograph.parsing.symbol_table import SymbolTable


# Matches bare identifiers inside type strings like Optional[UserModel] -> UserModel
_TYPE_IDENT = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def run(
    parsed_files: list[ParsedFile],
    store: GraphStore,
    symbol_table: SymbolTable,
) -> None:
    """
    For every typed function (return annotation or parameter annotation),
    resolve the referenced type names to Class nodes and mark them as
    type-referenced so they are not falsely flagged as dead code.
    """
    resolved_class_ids: set[str] = set()   # deduplicate store writes

    for pf in parsed_files:
        # Build a fast lookup: function_id -> list of parameter VariableNodes
        fn_param_vars: dict[str, list] = {}
        for var in pf.variables:
            if var.is_parameter and var.inferred_type:
                fn_param_vars.setdefault(var.function_id, []).append(var)

        for fn in pf.functions:
            # Collect candidate type name strings from return type + param annotations
            type_strings: list[str] = []
            if fn.return_type:
                type_strings.append(fn.return_type)
            for var in fn_param_vars.get(fn.id, []):
                type_strings.append(var.inferred_type)  # type: ignore[arg-type]

            for type_str in type_strings:
                for type_name in _extract_type_names(type_str):
                    if not type_name:
                        continue
                    # Resolution order: local file first, then global
                    entries = symbol_table.lookup_in_file(fn.file_path, type_name)
                    if not entries:
                        entries = symbol_table.lookup_global(type_name)

                    for entry in entries:
                        if entry.node_type == "class" and entry.node_id not in resolved_class_ids:
                            resolved_class_ids.add(entry.node_id)
                            store.mark_class_type_referenced(entry.node_id)


def _extract_type_names(type_str: str) -> list[str]:
    """Extract bare identifier names from a type annotation string.

    Examples:
        "Optional[UserModel]"          -> ["Optional", "UserModel"]
        "dict[str, AuthResponse]"      -> ["dict", "str", "AuthResponse"]
        "list[User] | None"            -> ["list", "User", "None"]
    """
    return _TYPE_IDENT.findall(type_str)
