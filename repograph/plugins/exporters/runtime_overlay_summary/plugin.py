from __future__ import annotations
from repograph.core.evidence import CAP_RUNTIME_OVERLAY, SOURCE_OBSERVED, evidence_tag
from repograph.core.plugin_framework import ExporterPlugin, PluginManifest
class RuntimeOverlaySummaryExporterPlugin(ExporterPlugin):
    manifest=PluginManifest(id="exporter.runtime_overlay_summary",name="Runtime overlay summary exporter",kind="exporter",description="Summarizes optional observed/runtime evidence and declares augment-not-replace overlay semantics.",requires=(CAP_RUNTIME_OVERLAY,),produces=(evidence_tag(CAP_RUNTIME_OVERLAY,SOURCE_OBSERVED).kind,),hooks=("on_export",), order=190,)
    def export(self, **kwargs):
        service=kwargs.get("service")
        if service is not None:
            observed=service.run_evidence_plugin("evidence.runtime_overlay")
        else:
            from pathlib import Path
            repograph_dir = Path(kwargs.get("repograph_dir") or ".repograph")
            runtime_dir = repograph_dir / "runtime"
            traces = sorted(p.relative_to(repograph_dir).as_posix() for p in runtime_dir.rglob("*") if p.is_file()) if runtime_dir.exists() else []
            observed={"kind":"runtime_overlay","enabled":runtime_dir.exists(),"runtime_dir":"runtime","trace_files":traces,"count":len(traces),"overlay_mode":"augment_not_replace","replaces_static":False,"evidence":evidence_tag(CAP_RUNTIME_OVERLAY,SOURCE_OBSERVED).as_dict()}
        return {"kind":"runtime_overlay_summary","overlay_mode":"augment_not_replace","replaces_static":False,"merge_keys":["path","symbol","entrypoint"],"precedence":["observed","static","framework","declared","inferred"],"observed":observed,"evidence":evidence_tag(CAP_RUNTIME_OVERLAY,SOURCE_OBSERVED).as_dict(),}

def build_plugin()->RuntimeOverlaySummaryExporterPlugin:
    return RuntimeOverlaySummaryExporterPlugin()
