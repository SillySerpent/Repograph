"""GraphStore queries for incremental sync: symbol tables, files, duplicates, doc warnings."""
from __future__ import annotations

import json

from repograph.graph_store.store_base import GraphStoreBase


class GraphStoreSyncReaders(GraphStoreBase):
    # Symbol-table repopulation helpers (avoids re-parsing unchanged files)

    def get_all_functions_for_symbol_table(self) -> list[dict]:
        """Return lightweight function records needed to populate the SymbolTable.
        Used in incremental sync to avoid re-parsing unchanged files from disk."""
        rows = self.query(
            """
            MATCH (f:Function)
            RETURN f.id, f.name, f.qualified_name, f.file_path,
                   f.line_start, f.line_end, f.is_method, f.param_names,
                   f.return_type, f.is_exported, f.is_async, f.source_hash,
                   f.is_test
            """
        )
        return [
            {
                "id": r[0], "name": r[1], "qualified_name": r[2],
                "file_path": r[3], "line_start": r[4], "line_end": r[5],
                "is_method": r[6],
                "param_names": json.loads(r[7]) if r[7] else [],
                "return_type": r[8], "is_exported": r[9],
                "is_async": r[10], "source_hash": r[11],
                "is_test": r[12] if r[12] is not None else False,
            }
            for r in rows
        ]

    def get_all_classes_for_symbol_table(self) -> list[dict]:
        """Return lightweight class records needed to populate the SymbolTable.
        Used in incremental sync to avoid re-parsing unchanged files from disk."""
        rows = self.query(
            """
            MATCH (c:Class)
            RETURN c.id, c.name, c.qualified_name, c.file_path,
                   c.line_start, c.line_end, c.is_exported,
                   c.base_names, c.source_hash
            """
        )
        return [
            {
                "id": r[0], "name": r[1], "qualified_name": r[2],
                "file_path": r[3], "line_start": r[4], "line_end": r[5],
                "is_exported": r[6],
                "base_names": json.loads(r[7]) if r[7] else [],
                "source_hash": r[8],
            }
            for r in rows
        ]

    def get_variables_not_in_files(self, excluded_paths: set[str]) -> list[dict]:
        """Return all variable nodes whose file_path is NOT in excluded_paths.
        Used to populate the VariableScopeExtractor in incremental mode without
        re-parsing unchanged files from disk."""
        rows = self.query(
            """
            MATCH (v:Variable)
            RETURN v.id, v.name, v.function_id, v.file_path,
                   v.line_number, v.inferred_type, v.is_parameter,
                   v.is_return, v.value_repr
            """
        )
        return [
            {
                "id": r[0], "name": r[1], "function_id": r[2],
                "file_path": r[3], "line_number": r[4],
                "inferred_type": r[5], "is_parameter": r[6],
                "is_return": r[7], "value_repr": r[8],
            }
            for r in rows
            if r[3] not in excluded_paths
        ]

    def get_all_duplicate_symbols(self) -> list[dict]:
        """Return all DuplicateSymbolGroup records."""
        import json as _json
        try:
            rows = self.query(
                "MATCH (d:DuplicateSymbol) "
                "RETURN d.id, d.name, d.kind, d.occurrence_count, "
                "       d.file_paths, d.severity, d.reason, d.is_superseded, "
                "       d.canonical_path, d.superseded_paths"
            )
            return [
                {
                    "id": r[0], "name": r[1], "kind": r[2],
                    "occurrence_count": r[3],
                    "file_paths": _json.loads(r[4]) if r[4] else [],
                    "severity": r[5], "reason": r[6],
                    "is_superseded": r[7],
                    "canonical_path": r[8] or "",
                    "superseded_paths": _json.loads(r[9]) if r[9] else [],
                }
                for r in rows
            ]
        except Exception:
            return []

    def get_file(self, file_path: str) -> dict | None:
        from repograph.core.models import NodeID
        rows = self.query(
            "MATCH (f:File {id: $id}) RETURN f.id, f.path, f.source_hash, f.language",
            {"id": NodeID.make_file_id(file_path)}
        )
        if not rows:
            return None
        r = rows[0]
        return {"id": r[0], "path": r[1], "source_hash": r[2], "language": r[3]}

    def get_all_file_hashes(self) -> dict[str, str]:
        """Return {path: source_hash} for all indexed files."""
        rows = self.query("MATCH (f:File) RETURN f.path, f.source_hash")
        return {r[0]: r[1] for r in rows}

    def get_all_files(self) -> list[dict]:
        """Return all File nodes in the graph, ordered by path.

        Useful for verifying graph state after a full rebuild or incremental
        sync — callers can assert the exact set of files present without
        relying on get_stats() counts alone.
        """
        rows = self.query(
            """
            MATCH (f:File)
            RETURN f.id, f.path, f.language, f.line_count,
                   f.source_hash, f.is_test, f.is_config
            ORDER BY f.path
            """
        )
        return [
            {
                "id": r[0], "path": r[1], "language": r[2],
                "line_count": r[3], "source_hash": r[4],
                "is_test": r[5], "is_config": r[6],
            }
            for r in rows
        ]

    def get_functions_in_file(self, file_path: str) -> list[dict]:
        rows = self.query(
            """
            MATCH (f:Function {file_path: $fp})
            RETURN f.id, f.name, f.qualified_name, f.signature,
                   f.line_start, f.line_end, f.is_entry_point, f.entry_score,
                   f.is_dead, f.decorators, f.param_names, f.docstring, f.is_test
            """,
            {"fp": file_path}
        )
        return [
            {
                "id": r[0], "name": r[1], "qualified_name": r[2],
                "signature": r[3], "line_start": r[4], "line_end": r[5],
                "is_entry_point": r[6], "entry_score": r[7],
                "is_dead": r[8],
                "decorators": json.loads(r[9]) if r[9] else [],
                "param_names": json.loads(r[10]) if r[10] else [],
                "docstring": r[11],
                "is_test": r[12] if r[12] is not None else False,
            }
            for r in rows
        ]

    def get_classes_in_file(self, file_path: str) -> list[dict]:
        rows = self.query(
            """
            MATCH (c:Class {file_path: $fp})
            RETURN c.id, c.name, c.qualified_name, c.line_start, c.line_end,
                   c.docstring, c.base_names, c.is_exported, c.community_id
            """,
            {"fp": file_path}
        )
        return [
            {
                "id": r[0], "name": r[1], "qualified_name": r[2],
                "line_start": r[3], "line_end": r[4], "docstring": r[5],
                "base_names": json.loads(r[6]) if r[6] else [],
                "is_exported": r[7], "community_id": r[8],
            }
            for r in rows
        ]

    def get_all_classes(self) -> list[dict]:
        rows = self.query(
            """
            MATCH (c:Class)
            RETURN c.id, c.name, c.qualified_name, c.file_path,
                   c.line_start, c.line_end, c.community_id, c.base_names,
                   c.source_hash
            """
        )
        return [
            {
                "id": r[0], "name": r[1], "qualified_name": r[2],
                "file_path": r[3], "line_start": r[4], "line_end": r[5],
                "community_id": r[6],
                "base_names": json.loads(r[7]) if r[7] else [],
                "source_hash": r[8] or "",
            }
            for r in rows
        ]

    def get_all_doc_warnings(self, severity: str | None = None) -> list[dict]:
        """Return DocWarning records, optionally filtered by severity."""
        try:
            if severity:
                rows = self.query(
                    "MATCH (w:DocWarning) WHERE w.severity = $sev "
                    "RETURN w.id, w.doc_path, w.line_number, w.symbol_text, "
                    "       w.warning_type, w.severity, w.context_snippet "
                    "ORDER BY w.doc_path, w.line_number",
                    {"sev": severity}
                )
            else:
                rows = self.query(
                    "MATCH (w:DocWarning) "
                    "RETURN w.id, w.doc_path, w.line_number, w.symbol_text, "
                    "       w.warning_type, w.severity, w.context_snippet "
                    "ORDER BY w.doc_path, w.line_number"
                )
            return [
                {
                    "id": r[0], "doc_path": r[1], "line_number": r[2],
                    "symbol_text": r[3], "warning_type": r[4],
                    "severity": r[5], "context_snippet": r[6],
                }
                for r in rows
            ]
        except Exception:
            return []
