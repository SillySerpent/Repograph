# Pipeline (`repograph.pipeline`)

## Layer A — Graph construction

`runner.run_full_pipeline` and `runner.run_incremental_pipeline` call phase modules
under `repograph/pipeline/phases/` in a fixed order:

- **Full sync:** `p01` walk → `p02` structure → `p03` parse → `p04` imports →
  `p05` calls → `p05b` callbacks → `p06` heritage → `p07` variables → `p08` types
  → `p09` communities → `p10` processes → optional `p12` git coupling → optional
  `p13` embeddings.
- **Incremental:** subset of the above over changed files, then `p09` / `p10`
  recomputed globally.

Parsing uses [`repograph.plugins.parsers.registry`](../plugins/parsers/registry.py).

## Graph write path

The live pipeline persists through a single [`GraphStore`](../graph_store/store.py) (Kuzu): phases **stream** MERGE/SET operations as they run. There is **no** separate in-memory graph flush step.

- **Node upserts** and relationship inserts live in [`repograph/graph_store/store_writes_upserts.py`](../graph_store/store_writes_upserts.py) and [`repograph/graph_store/store_writes_rel.py`](../graph_store/store_writes_rel.py) (e.g. ``upsert_function`` preserves runtime overlay columns; ``insert_call_edge`` never downgrades confidence on merge).
- **Post-sync checks:** [`repograph/quality/integrity.py`](../quality/integrity.py) implements structural invariants (Q1–Q6); use ``run_sync_invariants(store)`` after sync in tests or tooling.

## Layer B — Plugin hooks

After Layer A completes, `_fire_hooks` runs (unless incremental sync exits early
with no file changes):

1. `on_graph_built`
2. `on_evidence`
3. `on_export`
4. If runtime traces exist: `on_traces_collected`, then `on_traces_analyzed`

Implementations are **plugins** under [`repograph/plugins/`](../plugins/),
scheduled by [`repograph.plugins.lifecycle.get_hook_scheduler`](../plugins/lifecycle.py).

**Optional:** when `RunConfig.experimental_phase_plugins` is `True`, phases from
[`repograph/plugins/pipeline_phases/`](../plugins/pipeline_phases/registry.py) run
after the graph build and **before** hooks (see
[`docs/architecture/PLUGIN_PHASES_AND_HOOKS.md`](../../docs/architecture/PLUGIN_PHASES_AND_HOOKS.md)).

## Plugin framework types

Contracts and the hook scheduler live in
[`repograph.core.plugin_framework`](../core/plugin_framework/) (`PluginManifest`,
`PluginRegistry`, `PluginHookScheduler`, plugin base classes).
