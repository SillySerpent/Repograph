"""REFERENCE ONLY — not registered in production.

How to implement an evidence producer plugin
--------------------------------------------
1. Subclass ``EvidenceProducerPlugin``.
2. Set ``kind="evidence_producer"``, ``hooks=("on_evidence",)``.
3. Implement ``produce(**kwargs)`` — receives ``store``, ``repo_path``, ``repograph_dir``.
4. Return a dict summarising collected evidence (shape is contract-specific).
5. Register: append to ``EVIDENCE_PRODUCER_ORDER`` in ``discovery.py``.

See ``plugins/evidence_producers/declared_dependencies/plugin.py``.
"""
from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import EvidenceProducerPlugin, PluginManifest


class ExampleEvidenceProducerPlugin(EvidenceProducerPlugin):
    manifest = PluginManifest(
        id="evidence_producer.example_reference",
        name="Example evidence producer (reference)",
        kind="evidence_producer",
        description="Reference stub — not used in production.",
        requires=("symbols",),
        produces=("evidence.example",),
        hooks=("on_evidence",),
    )

    def produce(self, **kwargs: Any) -> dict[str, Any]:
        return {"kind": "evidence.example", "count": 0}


def build_plugin() -> ExampleEvidenceProducerPlugin:
    return ExampleEvidenceProducerPlugin()
