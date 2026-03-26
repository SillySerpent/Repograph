# Phase 16 — Identity Cleanup, Hook Ordering, and Artifact IO Consolidation

## Goal
Finish the second closure pass by removing the most obvious “mid-refactor” signals that remained after plugin centralization:

1. sync-time plugins and demand-side wrappers sharing the same IDs
2. hidden registration-order coupling in hook execution
3. repeated ad-hoc JSON meta read/write logic
4. API/manifests still exposing old naming without a clearer mental model

---

## Indexed findings

### RG2-ID-01 — sync-time and demand-side analyzers still had colliding identities
**Files:**
- `repograph/plugins/static_analyzers/pathways/plugin.py`
- `repograph/plugins/static_analyzers/dead_code/plugin.py`
- `repograph/plugins/static_analyzers/duplicates/plugin.py`
- `repograph/plugins/static_analyzers/event_topology/plugin.py`
- `repograph/plugins/static_analyzers/async_tasks/plugin.py`
- `repograph/plugins/demand_analyzers/*/plugin.py`

**Problem:**
Static analyzers and service-facing analyzer wrappers were both using `analyzer.*` IDs.

**Impact:**
The filesystem suggested two families, but the manifest layer blurred them back together. That made the codebase look transitional even after plugin centralization.

**Resolution:**
Static analyzers use canonical `static_analyzer.*` IDs **without** `analyzer.*` aliases. Demand analyzers use canonical `demand_analyzer.*` IDs; legacy `analyzer.*` strings remain as **manifest aliases** on demand plugins only (see `PluginRegistry.resolve_id`).

---

### RG2-ORD-01 — hook execution order was still implicit
**Files:**
- `repograph/core/plugin_framework/contracts.py`
- `repograph/core/plugin_framework/hooks.py`
- `repograph/plugins/exporters/*/plugin.py`
- `repograph/plugins/static_analyzers/*/plugin.py`

**Problem:**
Plugin execution order was effectively controlled by registration order.

**Impact:**
That made the system fragile and made plugin ownership less believable: if a feature depends on another feature, the relationship should be declared in the plugin manifest rather than in registry boilerplate.

**Resolution:**
`PluginManifest` now supports:
- `order`
- `after`
- `before`
- `aliases`

The scheduler now topologically orders plugins per hook using these fields, with stable fallback ordering.

---

### RG2-ART-01 — meta artifact IO was still duplicated across plugin families
**Files:**
- `repograph/plugins/utils/meta_io.py`
- `repograph/plugins/exporters/event_topology/plugin.py`
- `repograph/plugins/exporters/async_tasks/plugin.py`
- `repograph/plugins/exporters/report_surfaces/plugin.py`
- `repograph/plugins/exporters/config_registry/plugin.py`
- `repograph/plugins/exporters/modules/plugin.py`
- `repograph/plugins/exporters/invariants/plugin.py`
- `repograph/plugins/static_analyzers/event_topology/plugin.py`
- `repograph/plugins/static_analyzers/async_tasks/plugin.py`
- `repograph/pipeline/phases/p19_event_topology.py`
- `repograph/pipeline/phases/p20_async_tasks.py`

**Problem:**
Plugins and shims were still hand-rolling JSON meta reads/writes in multiple places.

**Impact:**
The codebase still felt like old phase code and new plugin code were coexisting without a shared utility layer.

**Resolution:**
Added `repograph.plugins.utils.meta_io` with:
- `meta_dir()`
- `meta_path()`
- `read_meta_json()`
- `write_meta_json()`

Then rewired several exporters, static analyzers, and shim phases to use it.

---

### RG2-SURFACE-01 — manifests still exposed old mental model only
**Files:**
- `repograph/plugins/features.py`
- `repograph/plugins/__init__.py`
- `repograph/plugins/README.md`

**Problem:**
The codebase still talked about `analyzers` generically even though the architecture now clearly distinguishes sync-time static analyzers from demand-side wrappers.

**Impact:**
Even if the implementation was cleaner, the public/internal naming still suggested a half-finished migration.

**Resolution:**
The manifest surface exposes:
- `static_analyzers`
- `demand_analyzers`

A duplicate `analyzers` key was later removed from `built_in_plugin_manifests()`; use `demand_analyzers` only.

---

## What changed in this pass

### RG2-DELIVER-01 — canonical static analyzer identities
Static analyzer manifests use `static_analyzer.*` ids. Static plugins **do not** register `analyzer.*` aliases (those strings are reserved for demand-side plugins). Parsers use `ParserAdapter` (formerly “legacy” wrapper name) to wrap `BaseParser` implementations.

### RG2-DELIVER-02 — registry alias support
`PluginRegistry` now resolves canonical IDs and manifest aliases cleanly. Manifest listings remain canonical; aliases are for lookup compatibility only.

### RG2-DELIVER-03 — explicit lifecycle order
The scheduler now resolves plugin order using manifest metadata instead of relying on registration order.

Current notable ordering contracts:
- `static_analyzer.pathways` runs before downstream static analyzers
- `exporter.pathway_contexts` runs after `exporter.pathways`
- `exporter.agent_guide` runs after pathway contexts, modules, and invariants
- `exporter.report_surfaces` runs after summary + key report exporters

### RG2-DELIVER-04 — centralized meta JSON helpers
The second pass removes several one-off read/write helpers and routes them through `plugins/utils/meta_io.py`.

### RG2-DELIVER-05 — manifest surface clarification
`built_in_plugin_manifests()` returns `parsers`, `framework_adapters`, `static_analyzers`, `demand_analyzers`, `evidence_producers`, `exporters`, `tracers`, and `dynamic_analyzers` — not a separate duplicate `analyzers` bucket.

---

## Resulting shape

After this pass, the codebase reads more clearly as:

- `pipeline/runner.py` — builds the graph and fires ordered hooks
- `plugins/static_analyzers/*` — sync-time graph enrichment with canonical IDs
- `plugins/demand_analyzers/*` — service/query-time analyzers
- `plugins/exporters/*` — ordered artifact production
- `plugins/utils/meta_io.py` — shared artifact IO primitives (where present)

---

## Remaining closure work

### RG2-NEXT-01 — retire or formalize legacy folders that are now pure shims
Candidates:
- `repograph/analysis/event_topology.py`
- `repograph/analysis/async_tasks.py`
- `repograph/pipeline/phases/p19_event_topology.py`
- `repograph/pipeline/phases/p20_async_tasks.py`

### RG2-NEXT-02 — ~~move demand-side wrappers~~ *(done)*
Demand-side code lives under `plugins/demand_analyzers/` with canonical manifest IDs `demand_analyzer.*` and optional `aliases=("analyzer.*",)` per plugin.

### RG2-NEXT-03 — audit remaining broad exception swallowing inside plugin implementations
The second pass clarified ownership and ordering, but trust still depends on being explicit about uncertainty and failure.

### RG2-NEXT-04 — final docs alignment pass
Update all docs/screens/help text so the product narrative matches the cleaner architecture:
- canonical static analyzer IDs
- demand-side wrappers vs sync-time analyzers
- hook ordering as a declared contract

---

## Acceptance markers for this pass

This pass should be considered successful if:

1. canonical sync-time plugin IDs no longer collide with demand-side analyzer IDs
2. plugin execution order is declared by manifests, not registry insertion order
3. meta JSON reads/writes are visibly centralized
4. manifests present the plugin families in a way that matches the intended architecture
5. the codebase *looks* less transitional when inspected folder-by-folder
