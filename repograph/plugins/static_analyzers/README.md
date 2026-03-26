# Static analyzers (`kind: static_analyzer`)

## Responsibility

Sync-time analysis after the graph is built (`on_graph_built`). Plugins read `GraphStore` (and optional config) and emit findings or graph updates: pathways, dead code, duplicates, event topology, async tasks, etc.

## Extending

1. Add `repograph/plugins/static_analyzers/<name>/plugin.py` with `build_plugin() -> StaticAnalyzerPlugin`.
2. Implement `analyze(self, store, **kwargs)` returning structured findings or mutating the store per your plugin’s contract.
3. Set `manifest.id` to `static_analyzer.<name>`, declare `requires` / `produces`, and use `order`, `after`, `before` to order relative to other static analyzers.
4. Append `<name>` to `STATIC_ANALYZER_ORDER` in `discovery.py`.

## Example (sketch)

```python
from repograph.core.plugin_framework import StaticAnalyzerPlugin, PluginManifest
from repograph.graph_store.store import GraphStore

class MyStaticPlugin(StaticAnalyzerPlugin):
    manifest = PluginManifest(
        id="static_analyzer.my_check",
        kind="static_analyzer",
        hooks=("on_graph_built",),
        requires=("call_edges",),
        produces=("findings.my_check",),
    )
    def analyze(self, store: GraphStore | None = None, **kwargs): return []
def build_plugin(): return MyStaticPlugin()
```

## Requirements

[`docs/plugins/AUTHORING.md`](../../../docs/plugins/AUTHORING.md), [`DISCOVERY.md`](../../../docs/plugins/DISCOVERY.md), `contracts.py` (`StaticAnalyzerPlugin`). Shared helpers may live in sibling modules (e.g. `pathways/`, `_shared.py`).
