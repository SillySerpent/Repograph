"""GraphStore — KuzuDB persistence layer for RepoGraph.

Uses MERGE for upserts so re-indexing is idempotent.
Arrays are stored as JSON strings (KuzuDB limitation for simple types).

Implementation is split across ``store_*.py`` modules; this file composes
them and re-exports helpers used by the pipeline runner and tests.
"""
from __future__ import annotations

from repograph.graph_store.store_queries_calls import GraphStoreCallQueries
from repograph.graph_store.store_queries_entrypoints import GraphStoreEntrypointQueries
from repograph.graph_store.store_queries_nodes import GraphStoreNodeQueries
from repograph.graph_store.store_queries_readers import GraphStoreSyncReaders
from repograph.graph_store.store_queries_search import GraphStoreSearchQueries
from repograph.graph_store.store_queries_structure import GraphStoreStructureQueries
from repograph.graph_store.store_utils import _delete_db_dir, _hash_content, _j, _ts
from repograph.graph_store.store_writes_admin import GraphStoreAdminWrites
from repograph.graph_store.store_writes_rel import GraphStoreRelWrites
from repograph.graph_store.store_writes_upserts import GraphStoreNodeUpserts

__all__ = [
    "GraphStore",
    "_delete_db_dir",
    "_hash_content",
    "_j",
    "_ts",
]


class GraphStore(
    GraphStoreCallQueries,
    GraphStoreEntrypointQueries,
    GraphStoreSearchQueries,
    GraphStoreStructureQueries,
    GraphStoreNodeQueries,
    GraphStoreSyncReaders,
    GraphStoreAdminWrites,
    GraphStoreRelWrites,
    GraphStoreNodeUpserts,
):
    """Main interface for reading and writing the RepoGraph KuzuDB database."""
