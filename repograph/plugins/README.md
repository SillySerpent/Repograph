# RepoGraph Plugins

RepoGraph uses a plugin architecture for parsing, analysis, evidence, exporting,
and runtime tracing.

## Start here

- Authoring guide: [`docs/plugins/AUTHORING.md`](../../docs/plugins/AUTHORING.md)
- Discovery and registration order: [`docs/plugins/DISCOVERY.md`](../../docs/plugins/DISCOVERY.md)
- Core lifecycle wiring: `repograph/plugins/lifecycle.py`
- Hook contracts and plugin types: `repograph/core/plugin_framework/contracts.py`

## Plugin families

- `parsers/` - parse source files into structured symbols
- `framework_adapters/` - enrich parsed files with framework-specific hints
- `static_analyzers/` - run at sync time on `on_graph_built`
- `evidence_producers/` - run on `on_evidence`
- `exporters/` - write artifacts on `on_export`
- `demand_analyzers/` - query/service-time analyzers (`on_analysis`)
- `dynamic_analyzers/` - consume runtime traces (`on_traces_collected`)
- `tracers/` - install/collect trace instrumentation
- `pipeline_phases/` - optional experimental phases (separate SPI)

## Sync-time vs demand-side analyzers

- `static_analyzers/*` run during sync through lifecycle hooks and operate on store/parsed/repo context.
- `demand_analyzers/*` run on-demand via service callers such as `RepoGraphService.run_analyzer_plugin(...)`.

Canonical ids:

- static analyzers: `static_analyzer.*`
- demand analyzers: `demand_analyzer.*` (with optional legacy `analyzer.*` aliases)

## Testing expectations

- Add tests for every new plugin package.
- Minimum bar: import factory (`build_plugin()`), verify manifest/plugin id, and add one smoke test for the primary hook method.
