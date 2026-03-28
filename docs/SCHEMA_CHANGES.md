# Kuzu schema changes

## Schema version 1.3

### `Function.is_test`

| Field | Type | Default | Populated by | Consumed by |
|-------|------|---------|--------------|-------------|
| `is_test` | BOOLEAN | `false` | Phase 3 parse (`FunctionNode` from `FileRecord.is_test`); `upsert_function` | `get_all_functions`, `get_test_coverage_map` Cypher, Phase 11 dead-code test classification, API readers |

**Upgrade:** Existing databases created before 1.3 run `ALTER TABLE Function ADD is_test BOOLEAN DEFAULT false` on `GraphStore.initialize_schema()` (best-effort; ignored if the column already exists). A full `repograph sync --full` rewrites function rows from parsers.

---

## Schema version 1.5 — secondary indexes (Block D2, not added)

Secondary `file_path` indexes were investigated but are not applicable to KuzuDB 0.11.x:

- KuzuDB does not support `CREATE INDEX` DDL for secondary/hash indexes on node properties.
- Only FTS and vector indexes exist (`CALL CREATE_FTS_INDEX` / `CREATE_VECTOR_INDEX`), which serve full-text and approximate-nearest-neighbor use cases, not equality lookups.
- KuzuDB's columnar storage applies predicate pushdown on `WHERE file_path = $x` queries natively via its scan operators — no explicit index DDL is needed or possible.

No schema change was made for v1.5. The version number is reserved. See `initialize_schema()` inline comment.

---

## Schema version 1.4

### Runtime overlay columns (`Function`)

Four columns persisting execution trace observations:

| Field | Type | Default | Populated by | Consumed by |
|-------|------|---------|--------------|-------------|
| `runtime_observed` | BOOLEAN | `false` | `apply_runtime_observation` | dead-code analysis, `runtime_overlay_summary` |
| `runtime_observed_calls` | INT64 | `0` | `apply_runtime_observation` | runtime overlay report |
| `runtime_observed_at` | STRING | `''` | `apply_runtime_observation` | freshness checks |
| `runtime_observed_for_hash` | STRING | `''` | `apply_runtime_observation` | invalidation on source change |

### Entry-score breakdown columns (`Function`)

| Field | Type | Default | Populated by | Consumed by |
|-------|------|---------|--------------|-------------|
| `entry_score_base` | DOUBLE | `0.0` | entry-point scorer | `get_entry_points`, `ScoreBreakdown` |
| `entry_score_multipliers` | STRING | `''` | entry-point scorer | `ScoreBreakdown` |
| `entry_callee_count` | INT64 | `0` | entry-point scorer | `ScoreBreakdown` |
| `entry_caller_count` | INT64 | `0` | entry-point scorer | `ScoreBreakdown` |

**Upgrade:** `_migrate_function_entry_score_details` and `_migrate_function_runtime_overlay_columns` in `GraphStoreBase.initialize_schema()`.

---

## Schema version 1.6

### Layer, role, and HTTP classification columns (`Function`, `File`)

Added to `Function`:

| Field | Type | Default | Populated by | Consumed by |
|-------|------|---------|--------------|-------------|
| `layer` | STRING | `''` | Phase `p06b_layer_classify`, framework adapters | layer queries, reports, MCP `query_graph` |
| `role` | STRING | `''` | `class_role` static analyzer plugin | role-based queries, architecture conformance |
| `http_method` | STRING | `''` | Python parser (route decorators), framework adapters | `get_http_endpoints`, cross-language resolution |
| `route_path` | STRING | `''` | Python parser (route decorators), framework adapters | HTTP endpoint matching, MAKES_HTTP_CALL edges |

Added to `File`:

| Field | Type | Default | Populated by | Consumed by |
|-------|------|---------|--------------|-------------|
| `layer` | STRING | `''` | Phase `p06b_layer_classify` | layer-level queries |

Valid `layer` values: `"db"`, `"persistence"`, `"business_logic"`, `"api"`, `"ui"`, `"util"`, `"unknown"`.

Valid `role` values: `"repository"`, `"service"`, `"controller"`, `"handler"`, `"page"`, `"component"`, `"util"`, `"model"`, `"unknown"`.

### `MAKES_HTTP_CALL` relationship type (new)

Cross-language HTTP call edge: `(Function) -[:MAKES_HTTP_CALL]-> (Function)`

| Field | Type | Description |
|-------|------|-------------|
| `http_method` | STRING | `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `WEBSOCKET` |
| `url_pattern` | STRING | URL pattern or literal from call site |
| `confidence` | DOUBLE | Matching confidence (0.0–1.0) |
| `reason` | STRING | `"http_endpoint_match"` or `"cross_lang_import"` |

Distinct from `CALLS` because it spans language boundaries and carries HTTP metadata.

**Upgrade:** `_migrate_layer_role_http_columns` in `GraphStoreBase.initialize_schema()`.

---

## Schema version 1.7

### `Function.is_covered` (pytest-cov overlay, Block I4)

| Field | Type | Default | Populated by | Consumed by |
|-------|------|---------|--------------|-------------|
| `is_covered` | BOOLEAN | `false` | `CoverageOverlayPlugin.analyze()` / `apply_coverage_json()` | layer coverage reports, `query_graph` NL queries |

A function is **covered** if at least one body line (`line_start+1` to `line_end`) appears in the `executed_lines` list of its file's entry in `coverage.json`.

**How to generate:** Run `pytest --cov --cov-report=json` to produce `coverage.json`, then run `repograph sync` — the plugin fires on `on_traces_collected`.

**Upgrade:** `_migrate_coverage_columns` in `GraphStoreBase.initialize_schema()`.
