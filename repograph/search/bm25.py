"""BM25 keyword search using KuzuDB's built-in string matching."""
from __future__ import annotations

from repograph.graph_store.store import GraphStore


class BM25Search:
    """
    BM25-style keyword search over function names, signatures, and docstrings.
    Uses KuzuDB's CONTAINS predicate for substring matching, scored by
    term frequency heuristic.
    """

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Return ranked results for a keyword query."""
        terms = query.lower().split()
        if not terms:
            return []

        all_fns = self._store.get_all_functions()
        scored: list[tuple[float, dict]] = []

        for fn in all_fns:
            score = self._score(fn, terms)
            if score > 0:
                scored.append((score, {
                    "id": fn["id"],
                    "type": "function",
                    "name": fn.get("qualified_name", ""),
                    "file_path": fn.get("file_path", ""),
                    "signature": fn.get("signature", ""),
                    "score": score,
                }))

        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:limit]]

    def _score(self, fn: dict, terms: list[str]) -> float:
        """Simple TF-based score across name + docstring + signature."""
        text = " ".join([
            (fn.get("name") or "").lower(),
            (fn.get("qualified_name") or "").lower(),
            (fn.get("docstring") or "").lower(),
            (fn.get("signature") or "").lower(),
        ])
        score = 0.0
        for term in terms:
            count = text.count(term)
            if count > 0:
                score += 1.0 + 0.1 * (count - 1)
                # Bonus for name match
                if term in (fn.get("name") or "").lower():
                    score += 0.5
        return score
