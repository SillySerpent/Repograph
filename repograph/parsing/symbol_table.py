"""Cross-file symbol resolution table.

The SymbolTable maps (file_path, symbol_name) to fully qualified node IDs.
It is populated during Phase 3 (parse) and queried during Phase 5 (call resolution).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from repograph.core.models import FunctionNode, ClassNode, ImportNode


@dataclass
class SymbolEntry:
    """A resolved symbol in the table."""
    node_id: str          # full node ID (function:path:qname or class:path:qname)
    node_type: str        # "function" | "class"
    file_path: str
    qualified_name: str
    name: str             # simple (unqualified) name


class SymbolTable:
    """
    Multi-index symbol lookup:
    - by (file_path, simple_name)
    - by (file_path, qualified_name)
    - by simple_name (global, for fuzzy fallback)
    """

    def __init__(self) -> None:
        # file_path -> {name -> list[SymbolEntry]}
        self._by_file: dict[str, dict[str, list[SymbolEntry]]] = defaultdict(lambda: defaultdict(list))
        # file_path -> {qualified_name -> SymbolEntry}
        self._by_qualified: dict[str, dict[str, SymbolEntry]] = defaultdict(dict)
        # simple_name -> list[SymbolEntry] (across all files)
        self._global_by_name: dict[str, list[SymbolEntry]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Population
    # ------------------------------------------------------------------

    def add_function(self, fn: FunctionNode) -> None:
        entry = SymbolEntry(
            node_id=fn.id,
            node_type="function",
            file_path=fn.file_path,
            qualified_name=fn.qualified_name,
            name=fn.name,
        )
        self._by_file[fn.file_path][fn.name].append(entry)
        self._by_file[fn.file_path][fn.qualified_name].append(entry)
        self._by_qualified[fn.file_path][fn.qualified_name] = entry
        self._global_by_name[fn.name].append(entry)
        self._global_by_name[fn.qualified_name].append(entry)

    def add_class(self, cls: ClassNode) -> None:
        entry = SymbolEntry(
            node_id=cls.id,
            node_type="class",
            file_path=cls.file_path,
            qualified_name=cls.qualified_name,
            name=cls.name,
        )
        self._by_file[cls.file_path][cls.name].append(entry)
        self._by_file[cls.file_path][cls.qualified_name].append(entry)
        self._by_qualified[cls.file_path][cls.qualified_name] = entry
        self._global_by_name[cls.name].append(entry)


    def add_function_from_dict(self, d: dict) -> None:
        """Populate SymbolTable from a store dict (avoids re-parsing unchanged files).

        Accepts the dict format returned by GraphStore.get_all_functions_for_symbol_table().
        """
        entry = SymbolEntry(
            node_id=d["id"],
            node_type="function",
            file_path=d["file_path"],
            qualified_name=d["qualified_name"],
            name=d["name"],
        )
        fp = d["file_path"]
        self._by_file[fp][d["name"]].append(entry)
        self._by_file[fp][d["qualified_name"]].append(entry)
        self._by_qualified[fp][d["qualified_name"]] = entry
        self._global_by_name[d["name"]].append(entry)
        self._global_by_name[d["qualified_name"]].append(entry)

    def add_class_from_dict(self, d: dict) -> None:
        """Populate SymbolTable from a store dict (avoids re-parsing unchanged files).

        Accepts the dict format returned by GraphStore.get_all_classes_for_symbol_table().
        """
        entry = SymbolEntry(
            node_id=d["id"],
            node_type="class",
            file_path=d["file_path"],
            qualified_name=d["qualified_name"],
            name=d["name"],
        )
        fp = d["file_path"]
        self._by_file[fp][d["name"]].append(entry)
        self._by_file[fp][d["qualified_name"]].append(entry)
        self._by_qualified[fp][d["qualified_name"]] = entry
        self._global_by_name[d["name"]].append(entry)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def lookup_in_file(
        self, file_path: str, name: str
    ) -> list[SymbolEntry]:
        """Look up a symbol by name within a specific file."""
        return self._by_file[file_path].get(name, [])

    def lookup_qualified(
        self, file_path: str, qualified_name: str
    ) -> SymbolEntry | None:
        return self._by_qualified[file_path].get(qualified_name)

    def lookup_global(self, name: str) -> list[SymbolEntry]:
        """Global lookup by simple name (for fuzzy resolution fallback)."""
        return self._global_by_name.get(name, [])

    def lookup_imported_symbol(
        self,
        importer_file: str,
        imports: list[ImportNode],
        symbol_name: str,
    ) -> list[SymbolEntry]:
        """
        Given a call to `symbol_name` in `importer_file`, check whether
        that name was imported from another file in the repo, and if so,
        look it up there.

        Handles both direct imports and aliased imports:
          from M import X        → symbol_name "X" resolves to X in M
          from M import X as Y   → symbol_name "Y" resolves to X in M
        """
        results: list[SymbolEntry] = []
        for imp in imports:
            if imp.file_path != importer_file:
                continue
            if imp.resolved_path is None:
                continue

            # --- Alias resolution (import X as Y) -------------------------
            # If the call site uses a local alias Y, look up the original X.
            aliases = getattr(imp, "aliases", {}) or {}
            if symbol_name in aliases:
                original_name = aliases[symbol_name]
                found = self.lookup_in_file(imp.resolved_path, original_name)
                results.extend(found)
                # Don't continue — an alias match is definitive; return early
                # after this import so we don't also match on the original name
                # in a different import statement.
                continue

            # --- Direct name check ----------------------------------------
            if symbol_name in imp.imported_names or imp.is_wildcard:
                found = self.lookup_in_file(imp.resolved_path, symbol_name)
                results.extend(found)
        return results

    def all_functions_in_file(self, file_path: str) -> list[SymbolEntry]:
        return [
            e for entries in self._by_file[file_path].values()
            for e in entries
            if e.node_type == "function"
        ]

    def file_count(self) -> int:
        return len(self._by_file)

    def symbol_count(self) -> int:
        return sum(
            sum(len(v) for v in file_syms.values())
            for file_syms in self._by_file.values()
        )
