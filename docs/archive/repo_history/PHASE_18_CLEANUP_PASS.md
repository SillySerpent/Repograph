# Phase 18 — Cleanup pass

## Goal
Make the codebase read as one coherent architecture after the ownership refactors,
without changing the fundamental execution model again.

## Main closure items

### 1. Canonical demand-analyzer package
Demand-side analyzer implementations live under:

- `repograph/plugins/demand_analyzers/*`

There is **no** `repograph/plugins/analyzers/` tree anymore; older docs referred to
that name before the rename to `demand_analyzers`.

### 2. Cleaner plugin taxonomy
`DemandAnalyzerPlugin` is now a first-class contract distinct from
`StaticAnalyzerPlugin`.

- sync-time analyzers fire on `on_graph_built`
- demand-side analyzers fire on `on_analysis`

`AnalyzerPlugin` remains as a compatibility alias for the demand-side contract.

### 3. Scheduler kind strings
`PluginHookScheduler.run_plugin` expects the canonical kind name (e.g. `demand_analyzer`).
There is **no** `kind="analyzer"` string in `PluginKind`; the class alias `AnalyzerPlugin`
refers only to `DemandAnalyzerPlugin` for Python typing/imports.

### 4. Documentation refresh
The plugin README, static-analyzer registry notes, and refactor index were
updated so the repo no longer claims the old package layout as if it were still
canonical.

## Result
The repository now reads more consistently as:

- `plugins/static_analyzers/*` — sync-time graph enrichment
- `plugins/demand_analyzers/*` — service/query-time analyzer logic
- `plugins/exporters/*` — output surface generation

## Remaining optional work
- remove compatibility façades once downstream integrations no longer import them
- trim or archive older phase notes that describe now-superseded intermediate states
- tighten broad exception handling in plugin implementations where trust matters most
