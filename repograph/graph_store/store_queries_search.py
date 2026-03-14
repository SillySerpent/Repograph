"""GraphStore name and symbol search helpers."""
from __future__ import annotations

from typing import Any

from repograph.graph_store.store_base import GraphStoreBase


class GraphStoreSearchQueries(GraphStoreBase):
    def search_functions_by_name(self, name: str, limit: int = 10) -> list[dict]:
        """Simple name-based search with deterministic exact-match preference."""
        rows = self.query(
            """
            MATCH (f:Function)
            WHERE lower(f.name) CONTAINS lower($name)
               OR lower(f.qualified_name) CONTAINS lower($name)
            RETURN f.id, f.name, f.qualified_name, f.file_path, f.signature
            """,
            {"name": name},
        )
        lowered = (name or "").lower()

        def _match_rank(row: list[Any]) -> tuple[int, int, str]:
            simple_name = str(row[1] or "")
            qualified_name = str(row[2] or "")
            qualified_lower = qualified_name.lower()
            simple_lower = simple_name.lower()
            if qualified_name == name:
                rank = 0
            elif qualified_lower == lowered:
                rank = 1
            elif simple_name == name:
                rank = 2
            elif simple_lower == lowered:
                rank = 3
            elif qualified_lower.startswith(lowered):
                rank = 4
            elif simple_lower.startswith(lowered):
                rank = 5
            else:
                rank = 6
            return (rank, len(qualified_name), qualified_name)

        ranked_rows = sorted(rows, key=_match_rank)
        return [
            {
                "id": row[0],
                "qualified_name": row[2],
                "file_path": row[3],
                "signature": row[4],
            }
            for row in ranked_rows[:limit]
        ]
