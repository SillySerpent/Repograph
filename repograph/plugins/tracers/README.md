# Tracers (`kind: tracer`)

## Responsibility

`repograph trace install` / `collect` integration: write instrumentation config (`on_tracer_install`) and finalize trace outputs (`on_tracer_collect`). Tracers do not parse the graph; they prepare and collect runtime data.

## Extending

1. Add `repograph/plugins/tracers/<name>/plugin.py` with `build_plugin() -> TracerPlugin`.
2. Implement `install` and `collect` as required by `TracerPlugin` in `contracts.py`.
3. Register via the tracer registry pattern used in this repo (`tracers/_registry.py` + lifecycle).

## Example (sketch)

```python
from pathlib import Path
from repograph.core.plugin_framework import TracerPlugin, PluginManifest

class MyTracer(TracerPlugin):
    manifest = PluginManifest(
        id="tracer.my_runtime",
        kind="tracer",
        hooks=("on_tracer_install", "on_tracer_collect"),
        produces=("traces.my_format",),
    )
    def install(self, repo_root, trace_dir, **kwargs): ...
    def collect(self, trace_dir, **kwargs): return []
def build_plugin(): return MyTracer()
```

## Requirements

[`docs/plugins/AUTHORING.md`](../../../docs/plugins/AUTHORING.md), `contracts.py` (`TracerPlugin`).
