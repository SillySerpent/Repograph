"""Hybrid search — BM25 + fuzzy + optional semantic, fused via RRF."""
from __future__ import annotations

from repograph.graph_store.store import GraphStore


def _rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + rank + 1)


class HybridSearch:
    """Fuses BM25 keyword, fuzzy name, and optional semantic signals."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    def search(self, query: str, limit: int = 10) -> list[dict]:
        from repograph.search.bm25 import BM25Search
        from repograph.search.fuzzy import FuzzySearch

        bm25_results = BM25Search(self._store).search(query, limit=limit * 2)
        fuzzy_results = FuzzySearch(self._store).search(query, limit=limit * 2)

        try:
            from repograph.search.semantic import SemanticSearch
            semantic_results = SemanticSearch(self._store).search(query, limit=limit)
        except Exception:
            semantic_results = []

        pathway_results = self._search_pathways(query)

        rrf: dict[str, float] = {}
        meta: dict[str, dict] = {}

        for rank, r in enumerate(bm25_results):
            rrf[r["id"]] = rrf.get(r["id"], 0) + _rrf_score(rank)
            meta[r["id"]] = r
        for rank, r in enumerate(fuzzy_results):
            rrf[r["id"]] = rrf.get(r["id"], 0) + _rrf_score(rank) * 0.8
            meta.setdefault(r["id"], r)
        for rank, r in enumerate(semantic_results):
            rrf[r["id"]] = rrf.get(r["id"], 0) + _rrf_score(rank) * 1.2
            meta.setdefault(r["id"], r)
        for rank, r in enumerate(pathway_results):
            rrf[r["id"]] = rrf.get(r["id"], 0) + _rrf_score(rank) * 0.9
            meta.setdefault(r["id"], r)

        ranked = sorted(rrf.items(), key=lambda x: -x[1])
        return [{**meta[rid], "score": score} for rid, score in ranked[:limit] if rid in meta]

    def _search_pathways(self, query: str) -> list[dict]:
        q = query.lower()
        results = []
        for p in self._store.get_all_pathways():
            name = (p.get("name") or "").lower()
            desc = (p.get("description") or "").lower()
            score = 0.0
            if q in name:
                score = 1.0 if name == q else 0.8
            elif any(w in name for w in q.split()):
                score = 0.6
            elif q in desc:
                score = 0.4
            if score > 0:
                results.append({
                    "id": p["id"], "type": "pathway",
                    "name": p.get("display_name") or p.get("name", ""),
                    "file_path": p.get("entry_function", ""),
                    "signature": p.get("description", ""),
                    "score": score,
                })
        return sorted(results, key=lambda x: -x["score"])
