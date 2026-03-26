# Example plugins (reference only)

This directory contains **minimal, importable** `plugin.py` files—one per plugin **kind**.
They are **not** registered in [`discovery.py`](../discovery.py); they exist so you can
copy patterns and run [`tests/unit/test_plugin_examples_load.py`](../../../tests/unit/test_plugin_examples_load.py).

| Directory | Kind | Notes |
|-----------|------|--------|
| `parser/` | `parser` | Returns an empty `ParsedFile` for any file |
| `framework_adapter/` | `framework_adapter` | No-op `inspect` |
| `static_analyzer/` | `static_analyzer` | Empty findings list |
| `demand_analyzer/` | `demand_analyzer` | Empty findings list |
| `evidence_producer/` | `evidence_producer` | Empty evidence dict |
| `exporter/` | `exporter` | No-op export summary |
| `dynamic_analyzer/` | `dynamic_analyzer` | Empty overlay list |
| `tracer/` | `tracer` | No-op install/collect |
| `pipeline_phase/` | (experimental) | No-op `run()` for `PipelinePhasePlugin` protocol |

To ship a real plugin, add a package under the appropriate `parsers/`, `exporters/`, etc.
tree, implement behaviour, then append the subpackage name to the matching `*_ORDER` in
`discovery.py` (and add tests).
