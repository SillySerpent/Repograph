# Multi-user and concurrency

RepoGraph is designed for single-writer use per `.repograph/` directory.
This document describes the concurrency model and safe usage patterns for teams.

## Concurrency model

KuzuDB supports multiple concurrent **readers** but only one **writer** at a time.
RepoGraph's sync pipeline is a writer. Multiple concurrent syncs against the same
database will fail with `RepographDBLockedError`.

RepoGraph read surfaces now open the existing graph **without** running schema
DDL or migrations. That means concurrent readers are safe with each other, but
they should still avoid running during a sync/write.

**Readers** (safe to run concurrently with each other, but NOT during a write):
- `repograph summary`
- `repograph pathway`
- `repograph node`
- MCP server (read-only tools)
- Python API reads (`service.pathways()`, `service.dead_code()`, etc.)

**Writers** (exclusive access required):
- `repograph sync` (full or incremental)
- `repograph sync --full`
- `repograph clean`

## Safe patterns

### Single-developer use (default)

One developer, one machine: no coordination needed. Run `repograph sync` as needed.
Use `repograph watch` for continuous incremental sync — it has a single-flight guard
that prevents overlapping syncs.

### CI/CD pipeline

Run sync on a dedicated CI step:

```yaml
# Example GitHub Actions step
- name: Build RepoGraph index
  run: repograph sync --full
  # Only one job writes at a time — ensure no parallel sync steps
```

If you need the index in multiple CI jobs, build it once, then copy `.repograph/`
as a CI artifact to subsequent jobs that only read.

### Shared read access (team / monorepo)

If multiple developers or services need to read the same index:

1. **Dedicated index machine:** Run `repograph watch` on one machine (the index server).
2. **Mount `.repograph/` as read-only** on consumer machines (NFS, shared storage).
3. Consumers use the MCP server or Python API pointed at the shared `.repograph/`.

```sh
# Index server (writer)
repograph watch --repo /shared/repo

# Consumer (reader) — point at shared .repograph/
REPOGRAPH_DIR=/shared/repo/.repograph repograph summary
```

### Git worktrees

Each git worktree should have its own `.repograph/` directory. Do not share a single
index across worktrees — the file paths baked into the graph will be wrong.

```sh
git worktree add /path/to/worktree main
cd /path/to/worktree
repograph sync --static-only
```

Use `repograph sync --full` instead if you want the one-shot static + dynamic
overlay workflow for that worktree.

## Error: `RepographDBLockedError`

```
RepographDBLockedError: .repograph/graph.db is locked by another process
```

This means another process has the database open for writing. Remedies:

1. **Wait:** If a sync is in progress, wait for it to finish.
2. **Stop the watcher:** `pkill -f "repograph watch"`
3. **Kill a crashed sync:** Identify and kill the PID holding the lock.
4. **Remove the lock file** (only if you are certain no process is using the DB):
   ```sh
   ls .repograph/graph.db/
   rm .repograph/graph.db/*.lock 2>/dev/null
   ```

See `CORRUPTION_RECOVERY.md` for more on lock file removal.

## MCP server and concurrent reads

The MCP server runs read-only tools. Multiple MCP clients can connect concurrently
to the same MCP server instance. The server holds one `RepoGraphService` (one
database connection) — reads are serialized through KuzuDB's connection.

If you need higher read throughput, run multiple MCP server instances each with
their own `RepoGraphService`. They share the same database file and KuzuDB will
serve concurrent reads safely.
