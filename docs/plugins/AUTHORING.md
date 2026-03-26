# Authoring RepoGraph plugins

Built-in plugins live under [`repograph/plugins/`](../../repograph/plugins/README.md)
and are registered via [`discovery.py`](../../repograph/plugins/discovery.py) (ordered
`build_plugin` imports). This document describes **how to implement** each **kind**.

## Shared rules

1. **Factory:** expose `build_plugin() -> RepoGraphPlugin` in `plugin.py`.
2. **Manifest:** set `id`, `name`, `kind`, `hooks`, `requires` / `produces` consistently
   with [`PluginManifest`](../../repograph/core/plugin_framework/contracts.py).
3. **Hooks:** only hooks listed on the manifest are dispatched by
   [`PluginHookScheduler`](../../repograph/core/plugin_framework/hooks.py).
4. **Ordering:** use `manifest.order`, `after`, `before` when multiple plugins share a hook.
5. **Tests:** add or extend tests under `tests/`; for new built-ins, append the package
   name to the appropriate `*_ORDER` tuple in `discovery.py` and run
   `scripts/check_plugin_coverage.py`.

## Plugin IDs and aliases

- **Canonical ids** use a family prefix: `parser.*`, `static_analyzer.*`, `demand_analyzer.*`, `exporter.*`, etc.
- **Demand analyzers** should use `id="demand_analyzer.<name>"`. Optional `manifest.aliases=("analyzer.<name>",)` keeps older `run_analyzer_plugin("analyzer.<name>")` call strings working via `PluginRegistry.resolve_id`.
- **Static analyzers** use `static_analyzer.*` only; they do not register `analyzer.*` aliases (those names are for demand-side plugins).

## Kind reference

| Kind | Base class | Primary hook(s) | Method(s) |
|------|------------|-------------------|-----------|
| `parser` | `ParserPlugin` | `on_file_parsed` | `parse_file` |
| `framework_adapter` | `FrameworkAdapterPlugin` | `on_file_parsed` | `inspect` |
| `static_analyzer` | `StaticAnalyzerPlugin` | `on_graph_built` | `analyze` |
| `demand_analyzer` | `DemandAnalyzerPlugin` | `on_analysis` | `analyze` |
| `evidence_producer` | `EvidenceProducerPlugin` | `on_evidence` | `produce` |
| `exporter` | `ExporterPlugin` | `on_export` | `export` |
| `dynamic_analyzer` | `DynamicAnalyzerPlugin` | `on_traces_collected` | `analyze_traces` |
| `tracer` | `TracerPlugin` | `on_tracer_install`, `on_tracer_collect` | `install`, `collect` |

**Experimental pipeline phases** (optional, not part of hook scheduler) implement
[`PipelinePhasePlugin`](../../repograph/core/plugin_framework/pipeline_phases.py) and
are listed in [`pipeline_phases/registry.py`](../../repograph/plugins/pipeline_phases/registry.py);
they run only when `RunConfig.experimental_phase_plugins` is `True`.

## Examples

Minimal **reference implementations** (not loaded in production) live in
[`repograph/plugins/examples/`](../../repograph/plugins/examples/README.md).

## Further reading

- [`DISCOVERY.md`](DISCOVERY.md) — registration order and entry points
- [`PLUGIN_PHASES_AND_HOOKS.md`](../architecture/PLUGIN_PHASES_AND_HOOKS.md) — hooks vs experimental phases
