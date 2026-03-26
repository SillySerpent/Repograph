# Phase 15 — Plugin Centralization and Refactor Closure

## Goal
Eliminate the “mid-refactor” feel by making sync-time feature execution come from plugin-owned implementations instead of the pipeline runner owning special cases.

## Indexed findings

### RG-ARCH-01 — scheduler kind split was collapsed incorrectly
- `repograph/plugins/lifecycle.py`
- `repograph/plugins/static_analyzers/_registry.py`
- `repograph/plugins/demand_analyzers/` (registry / discovery)

Problem:
Earlier iterations blurred sync-time graph work with demand-side analysis.

Impact:
The pipeline and service API needed distinct plugin kinds and registries.

Decision (current code):
- `static_analyzer` — sync-time, `on_graph_built`, ids `static_analyzer.*`
- `demand_analyzer` — query-time, `on_analysis`, canonical ids `demand_analyzer.*` with optional manifest `aliases` for legacy `analyzer.*` lookup strings
- `PluginKind` in `contracts.py` does **not** include a separate `"analyzer"` kind string; the Python alias `AnalyzerPlugin = DemandAnalyzerPlugin` remains for class imports only

### RG-ARCH-02 — runner owned too much feature logic
- `repograph/pipeline/runner.py`
- `repograph/docs/mirror.py`
- `repograph/plugins/exporters/pathway_contexts/` (context generation)
- `repograph/plugins/exporters/agent_guide/`
- `repograph/plugins/static_analyzers/dead_code/` (sync-time dead code)
- `repograph/plugins/static_analyzers/duplicates/` (duplicate detection; the old `p11b_duplicates.py` shim file was later removed)

Problem:
The runner directly invoked pathway assembly, dead-code detection, duplicate detection, docs mirror generation, pathway context generation, and agent guide generation.

Impact:
Even though plugin folders existed, the pipeline was still the real source of truth for several features.

Decision:
Move these responsibilities behind plugins; remove obsolete numbered-phase shims when tests and imports no longer need them.

### RG-ARCH-03 — several plugins were wrappers, not runtime implementations
- `repograph/plugins/exporters/event_topology/plugin.py`
- `repograph/plugins/exporters/async_tasks/plugin.py`
- `repograph/plugins/exporters/entry_points/plugin.py`
- `repograph/plugins/exporters/pathways/plugin.py`
- `repograph/plugins/exporters/summary/plugin.py`
- `repograph/plugins/exporters/report_surfaces/plugin.py`
- `repograph/plugins/exporters/runtime_overlay_summary/plugin.py`
- `repograph/plugins/exporters/observed_runtime_findings/plugin.py`

Problem:
Multiple exporters assumed a `service=` context even during sync-time `on_export` hooks.

Impact:
Plugin manifests looked complete, but pipeline execution could not actually rely on them.

Decision:
Make exporters pipeline-safe when only `store/repograph_dir/config` are available.

### RG-ARCH-04 — real static analyzers existed but were not the registered source of truth
- `repograph/plugins/static_analyzers/dead_code/plugin.py`
- `repograph/plugins/static_analyzers/event_topology/plugin.py`
- `repograph/plugins/static_analyzers/async_tasks/plugin.py`
- `repograph/plugins/static_analyzers/interface_map/plugin.py`

Problem:
The static-analyzer folder existed, but registration delegated back to the legacy analyzer family.

Impact:
Actual sync-time plugin execution was mostly inert or wrong-hooked.

Decision:
Register real sync-time analyzers explicitly.

### RG-COMPAT-01 — compatibility shims lost helper-level contracts
- `repograph/plugins/static_analyzers/dead_code/plugin.py` *(inheritance helpers)*
- `repograph/plugins/static_analyzers/pathways/scorer.py`
- Doc symbol checks: `repograph/plugins/exporters/doc_warnings/`
- Config registry / invariants: handled via exporters and demand plugins *(no longer separate `p17`/`p18` phase modules in-tree)*

Problem:
Some shims preserved only `run()` while tests and downstream imports still referenced helper-level symbols.

Decision:
Restore those helper exports while keeping implementation ownership in plugin folders.

## What changed in this delivery

### RG-DELIVER-01 — explicit sync-time static registry
Updated:
- `repograph/plugins/static_analyzers/_registry.py`
- `repograph/plugins/lifecycle.py`
- `repograph/plugins/features.py`

Result:
- sync-time analyzers are registered explicitly
- demand-side analyzers use `kind="demand_analyzer"` and `PluginHookScheduler.run_plugin("demand_analyzer", ...)`
- `built_in_plugin_manifests()` exposes `static_analyzers` and `demand_analyzers` (no duplicate `analyzers` key)

### RG-DELIVER-02 — new plugin-owned sync-time features
Added:
- `repograph/plugins/static_analyzers/pathways/plugin.py`
- `repograph/plugins/static_analyzers/duplicates/plugin.py`
- `repograph/plugins/exporters/docs_mirror/plugin.py`
- `repograph/plugins/exporters/pathway_contexts/plugin.py`
- `repograph/plugins/exporters/agent_guide/plugin.py`

