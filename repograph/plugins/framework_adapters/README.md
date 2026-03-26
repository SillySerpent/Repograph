# Framework adapters (`kind: framework_adapter`)

## Responsibility

After a file is parsed, enrich `ParsedFile` with framework-specific hints (e.g. Flask routes, FastAPI routers, React components). Adapters share the `on_file_parsed` hook with parsers but run afterward to attach `framework_hints` and optional `plugin_artifacts`.

## Extending

1. Add `repograph/plugins/framework_adapters/<name>/plugin.py` with `build_plugin() -> FrameworkAdapterPlugin`.
2. Implement `inspect(file_record=..., parsed_file=...)` (or the hook method matched by the scheduler for this kind).
3. Register languages/frameworks in the manifest (`languages`, `frameworks` as appropriate).
4. Append the package name to `FRAMEWORK_ADAPTER_ORDER` in `discovery.py`.

## Example (sketch)

```python
from repograph.core.plugin_framework import FrameworkAdapterPlugin, PluginManifest

class MyFrameworkAdapter(FrameworkAdapterPlugin):
    manifest = PluginManifest(
        id="framework_adapter.myfw",
        kind="framework_adapter",
        languages=("python",),
        frameworks=("myfw",),
        hooks=("on_file_parsed",),
        requires=("symbols",),
        produces=("framework_hints",),
    )
    def inspect(self, **kwargs): return {"frameworks": ["myfw"], ...}
def build_plugin(): return MyFrameworkAdapter()
```

## Requirements

[`docs/plugins/AUTHORING.md`](../../../docs/plugins/AUTHORING.md), [`DISCOVERY.md`](../../../docs/plugins/DISCOVERY.md), `contracts.py` (`FrameworkAdapterPlugin`).
