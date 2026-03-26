# Dynamic analyzers (`kind: dynamic_analyzer`)

## Responsibility

Consume collected runtime traces (`on_traces_collected`) and merge observations into the graph or evidence model (coverage, runtime overlay, etc.). Only run when trace files exist under `.repograph/runtime/`.

## Extending

1. Add `repograph/plugins/dynamic_analyzers/<name>/plugin.py` with `build_plugin() -> DynamicAnalyzerPlugin`.
2. Implement `analyze_traces(self, trace_dir, store, **kwargs)` per `contracts.py`.
3. Declare `trace_formats` on the manifest when applicable.
4. Append `<name>` to `DYNAMIC_ANALYZER_ORDER` in `discovery.py`.

## Example (sketch)

```python
from pathlib import Path
from repograph.core.plugin_framework import DynamicAnalyzerPlugin, PluginManifest
from repograph.graph_store.store import GraphStore

class MyDynamicPlugin(DynamicAnalyzerPlugin):
    manifest = PluginManifest(
        id="dynamic_analyzer.my_overlay",
        kind="dynamic_analyzer",
        hooks=("on_traces_collected",),
        requires=("call_edges",),
        produces=("findings.runtime",),
    )
    def analyze_traces(self, trace_dir: Path | str, store: GraphStore, **kwargs): return {}
def build_plugin(): return MyDynamicPlugin()
```

## Requirements

[`docs/plugins/AUTHORING.md`](../../../docs/plugins/AUTHORING.md), [`DISCOVERY.md`](../../../docs/plugins/DISCOVERY.md), `contracts.py` (`DynamicAnalyzerPlugin`).
