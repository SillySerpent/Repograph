# Performance tuning

RepoGraph's pipeline has several parameters that affect speed and memory use.
This document covers what to tune and how to measure the effect.

## Key parameters in `RunConfig`

| Parameter | Default | Effect |
|-----------|---------|--------|
| `min_community_size` | `3` | Minimum functions per Leiden community. Lower = more, smaller communities; higher = fewer, larger. Affects Phase 9 memory. |
| `module_expansion_threshold` | `15` | Maximum callers to expand when re-parsing changed modules in incremental sync. Lower = faster incremental; too low misses updates. |
| `max_context_tokens` | `2000` | Maximum tokens in generated pathway context documents. Affects Phases 13/14. |
| `workers` | `os.cpu_count()` | Thread count for parallel file parsing (Phase 3). |
| `continue_on_error` | `True` | Whether to continue when a phase fails. `False` makes failures immediately visible. |

Persisted user-facing settings live in `.repograph/settings.json` and optional
power-user overrides in `.repograph/repograph.index.yaml`. The persisted key for
pathway context size is `context_tokens`; the internal `RunConfig` field is
`max_context_tokens`.

Set these via the CLI:

```bash
repograph config set min_community_size 5
repograph config set context_tokens 1500
```

Or via `.repograph/repograph.index.yaml`:

```yaml
min_community_size: 5
context_tokens: 1500
```

Or programmatically:

```python
from repograph.pipeline.runner import RunConfig
config = RunConfig(repo_root="..", min_community_size=5, module_expansion_threshold=10)
```

## Phases and where time is spent

Run `repograph logs show` after a sync to see per-phase durations in the structured logs.
The slowest phases are typically:

| Phase | Description | Tuning knob |
|-------|-------------|-------------|
| `p03_parse` | File parsing | `workers` (parallel) |
| `p09_communities` | Leiden community detection | `min_community_size` (fewer large communities = faster) |
| `pathway_contexts` exporter | Pathway context generation | `context_tokens` / `max_context_tokens` (smaller = fewer tokens to process) |

Dynamic full rebuilds also emit spans for:
- `dynamic_full.step1_static_rebuild`
- `dynamic_full.step2_traced_tests`
- `dynamic_full.step3_finalize_overlay`

Those are the first places to check when `repograph sync --full` is slower or hotter than expected.

## Parallel parsing (Phase 3)

Phase 3 uses `ThreadPoolExecutor` with `workers` threads. Each thread gets its own
tree-sitter parser instance (thread-local). The default is `os.cpu_count()`.

For large repos (>10 000 files), increasing workers beyond CPU count typically hurts
due to I/O contention. Recommended: `workers = min(os.cpu_count(), 8)`.

## Incremental sync tuning

After the initial full sync, incremental syncs are fast. Performance depends on:

1. **Changed file count** — directly determines how many files are re-parsed.
2. **`module_expansion_threshold`** — caps how many upstream callers are also re-parsed.
   Lower values = faster, but may miss propagated changes in large call graphs.

If incremental syncs are slower than expected, inspect `.repograph/logs/latest/pipeline.jsonl`
for the `expand_reparse_paths` span duration.

## Community detection (Phase 9)

Phase 9 (Leiden clustering) is the most CPU-intensive phase for large graphs.

**Partial re-run:** If fewer than 5% of functions changed in a sync, RepoGraph attempts
a partial community re-run that only re-clusters the affected subgraph. This is
significantly faster and usually produces equivalent results.

To force a full re-run (e.g., after a large structural refactor):
```sh
repograph sync --static-only
```

## Memory usage

Memory scales with:
- **Function count** — each node is ~200–400 bytes in the KuzuDB buffer pool.
- **Community size** — larger communities require more Leiden algorithm memory.
- **Context tokens** — pathway context generation holds text in memory per pathway.

For repos with >100 000 functions, consider:
- Increasing `min_community_size` to 10–20 to reduce community count.
- Reducing `max_context_tokens` to 1000 to limit pathway document size.
- Running on a machine with ≥8 GB RAM.

## KuzuDB buffer pool

KuzuDB auto-tunes its buffer pool. If you see OOM errors, set the buffer pool size
explicitly when opening the database. This requires using the store directly:

```python
from repograph.graph_store.store import GraphStore
# KuzuDB default buffer pool is 80% of available RAM for large datasets
store = GraphStore(".repograph/graph.db")
```

To limit memory, run the sync on a machine with less RAM or reduce parallel workers.

## Profiling a sync

```sh
# Full sync with timing output in logs
repograph sync --static-only
repograph logs show | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        r = json.loads(line)
        if r.get('duration_ms'):
            print(f\"{r['operation']:40} {r['duration_ms']:.0f}ms\")
    except: pass
" | sort -t' ' -k2 -rn | head -20
```
