# RepoGraph plugin layout

**How to implement each plugin kind:** see [`docs/plugins/AUTHORING.md`](../docs/plugins/AUTHORING.md)
and minimal stubs under [`repograph/plugins/examples/`](examples/README.md).

RepoGraph now separates extension points into five families:

- `parsers/` — language structure extraction
- `framework_adapters/` — framework-specific post-parse enrichment
- `static_analyzers/` — sync-time post-build graph enrichers that run from pipeline context
- `evidence_producers/` — static evidence collectors and groundwork for future dynamic overlays
- `demand_analyzers/` — canonical service/query-time analyzer implementations
- `exporters/` — artifact and view producers

Lifecycle execution is coordinated through `repograph.plugins.lifecycle` and the
core `PluginHookScheduler` (see `repograph.core.plugin_framework`).

Built-in registration order is defined in [`discovery.py`](discovery.py); see
[`docs/plugins/DISCOVERY.md`](../docs/plugins/DISCOVERY.md).

The intended boundary is:
- parsers answer **what syntax/structure exists**
- framework adapters answer **what that structure means in a framework**
- evidence producers answer **what extra evidence exists around the repo/runtime**
- demand analyzers answer **what findings we can infer on demand**
- exporters answer **what stable artifacts/views we expose**

Evidence naming is stabilised in `repograph.core.evidence.taxonomy`, which defines a small set of source labels (`static`, `framework`, `declared`, `observed`, `inferred`) and shared capability names for future static/dynamic fusion.

Phase 7 adds:
- config-flow analyzers for policy/config tracing
- module/component signal analyzers for architecture drafting and import flows
- runtime overlay summary exporters that declare observed evidence as augmenting static evidence instead of replacing it


Phase 9 adds React/Next.js framework adapters, boundary-rule analysis, and a Meridian-facing intelligence snapshot service.


Phase 10 added grouped report surfaces and observed runtime findings exporters so UI consumers can use a stable evidence snapshot instead of growing around one-off fields.


Phase 11 split broad boundary/conformance logic into rule families (`contract_rules`, `boundary_shortcuts`) while preserving compatibility aggregators. Grouped intelligence snapshots now expose family summaries and richer severity policy metadata for Meridian.


## Sync-time vs demand-side analyzers

RepoGraph now keeps two analyzer families on purpose:

- `static_analyzers/` are fired by the pipeline on `on_graph_built` and must work from `store`, `parsed`, `repo_path`, and `repograph_dir`.
- `demand_analyzers/` are the canonical service/query-time analyzers used by `RepoGraphService.run_analyzer_plugin(...)` and related API/UI consumers.

Static analyzers use canonical `static_analyzer.*` ids. Demand analyzers use canonical `demand_analyzer.*` ids; older `analyzer.*` ids remain as manifest aliases for compatibility.

Use `docs/refactor/INDEX.md`, `docs/README.md`, and `docs/SURFACES.md` for current architecture and surfaces.

## Plugin ownership rule

For plugin-owned features, the plugin package is the physical home of the
feature logic as well as the registration point. Import from
`repograph.plugins.*` only.

## Testing requirements

- Each plugin package under `repograph/plugins/<kind>/<name>/` should include tests
  under `tests/` mirroring the feature (e.g. `tests/unit/test_<feature>.py`) or
  `tests/plugins/<kind>/<name>/`.
- Minimum bar for a new plugin: import `build_plugin()` (or the package’s factory),
  assert `plugin_id()` and manifest hooks match expectations, and add at least one
  smoke test for the primary hook (`analyze`, `export`, etc.) using fakes or a
  small fixture graph when applicable.
