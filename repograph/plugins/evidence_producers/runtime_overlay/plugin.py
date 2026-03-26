from __future__ import annotations

from pathlib import Path

from repograph.core.evidence import CAP_RUNTIME_OVERLAY, SOURCE_OBSERVED, evidence_tag
from repograph.core.plugin_framework import EvidenceProducerPlugin, PluginManifest


class RuntimeOverlayEvidencePlugin(EvidenceProducerPlugin):
    manifest = PluginManifest(
        id="evidence.runtime_overlay",
        name="Runtime overlay groundwork",
        kind="evidence_producer",
        description="Discovers optional runtime trace payloads without requiring dynamic analysis yet.",
        requires=("repograph_artifacts",),
        produces=(evidence_tag(CAP_RUNTIME_OVERLAY, SOURCE_OBSERVED).kind,),
        hooks=("on_evidence",),
    )

    def produce(self, **kwargs):
        service = kwargs.get("service")
        repograph_dir = Path(kwargs.get("repograph_dir") or getattr(service, "repograph_dir", ".repograph")).resolve()
        runtime_dir = repograph_dir / "runtime"
        traces = sorted(p.relative_to(repograph_dir).as_posix() for p in runtime_dir.rglob("*") if p.is_file()) if runtime_dir.exists() else []
        return {
            "kind": "runtime_overlay",
            "enabled": runtime_dir.exists(),
            "runtime_dir": runtime_dir.relative_to(repograph_dir).as_posix() if runtime_dir.exists() else "runtime",
            "trace_files": traces,
            "count": len(traces),
            "overlay_mode": "augment_not_replace",
            "replaces_static": False,
            "evidence": evidence_tag(CAP_RUNTIME_OVERLAY, SOURCE_OBSERVED).as_dict(),
        }


def build_plugin() -> RuntimeOverlayEvidencePlugin:
    return RuntimeOverlayEvidencePlugin()
