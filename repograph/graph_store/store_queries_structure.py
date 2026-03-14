"""GraphStore structural, pathway, and meta-export query helpers."""
from __future__ import annotations

import json
import os

from repograph.graph_store.store_base import GraphStoreBase


class GraphStoreStructureQueries(GraphStoreBase):
    def get_functions_by_layer(self, layer: str) -> list[dict]:
        """Return all Function nodes with the given ``layer`` value."""
        try:
            rows = self.query(
                "MATCH (f:Function) WHERE f.layer = $layer "
                "RETURN f.id, f.qualified_name, f.file_path, f.layer, f.role, "
                "f.http_method, f.route_path",
                {"layer": layer},
            )
        except Exception:
            return []
        return [
            {
                "id": row[0],
                "qualified_name": row[1],
                "file_path": row[2],
                "layer": row[3],
                "role": row[4],
                "http_method": row[5],
                "route_path": row[6],
            }
            for row in rows
        ]

    def get_http_endpoints(self) -> list[dict]:
        """Return all Function nodes that are HTTP endpoints."""
        try:
            rows = self.query(
                "MATCH (f:Function) WHERE f.http_method <> '' AND f.http_method IS NOT NULL "
                "RETURN f.id, f.qualified_name, f.file_path, f.http_method, f.route_path, f.layer"
            )
        except Exception:
            return []
        return [
            {
                "id": row[0],
                "qualified_name": row[1],
                "file_path": row[2],
                "http_method": row[3],
                "route_path": row[4],
                "layer": row[5],
            }
            for row in rows
        ]

    def get_pathway(self, name: str) -> dict | None:
        """Resolve a pathway by internal name, display name, or id."""
        cols = (
            "p.id, p.name, p.display_name, p.description, p.context_doc, "
            "p.confidence, p.step_count, p.entry_function, p.source, p.importance_score"
        )

        def row_to_dict(row: list) -> dict:
            return {
                "id": row[0],
                "name": row[1],
                "display_name": row[2],
                "description": row[3],
                "context_doc": row[4],
                "confidence": row[5],
                "step_count": row[6],
                "entry_function": row[7],
                "source": row[8],
                "importance_score": row[9] or 0.0,
            }

        rows = self.query(
            f"MATCH (p:Pathway {{name: $v}}) RETURN {cols}",
            {"v": name},
        )
        if rows:
            return row_to_dict(rows[0])

        rows = self.query(
            f"MATCH (p:Pathway) WHERE p.display_name = $v RETURN {cols}",
            {"v": name},
        )
        if rows:
            return row_to_dict(rows[0])

        rows = self.query(
            f"MATCH (p:Pathway) WHERE p.id = $v RETURN {cols}",
            {"v": name},
        )
        if rows:
            return row_to_dict(rows[0])

        try:
            all_rows = self.query(f"MATCH (p:Pathway) RETURN {cols}")
        except Exception:
            return None
        needle = name.lower()
        candidates = [
            row
            for row in all_rows
            if needle in (row[1] or "").lower() or needle in (row[2] or "").lower()
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda row: len(row[1] or ""))
        return row_to_dict(candidates[0])

    def get_all_pathways(self) -> list[dict]:
        rows = self.query(
            """
            MATCH (p:Pathway)
            RETURN p.id, p.name, p.display_name, p.description,
                   p.confidence, p.step_count, p.source, p.entry_function,
                   p.importance_score
            """
        )
        return [
            {
                "id": row[0],
                "name": row[1],
                "display_name": row[2],
                "description": row[3],
                "confidence": row[4],
                "step_count": row[5],
                "source": row[6],
                "entry_function": row[7],
                "importance_score": row[8] or 0.0,
            }
            for row in rows
        ]

    def get_pathway_by_id(self, pathway_id: str) -> dict | None:
        rows = self.query(
            """
            MATCH (p:Pathway {id: $id})
            RETURN p.id, p.name, p.display_name, p.description, p.context_doc,
                   p.confidence, p.step_count, p.entry_function, p.source,
                   p.variable_threads, p.entry_file
            """,
            {"id": pathway_id},
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "id": row[0],
            "name": row[1],
            "display_name": row[2],
            "description": row[3],
            "context_doc": row[4],
            "confidence": row[5],
            "step_count": row[6],
            "entry_function": row[7],
            "source": row[8],
            "variable_threads": row[9],
            "entry_file": row[10],
        }

    def get_pathway_steps(self, pathway_id: str) -> list[dict]:
        rows = self.query(
            """
            MATCH (f:Function)-[r:STEP_IN_PATHWAY]->(p:Pathway {id: $pid})
            RETURN f.id, f.name, f.qualified_name, f.file_path,
                   f.line_start, f.line_end, f.decorators,
                   r.step_order, r.role
            ORDER BY r.step_order
            """,
            {"pid": pathway_id},
        )
        return [
            {
                "id": row[0],
                "name": row[1],
                "function_name": row[1],
                "qualified_name": row[2],
                "file_path": row[3],
                "line_start": row[4],
                "line_end": row[5],
                "decorators": json.loads(row[6]) if row[6] else [],
                "step_order": row[7],
                "order": row[7],
                "role": row[8],
            }
            for row in rows
        ]

    def get_event_topology(self) -> list[dict]:
        """Return ``meta/event_topology.json`` records."""
        path = os.path.join(os.path.dirname(self.db_path), "meta", "event_topology.json")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []

    def get_async_tasks(self) -> list[dict]:
        """Return ``meta/async_tasks.json`` records."""
        path = os.path.join(os.path.dirname(self.db_path), "meta", "async_tasks.json")
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