Result:
The runner no longer owns those feature implementations.

### RG-DELIVER-03 — parsed-dependent analyzers now work during sync
Updated:
- `repograph/plugins/static_analyzers/event_topology/plugin.py`
- `repograph/plugins/static_analyzers/async_tasks/plugin.py`

Result:
They now consume `parsed` from the pipeline hook and write their meta artifacts during sync.

### RG-DELIVER-04 — exporters made pipeline-safe
Updated:
- `repograph/plugins/exporters/event_topology/plugin.py`
- `repograph/plugins/exporters/async_tasks/plugin.py`
- `repograph/plugins/exporters/entry_points/plugin.py`
- `repograph/plugins/exporters/pathways/plugin.py`
- `repograph/plugins/exporters/summary/plugin.py`
- `repograph/plugins/exporters/report_surfaces/plugin.py`
- `repograph/plugins/exporters/runtime_overlay_summary/plugin.py`
- `repograph/plugins/exporters/observed_runtime_findings/plugin.py`

Result:
Registered exporters can now operate during `on_export` without requiring a service wrapper.

### RG-DELIVER-05 — runner simplified to core graph build + hooks
Updated:
- `repograph/pipeline/runner.py`

Result:
The runner now focuses on:
1. core graph build
2. optional embeddings
3. plugin hook execution

### RG-DELIVER-06 — compatibility contract repaired *(superseded by later cleanup)*
Canonical implementations now live only under plugin packages; numbered phase
shims such as `p11_dead_code.py`, `p15_doc_symbols.py`, and top-level
`repograph/pathways/*` / `repograph/pipeline/dead_code/*` **have been removed**.
Duplicate-symbol logic lives in `plugins/static_analyzers/duplicates/`; the former
`p11b_duplicates.py` re-export shim **has been removed** (callers import the plugin module directly).

## Remaining closure work

### RG-NEXT-01 — reduce duplicate analyzer identities *(addressed)*
Current code:
- Sync-time: `static_analyzer.dead_code`, `static_analyzer.duplicates`, etc. (no `analyzer.*` aliases on static plugins).
- Demand-side: `demand_analyzer.dead_code`, `demand_analyzer.duplicates`, etc., with optional `aliases=("analyzer.dead_code",)` for registry lookup compatibility.
Registry lookups are **kind-scoped**, so the same dotted string can only alias within one family.

### RG-NEXT-02 — ~~merge or retire the analyzers split~~ *(done)*
Demand-side code lives in `plugins/demand_analyzers/`; sync-time work stays in
`plugins/static_analyzers/`. The old `plugins/analyzers/` directory name is gone.

### RG-NEXT-03 — formalize plugin execution ordering
Current state:
Registration order implicitly controls execution order.

Recommendation:
Add one of:
- manifest `order` / `after` / `before` metadata, or
- an explicit lifecycle order map in `plugins/lifecycle.py`

This matters now that pathways, dead code, duplicates, event topology, and async tasks all execute through plugins.

### RG-NEXT-04 — centralize plugin artifact IO helpers
Current state:
Several exporters still hand-roll JSON meta reading/writing.

Recommendation:
Create a shared helper module for:
- `write_meta_json(repograph_dir, name, payload)`
- `read_meta_json(repograph_dir, name, default)`
- `service_or_store(...)` pattern reduction

### RG-NEXT-05 — retire unused legacy analysis surfaces
Candidates:
- `repograph/pipeline/phases/p19_event_topology.py`
- `repograph/pipeline/phases/p20_async_tasks.py`
- `repograph/analysis/event_topology.py`
- `repograph/analysis/async_tasks.py`
- `repograph/analysis/interface_map.py`

Recommendation:
Keep them only if a verified external contract still needs them. Otherwise delete after one stabilization pass.

## Suggested stabilization sequence

1. **Registry cleanup**
   - decide final naming for sync-time vs demand-side analyzers
2. **Artifact IO helper extraction**
   - remove repeated meta JSON boilerplate
3. **Hook ordering contract**
   - make plugin ordering explicit
4. **Shim deletion pass**
   - remove shims not needed by a real external/test contract
5. **Docs alignment pass**
   - update README, PIPELINE.md, AGENT_USAGE.md, plugin docs
6. **Trust pass**
   - verify every registered plugin can run in pipeline context without `service=`

## End-state target

The desired end-state should read like this:
- `pipeline/runner.py` builds the graph and fires hooks
- `plugins/static_analyzers/*` enrich the graph from pipeline context
- `plugins/evidence_producers/*` collect declared/observed evidence
- `plugins/exporters/*` write stable artifacts and summaries
- `services/repo_graph_service.py` exposes query and demand-side orchestration only
- phase modules exist only where a compatibility contract still requires them

That shape removes the “mid-refactor” smell because ownership becomes obvious from the filesystem.
