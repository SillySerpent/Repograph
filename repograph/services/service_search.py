"""Search-oriented RepoGraph service methods."""
from __future__ import annotations

from repograph.services.service_base import RepoGraphServiceProtocol, _observed_service_call


class ServiceSearchMixin:
    """Text and raw-query service surfaces."""

    @_observed_service_call(
        "service_search",
        metadata_fn=lambda self, query, limit=10: {
            "query_len": len(query or ""),
            "limit": int(limit),
        },
    )
    def search(self: RepoGraphServiceProtocol, query: str, limit: int = 10) -> list[dict]:
        """Search for functions by symbol text or simple keywords."""
        from repograph.search.query_tokens import tokenize_search_query

        store = self._get_store()
        terms = tokenize_search_query(query)
        if not terms:
            return []
        if len(terms) == 1:
            return store.search_functions_by_name(terms[0], limit=limit)

        seen: set[str] = set()
        merged: list[dict] = []
        for term in terms:
            for row in store.search_functions_by_name(term, limit=limit):
                row_id = row["id"]
                if row_id in seen:
                    continue
                seen.add(row_id)
                merged.append(row)
                if len(merged) >= limit:
                    return merged
        return merged

    @_observed_service_call(
        "service_query",
        metadata_fn=lambda self, cypher, params=None: {
            "cypher_len": len(cypher or ""),
            "param_count": len(params or {}),
        },
    )
    def query(
        self: RepoGraphServiceProtocol,
        cypher: str,
        params: dict | None = None,
    ) -> list[list]:
        """Execute a raw Cypher query against the graph database."""
        return self._get_store().query(cypher, params)
