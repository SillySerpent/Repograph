"""GraphStore lifecycle: open/close, schema init, low-level query execution."""
from __future__ import annotations

import os
from typing import Any

from repograph.graph_store.kuzu_loader import kuzu
from repograph.graph_store.schema import ALL_NODE_TABLES, ALL_REL_TABLES
from repograph.graph_store.store_utils import _delete_db_dir
from repograph.observability import ObservableMixin, get_logger

_logger = get_logger(__name__, subsystem="graph_store")


class GraphStoreBase(ObservableMixin):
    """Connection handle, schema initialization, and raw Cypher execution."""

    _obs_subsystem = "graph_store"

    def __init__(self, db_path: str) -> None:
        from repograph.exceptions import RepographDBLockedError

        self.db_path = db_path
        self._calls_extra_lines = False
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        try:
            self._db = kuzu.Database(db_path)
        except RuntimeError as exc:
            err = str(exc).lower()
            if "lock" in err or "could not set lock" in err:
                raise RepographDBLockedError(db_path, exc) from exc
            raise
        self._conn: Any | None = kuzu.Connection(self._db)
        self._initialized = False
        # Optional batch caches (see store_writes_upserts / store_writes_rel).
        self._runtime_overlay_prefetch: dict[str, tuple[Any, Any, Any, Any]] | None = None
        self._call_edge_prefetch: dict[tuple[str, str], list[list[Any]]] | None = None

    def _require_conn(self) -> Any:
        if self._conn is None:
            raise RuntimeError("GraphStore connection is closed")
        return self._conn

    def initialize_schema(self) -> None:
        """Create all node and relationship tables if they don't exist.

        Kuzu's ``IF NOT EXISTS`` silently skips DDL when a table already
        exists, so new columns added to an existing table definition will
        never be created that way.  All schema additions MUST be paired
        with a ``_migrate_*`` method that issues ``ALTER TABLE … ADD``
        guarded by a try/except (Kuzu raises when the column already exists).
        """
        conn = self._require_conn()
        for ddl in ALL_NODE_TABLES:
            conn.execute(ddl.strip())
        for ddl in ALL_REL_TABLES:
            conn.execute(ddl.strip())
        # Run all migrations in version order.  Each is idempotent.
        self._migrate_function_is_test_column()
        self._migrate_function_entry_score_details()
        self._migrate_function_runtime_overlay_columns()
        self._migrate_layer_role_http_columns()
        self._migrate_coverage_columns()
        # NOTE: KuzuDB 0.11.x does not support CREATE INDEX DDL for secondary/hash
        # indexes on node properties (Block D2).  KuzuDB's columnar scan already
        # applies predicate pushdown on WHERE file_path = $x queries, so no explicit
        # index DDL is needed or possible.  See docs/SCHEMA_CHANGES.md v1.5.
        self._initialized = True
        self._calls_extra_lines = self._probe_calls_extra_lines_column()

    def _migrate_function_is_test_column(self) -> None:
        """schema v1.3 — Add Function.is_test."""
        try:
            self._require_conn().execute(
                "ALTER TABLE Function ADD is_test BOOLEAN DEFAULT false"
            )
        except Exception:
            _logger.debug("migration v1.3: is_test column already exists — skipping")

    def _migrate_function_entry_score_details(self) -> None:
        """schema v1.4 — Add entry-score breakdown columns.

        These support the ScoreBreakdown returned by score_function_verbose()
        and are queried by get_entry_points().  On databases that predate
        this migration the columns simply don't exist and Kuzu will raise
        a Binder exception; the ALTER TABLE here fixes that transparently.
        """
        migrations = [
            "ALTER TABLE Function ADD entry_score_base DOUBLE DEFAULT 0.0",
            "ALTER TABLE Function ADD entry_score_multipliers STRING DEFAULT ''",
            "ALTER TABLE Function ADD entry_callee_count INT64 DEFAULT 0",
            "ALTER TABLE Function ADD entry_caller_count INT64 DEFAULT 0",
        ]
        for ddl in migrations:
            try:
                self._require_conn().execute(ddl)
            except Exception:
                _logger.debug("migration v1.4: entry_score column already exists — skipping", ddl=ddl)

    def _migrate_function_runtime_overlay_columns(self) -> None:
        """schema v1.4 — Persist runtime trace observations on Function nodes."""
        for ddl in (
            "ALTER TABLE Function ADD runtime_observed BOOLEAN DEFAULT false",
            "ALTER TABLE Function ADD runtime_observed_calls INT64 DEFAULT 0",
            "ALTER TABLE Function ADD runtime_observed_at STRING DEFAULT ''",
            "ALTER TABLE Function ADD runtime_observed_for_hash STRING DEFAULT ''",
        ):
            try:
                self._require_conn().execute(ddl)
            except Exception:
                _logger.debug("migration v1.4: runtime_overlay column already exists — skipping", ddl=ddl)

    def _migrate_layer_role_http_columns(self) -> None:
        """schema v1.6 — Add layer/role/http classification fields.

        Adds ``layer``, ``role``, ``http_method``, ``route_path`` to Function
        and ``layer`` to File.  These are populated by Block F/G (framework
        adapter tags and layer classification phase).  On fresh databases the
        DDL in schema.py already includes these columns; this migration handles
        existing databases.
        """
        migrations = [
            "ALTER TABLE Function ADD layer STRING DEFAULT ''",
            "ALTER TABLE Function ADD role STRING DEFAULT ''",
            "ALTER TABLE Function ADD http_method STRING DEFAULT ''",
            "ALTER TABLE Function ADD route_path STRING DEFAULT ''",
            "ALTER TABLE File ADD layer STRING DEFAULT ''",
        ]
        for ddl in migrations:
            try:
                self._require_conn().execute(ddl)
            except Exception:
                _logger.debug("migration v1.6: column already exists — skipping", ddl=ddl)

    def _migrate_coverage_columns(self) -> None:
        """schema v1.7 — Add Function.is_covered (pytest-cov overlay, Block I4)."""
        for ddl in [
            "ALTER TABLE Function ADD is_covered BOOLEAN DEFAULT false",
        ]:
            try:
                self._require_conn().execute(ddl)
            except Exception:
                _logger.debug("migration v1.7: column already exists — skipping", ddl=ddl)

    def _probe_calls_extra_lines_column(self) -> bool:
        """True when CALLS.extra_site_lines exists (schema >= 1.1)."""
        try:
            self.query("MATCH ()-[r:CALLS]->() RETURN r.extra_site_lines LIMIT 1")
            return True
        except Exception:
            return False

    def clear_all_data(self) -> None:
        """
        Destroy and recreate the entire database for a full re-index.

        Strategy: close own handles (so KuzuDB can checkpoint the WAL),
        delete the main DB file plus any WAL/SHM sidecars, then open a
        fresh database.

        Prefer calling _delete_db_dir() BEFORE constructing the GraphStore
        (as run_full_pipeline does) to avoid competing open handles entirely.
        """
        self._close_handles()
        _delete_db_dir(self.db_path)
        self._db = kuzu.Database(self.db_path)
        self._conn = kuzu.Connection(self._db)
        self._initialized = False
        self._calls_extra_lines = False
        self._runtime_overlay_prefetch = None
        self._call_edge_prefetch = None

    def close(self) -> None:
        """Explicitly release all database handles.
        Call this before running a new full pipeline on the same DB path."""
        self._close_handles()

    def _close_handles(self) -> None:
        """Release Python references to kuzu objects and hint the GC."""
        self._conn = None  # type: ignore[assignment]
        self._db = None  # type: ignore[assignment]
        import gc
        gc.collect()

    def query(self, cypher: str, params: dict | None = None) -> list[list[Any]]:
        """Execute a Cypher query and return all rows."""
        result = self._require_conn().execute(cypher, params or {})
        rows: list[list[Any]] = []
        while result.has_next():  # type: ignore[union-attr]
            rows.append(result.get_next())  # type: ignore[union-attr]
        return rows

    @staticmethod
    def _esc(s: str) -> str:
        """Escape a string value for safe Cypher interpolation. Caller must not pass None."""
        return str(s).replace("\\", "\\\\").replace("'", "\\'")

    # Known KuzuDB error message fragments that indicate a missing node during
    # relationship insertion.  All other exceptions are re-raised so that real
    # errors (schema mismatches, lock conflicts, query syntax) are never swallowed.
    _MISSING_NODE_PATTERNS: tuple[str, ...] = (
        "does not exist",
        "node does not exist",
        "runtime exception: node",
    )

    def _exec_rel(self, cypher: str) -> None:
        """Execute a relationship insertion.

        Skips operations where one endpoint node is missing (a known expected
        case during incremental sync when a callee has not yet been upserted).
        All other exceptions propagate so real errors remain visible.
        """
        try:
            self._require_conn().execute(cypher)
        except Exception as exc:
            err = str(exc).lower()
            if any(pat in err for pat in self._MISSING_NODE_PATTERNS):
                _logger.debug(
                    "relationship insertion skipped — missing node",
                    exc_msg=str(exc),
                )
            else:
                raise
