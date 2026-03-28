# Corruption recovery

RepoGraph stores its index in a KuzuDB database under `.repograph/graph.db`.
This document covers how to detect a corrupted index and recover from it.

## Detecting corruption

Corruption typically manifests as:

- `repograph sync` exits non-zero with a KuzuDB runtime exception
- `repograph doctor` reports an unreadable graph
- `repograph summary` returns empty output or raises `RuntimeError`
- `.repograph/logs/latest/errors.jsonl` contains `lock`, `corrupted`, or `binder exception` messages

### Quick check

```sh
repograph doctor
```

Doctor runs schema validation, a sample query, and a basic integrity probe. If any step fails it prints the subsystem and the error.

### Log inspection

```sh
repograph logs errors          # last run
repograph logs errors --run <id>   # specific run
```

## Recovery options

### Option 1: Full re-index (safest)

Delete the database directory and re-run a full sync. All data is derived from the source tree — there is no data loss beyond index rebuild time.

```sh
rm -rf .repograph/graph.db
repograph sync --full
```

`repograph sync --full` internally calls `GraphStore.clear_all_data()` before rebuilding.

### Option 2: Reinitialize schema, keep data

If only the schema is broken (missing columns) but node data is intact, calling `initialize_schema()` again applies all pending migrations:

```sh
python3 - <<'EOF'
from repograph.graph_store.store import GraphStore
store = GraphStore(".repograph/graph.db")
store.initialize_schema()
store.close()
print("schema migration complete")
EOF
```

This is idempotent — safe to run on an already-initialized database.

### Option 3: Restore from backup

If a backup exists (see `BACKUP_RESTORE.md`):

```sh
rm -rf .repograph/graph.db
cp -r /path/to/backup/graph.db .repograph/graph.db
```

After restore, run `repograph sync` (incremental) to bring the index up to date.

## Lock file issues

KuzuDB creates a lock file inside `graph.db/`. If a previous process crashed, the
lock may persist and block new connections:

```
RepographDBLockedError: .repograph/graph.db is locked by another process
```

**If you are certain no other process is using the database:**

```sh
# Remove the lock file (KuzuDB-specific path — check db dir for .lock or lock files)
ls .repograph/graph.db/
rm .repograph/graph.db/*.lock 2>/dev/null || true
```

Then retry `repograph sync`.

If the lock is held by a running `repograph watch` daemon, stop it first:
```sh
# Kill the watcher process
pkill -f "repograph watch"
```

## WAL (write-ahead log) recovery

KuzuDB uses a WAL. If the process crashed mid-write, KuzuDB recovers on next open by
replaying the WAL. If WAL recovery itself fails:

```sh
# Remove WAL files and retry — data may be lost back to last checkpoint
ls .repograph/graph.db/*.wal 2>/dev/null
rm .repograph/graph.db/*.wal 2>/dev/null || true
repograph sync --full
```

## Preventing corruption

- Never kill `repograph sync` with `SIGKILL` (`kill -9`). Use `SIGTERM` or `Ctrl-C` to allow clean shutdown.
- Do not run multiple `repograph sync` processes against the same `.repograph/` concurrently (see `MULTI_USER.md`).
- Use `repograph watch` for continuous sync — it has a single-flight guard that prevents overlapping syncs.
