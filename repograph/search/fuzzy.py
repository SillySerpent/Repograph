"""Fuzzy search using Levenshtein edit distance."""
from __future__ import annotations

from repograph.graph_store.store import GraphStore


class FuzzySearch:
    """Levenshtein-distance-based fuzzy name search."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    def search(self, query: str, limit: int = 10, threshold: float = 0.5) -> list[dict]:
        """Return results where the function name is within edit distance of query."""
        all_fns = self._store.get_all_functions()
        scored: list[tuple[float, dict]] = []
        q = query.lower()

        for fn in all_fns:
            name = (fn.get("name") or "").lower()
            qname = (fn.get("qualified_name") or "").lower()

            sim = max(
                _similarity(q, name),
                _similarity(q, qname.split(":")[-1]),
            )
            if sim >= threshold:
                scored.append((sim, {
                    "id": fn["id"],
                    "type": "function",
                    "name": fn.get("qualified_name", ""),
                    "file_path": fn.get("file_path", ""),
                    "signature": fn.get("signature", ""),
                    "score": sim,
                }))

        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:limit]]


def _similarity(s: str, t: str) -> float:
    """Levenshtein similarity in [0, 1]."""
    if not s and not t:
        return 1.0
    dist = _levenshtein(s, t)
    return 1.0 - dist / max(len(s), len(t), 1)


def _levenshtein(s: str, t: str) -> int:
    m, n = len(s), len(t)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, n + 1):
            temp = dp[j]
            dp[j] = prev if s[i-1] == t[j-1] else 1 + min(prev, dp[j], dp[j-1])
            prev = temp
    return dp[n]
