"""Phase 13 — Embeddings: vector embeddings for semantic search (optional)."""
from __future__ import annotations

from repograph.graph_store.store import GraphStore


def run(store: GraphStore) -> None:
    """
    Generate vector embeddings for functions and pathways.
    Requires sentence-transformers to be installed.
    Embeddings are stored as serialised JSON in a sidecar file since
    KuzuDB HNSW requires explicit schema setup that varies by version.
    """
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        raise ImportError(
            "sentence-transformers not installed. "
            "Install with: pip install 'repograph[embeddings]'"
        )

    model = SentenceTransformer("BAAI/bge-small-en-v1.5")

    functions = store.get_all_functions()
    texts = [
        f"{fn.get('qualified_name', '')} {fn.get('docstring', '')} {fn.get('signature', '')}"
        for fn in functions
    ]

    if not texts:
        return

    embeddings = model.encode(texts, batch_size=32, show_progress_bar=False)

    import json, os
    db_dir = os.path.dirname(store.db_path)
    emb_path = os.path.join(db_dir, "embeddings.json")
    data = {
        fn["id"]: emb.tolist()
        for fn, emb in zip(functions, embeddings)
    }
    with open(emb_path, "w") as f:
        json.dump(data, f)
