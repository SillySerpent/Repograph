# Exporters (`kind: exporter`)

## Responsibility

Write artifacts and views after evidence is produced (`on_export`): summaries, pathway context docs, agent guides, module maps, runtime overlays, report surfaces, etc. Subpackages (e.g. `pathway_contexts/`, `doc_warnings/`) each implement one exporter.

## Extending

1. Add `repograph/plugins/exporters/<name>/plugin.py` (or package with `plugin.py`) exposing `build_plugin() -> ExporterPlugin`.
2. Implement `export(self, **kwargs)`; typical kwargs include `store`, `repograph_dir`, `config`.
3. Set `manifest.id` to `exporter.<name>` (match existing naming in this tree).
4. Append `<name>` to `EXPORTER_ORDER` in `discovery.py`.

## Example (sketch)

```python
from repograph.core.plugin_framework import ExporterPlugin, PluginManifest

class MyExporter(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.my_view",
        kind="exporter",
        hooks=("on_export",),
        requires=("symbols",),
        produces=("artefacts.my_view",),
    )
    def export(self, **kwargs): return {"written": []}
def build_plugin(): return MyExporter()
```

## Requirements

[`docs/plugins/AUTHORING.md`](../../../docs/plugins/AUTHORING.md), [`DISCOVERY.md`](../../../docs/plugins/DISCOVERY.md), `contracts.py` (`ExporterPlugin`). Large exporter families may split helpers into sibling modules (see `pathway_contexts/`).
