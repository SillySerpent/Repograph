# Backup and restore

RepoGraph's persistent state lives entirely in `.repograph/`. Backing up and restoring
is straightforward since the index is fully derived from source code.

## What to back up

```
.repograph/
    graph.db/          ← KuzuDB database (main index)
    logs/              ← structured observability logs (optional)
    meta.json          ← sync metadata, community snapshot hash
    community_snapshot.json  ← incremental community cache
    runtime/           ← runtime trace files (if using tracer)
    mirror/            ← doc-mirror markdown files (optional)
```

For a minimal backup that allows full recovery: back up `graph.db/` and `meta.json`.

For a backup that preserves incremental-sync efficiency: also back up `community_snapshot.json`.

## Creating a backup

### Simple copy (offline — safest)

Stop any running watchers, then copy the directory:

```sh
pkill -f "repograph watch" || true
cp -r .repograph/graph.db /path/to/backup/graph.db.$(date +%Y%m%d-%H%M%S)
cp .repograph/meta.json /path/to/backup/
cp .repograph/community_snapshot.json /path/to/backup/ 2>/dev/null || true
```

### Archive

```sh
tar -czf repograph-backup-$(date +%Y%m%d).tar.gz \
    .repograph/graph.db \
    .repograph/meta.json \
    .repograph/community_snapshot.json 2>/dev/null
```

## Restoring from backup

```sh
# Stop watchers
pkill -f "repograph watch" || true

# Remove current index
rm -rf .repograph/graph.db

# Restore
cp -r /path/to/backup/graph.db .repograph/graph.db
cp /path/to/backup/meta.json .repograph/meta.json
cp /path/to/backup/community_snapshot.json .repograph/ 2>/dev/null || true

# Run incremental sync to bring index up to date
repograph sync
```

The incremental sync after restore will re-parse only files that changed since the backup.

## Backup during live sync

KuzuDB is not safe to copy while a write transaction is in progress. If you must
back up a live instance:

1. Prefer taking backups after `repograph sync` completes (not during).
2. If using `repograph watch`, wait for a `repograph: sync ok` message before copying.
3. KuzuDB checkpoints on close — `store.close()` ensures the WAL is flushed before copy.

## Recovery without backup

Since the index is fully derived from the source tree, a full re-index always recovers
to a consistent state:

```sh
rm -rf .repograph/graph.db .repograph/meta.json .repograph/community_snapshot.json
repograph sync --static-only
```

This takes longer than an incremental sync but produces identical results.

## Backup size estimates

| Repo size | Approx. graph.db size |
|-----------|----------------------|
| 1 000 functions | ~5 MB |
| 10 000 functions | ~50–100 MB |
| 100 000 functions | ~500 MB–1 GB |

The `graph.db/` directory contains KuzuDB's column-store files plus WAL.
The directory size scales roughly linearly with function count.
