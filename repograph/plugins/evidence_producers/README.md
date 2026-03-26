# Evidence producers (`kind: evidence_producer`)

## Responsibility

Collect structured evidence after the graph is built (`on_evidence`): declared dependencies, config surfaces, runtime-overlay inputs, etc. Output feeds exporters and downstream consumers.

## Extending

1. Add `repograph/plugins/evidence_producers/<name>/plugin.py` with `build_plugin() -> EvidenceProducerPlugin`.
2. Implement `produce(self, **kwargs)` with `store`, `repo_path`, `repograph_dir` as provided by the runner.
3. Append `<name>` to `EVIDENCE_PRODUCER_ORDER` in `discovery.py` (registration is automatic via `evidence_producers/registry.py`).

## Example (sketch)

```python
from repograph.core.plugin_framework import EvidenceProducerPlugin, PluginManifest

class MyEvidencePlugin(EvidenceProducerPlugin):
    manifest = PluginManifest(
        id="evidence_producer.my_evidence",
        kind="evidence_producer",
        hooks=("on_evidence",),
        requires=("symbols",),
        produces=("evidence.my_kind",),
    )
    def produce(self, **kwargs): return {"items": []}
def build_plugin(): return MyEvidencePlugin()
```

## Requirements

[`docs/plugins/AUTHORING.md`](../../../docs/plugins/AUTHORING.md), [`DISCOVERY.md`](../../../docs/plugins/DISCOVERY.md), `contracts.py` (`EvidenceProducerPlugin`).
