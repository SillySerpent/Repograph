# Kuzu schema changes

## Schema version 1.3

### `Function.is_test`

| Field | Type | Default | Populated by | Consumed by |
|-------|------|---------|--------------|-------------|
| `is_test` | BOOLEAN | `false` | Phase 3 parse (`FunctionNode` from `FileRecord.is_test`); `upsert_function` | `get_all_functions`, `get_test_coverage_map` Cypher, Phase 11 dead-code test classification, API readers |

**Upgrade:** Existing databases created before 1.3 run `ALTER TABLE Function ADD is_test BOOLEAN DEFAULT false` on `GraphStore.initialize_schema()` (best-effort; ignored if the column already exists). A full `repograph sync --full` rewrites function rows from parsers.
