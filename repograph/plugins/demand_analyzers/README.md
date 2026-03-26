# Demand analyzers (`kind: demand_analyzer`)

## Responsibility

Query-time / service-time analysis: consumers call `RepoGraphService.run_analyzer_plugin(id, ...)` or the scheduler runs `on_analysis`. These plugins use `service` (and repo context) to return lists of findings or structured evidence. Canonical manifest ids are `demand_analyzer.<name>`; legacy `analyzer.<name>` ids are kept as optional **aliases** on each plugin for compatibility.

## Extending

1. Add `repograph/plugins/demand_analyzers/<name>/plugin.py` with `build_plugin() -> DemandAnalyzerPlugin`.
2. Implement `analyze(self, **kwargs)`; expect `service=` from callers.
3. Set `id="demand_analyzer.<name>"`, `kind="demand_analyzer"`, `hooks=("on_analysis",)`, and optional `aliases=("analyzer.<name>",)` if you need backward compatibility.
4. Append `<name>` to `DEMAND_ANALYZER_ORDER` in `discovery.py`.

## Example (sketch)

```python
from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginManifest

class MyDemandPlugin(DemandAnalyzerPlugin):
    manifest = PluginManifest(
        id="demand_analyzer.my_rule",
        kind="demand_analyzer",
        hooks=("on_analysis",),
        requires=("repo_files",),
        produces=("findings.my_rule",),
        aliases=("analyzer.my_rule",),
    )
    def analyze(self, **kwargs):
        service = kwargs.get("service")
        if service is None:
            return []
        return []
def build_plugin(): return MyDemandPlugin()
```

## Requirements

[`docs/plugins/AUTHORING.md`](../../../docs/plugins/AUTHORING.md), [`DISCOVERY.md`](../../../docs/plugins/DISCOVERY.md), `contracts.py` (`DemandAnalyzerPlugin`). Rule-pack integration: `repograph/plugins/rules/`.
