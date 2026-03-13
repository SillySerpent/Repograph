"""GraphStore call-graph and edge-traversal query helpers."""
from __future__ import annotations

import json

from repograph.graph_store.store_base import GraphStoreBase


class GraphStoreCallQueries(GraphStoreBase):
    def get_callers(self, function_id: str) -> list[dict]:
        rows = self.query(
            """
            MATCH (caller:Function)-[e:CALLS]->(f:Function {id: $id})
            RETURN caller.id, caller.qualified_name, caller.file_path, e.confidence, e.reason
            """,
            {"id": function_id},
        )
        return [
            {
                "id": row[0],
                "qualified_name": row[1],
                "file_path": row[2],
                "confidence": row[3],
                "reason": row[4],
            }
            for row in rows
        ]

    def get_interface_callers(self, function_id: str) -> list[dict]:
        """Find callers of interface/base methods that correspond to this impl."""
        name_rows = self.query(
            "MATCH (f:Function {id: $id}) RETURN f.name, f.qualified_name",
            {"id": function_id},
        )
        if not name_rows:
            return []
        func_name: str = name_rows[0][0]
        qualified: str = name_rows[0][1] or ""

        class_name = qualified.split(".")[0] if "." in qualified else ""
        if not class_name:
            return []

        base_rows = self.query(
            """
            MATCH (sub:Class {name: $cls})-[:EXTENDS|IMPLEMENTS*1..3]->(base:Class)
            RETURN base.name
            """,
            {"cls": class_name},
        )
        if not base_rows:
            return []
        base_names = [row[0] for row in base_rows if row[0]]

        seen: set[str] = set()
        result: list[dict] = []
        for base_name in base_names:
            base_fn_qname = f"{base_name}.{func_name}"
            caller_rows = self.query(
                """
                MATCH (base_fn:Function {qualified_name: $qname})
                MATCH (caller:Function)-[e:CALLS]->(base_fn)
                RETURN caller.id, caller.qualified_name, caller.file_path,
                       e.confidence, base_fn.qualified_name
                """,
                {"qname": base_fn_qname},
            )
            for row in caller_rows:
                caller_id = row[0]
                if caller_id in seen:
                    continue
                seen.add(caller_id)
                result.append(
                    {
                        "id": caller_id,
                        "qualified_name": row[1],
                        "file_path": row[2],
                        "confidence": round((row[3] or 1.0) * 0.9, 4),
                        "reason": f"via_interface:{row[4]}",
                    }
                )
        return result

    def get_callees(self, function_id: str) -> list[dict]:
        rows = self.query(
            """
            MATCH (f:Function {id: $id})-[e:CALLS]->(callee:Function)
            RETURN callee.id, callee.qualified_name, callee.file_path, e.confidence, e.reason
            """,
            {"id": function_id},
        )
        return [
            {
                "id": row[0],
                "qualified_name": row[1],
                "file_path": row[2],
                "confidence": row[3],
                "reason": row[4],
            }
            for row in rows
        ]

    def get_http_callees(self, function_id: str) -> list[dict]:
        """Return functions reachable via MAKES_HTTP_CALL from the given function."""
        rows = self.query(
            """
            MATCH (f:Function {id: $id})-[e:MAKES_HTTP_CALL]->(callee:Function)
            RETURN callee.id, callee.qualified_name, callee.file_path, e.confidence, e.http_method
            """,
            {"id": function_id},
        )
        return [
            {
                "id": row[0],
                "qualified_name": row[1],
                "file_path": row[2],
                "confidence": row[3],
                "reason": "http",
                "edge_type": "http",
                "http_method": row[4],
            }
            for row in rows
        ]

    def get_importers(self, file_path: str) -> list[str]:
        """Return paths of all files that import the given file."""
        from repograph.core.models import NodeID

        file_id = NodeID.make_file_id(file_path)
        rows = self.query(
            "MATCH (importer:File)-[:IMPORTS]->(f:File {id: $id}) RETURN importer.path",
            {"id": file_id},
        )
        return [row[0] for row in rows]

    def get_bulk_importers(self, file_paths: list[str]) -> list[str]:
        """Return paths of all files that import any of the given files."""
        if not file_paths:
            return []
        rows = self.query(
            "MATCH (importer:File)-[:IMPORTS]->(f:File) "
            "WHERE f.path IN $paths RETURN DISTINCT importer.path",
            {"paths": file_paths},
        )
        return [row[0] for row in rows if row[0]]

    def get_all_call_edges(self) -> list[dict]:
        if not self._calls_extra_lines:
            rows = self.query(
                """
                MATCH (a:Function)-[e:CALLS]->(b:Function)
                RETURN a.id, b.id, e.confidence, e.call_site_line, e.reason
                """
            )
            return [
                {
                    "from": row[0],
                    "to": row[1],
                    "confidence": row[2],
                    "line": row[3],
                    "lines": [row[3]],
                    "reason": row[4],
                }
                for row in rows
            ]

        rows = self.query(
            """
            MATCH (a:Function)-[e:CALLS]->(b:Function)
            RETURN a.id, b.id, e.confidence, e.call_site_line, e.reason, e.extra_site_lines
            """
        )
        out: list[dict] = []
        for row in rows:
            primary = row[3]
            lines = [primary]
            raw = row[5]
            if raw:
                try:
                    extra = json.loads(raw)
                    if isinstance(extra, list):
                        merged = {int(primary), *(
                            int(item)
                            for item in extra
                            if item is not None and str(item).lstrip("-").isdigit()
                        )}
                        lines = sorted(merged)
                except (json.JSONDecodeError, TypeError, ValueError):
                    lines = [primary]
            out.append(
                {
                    "from": row[0],
                    "to": row[1],
                    "confidence": row[2],
                    "line": lines[0] if lines else primary,
                    "lines": lines,
                    "reason": row[4],
                }
            )
        return out

    def get_flows_into_edges(self) -> list[dict]:
        rows = self.query(
            """
            MATCH (a:Variable)-[r:FLOWS_INTO]->(b:Variable)
            RETURN a.id, b.id, r.via_argument, r.confidence
            """
        )
        return [
            {
                "from": row[0],
                "to": row[1],
                "via_argument": row[2],
                "confidence": row[3],
            }
            for row in rows
        ]
