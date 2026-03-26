"""Semantic vector search — requires embeddings phase to have run."""
from __future__ import annotations

import json
import os

from repograph.graph_store.store import GraphStore


class SemanticSearch:
    """
    Cosine-similarity search over function embeddings.
    Falls back to empty results if embeddings haven't been generated.
    """

    def __init__(self, store: GraphStore) -> None:
        self._store = store
        self._embeddings: dict[str, list[float]] | None = None
        self._model = None

    def _load_embeddings(self) -> dict[str, list[float]]:
        if self._embeddings is not None:
            return self._embeddings
        emb_path = os.path.join(os.path.dirname(self._store.db_path), "embeddings.json")
        if not os.path.exists(emb_path):
            self._embeddings = {}
            return self._embeddings
        with open(emb_path) as f:
            loaded = json.load(f)
        self._embeddings = loaded if isinstance(loaded, dict) else {}
        return self._embeddings

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Return semantically similar functions."""
        try:
            from sentence_transformers import SentenceTransformer
            import numpy as np
        except ImportError:
            return []

        embeddings = self._load_embeddings()
        if not embeddings:
            return []

        if self._model is None:
            self._model = SentenceTransformer("BAAI/bge-small-en-v1.5")

        query_vec = self._model.encode(query)
        scored: list[tuple[float, str]] = []

        for fn_id, emb in embeddings.items():
            vec = np.array(emb)
            sim = float(np.dot(query_vec, vec) / (np.linalg.norm(query_vec) * np.linalg.norm(vec) + 1e-9))
            scored.append((sim, fn_id))

        scored.sort(key=lambda x: -x[0])
        results = []
        for sim, fn_id in scored[:limit]:
            fn = self._store.get_function_by_id(fn_id)
            if fn:
                results.append({
                    "id": fn_id,
                    "type": "function",
                    "name": fn.get("qualified_name", ""),
                    "file_path": fn.get("file_path", ""),
                    "signature": fn.get("signature", ""),
                    "score": sim,
                })
        return results
