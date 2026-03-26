from __future__ import annotations

from repograph.core.evidence import CAP_REPORT_SURFACES, SOURCE_STATIC, evidence_tag
from repograph.core.plugin_framework import ExporterPlugin, PluginManifest
from repograph.plugins.utils import read_meta_json





class ReportSurfacesExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.report_surfaces",
        name="Report surfaces exporter",
        kind="exporter",
        description="Groups stable report/meta surfaces for downstream consumers.",
        requires=("repo_files",),
        produces=(evidence_tag(CAP_REPORT_SURFACES, SOURCE_STATIC).kind,),
        hooks=("on_export",),
        order=210,
        after=("exporter.summary", "exporter.entry_points", "exporter.doc_warnings", "exporter.observed_runtime_findings", "exporter.runtime_overlay_summary"),
    )

    def export(self, **kwargs):
        service = kwargs.get("service")
        if service is not None:
            entry_points = service.entry_points(limit=10)
            doc_warnings = service.doc_warnings(min_severity="medium")[:10]
            duplicates = service.duplicates(min_severity="medium")[:10]
            summary = service.run_exporter_plugin("exporter.summary")
        else:
            store = kwargs.get("store")
            repograph_dir = kwargs.get("repograph_dir") or ""
            entry_points = store.get_entry_points(limit=10) if store is not None else []
            doc_warnings = read_meta_json(repograph_dir, "doc_warnings.json", [])[:10]
            duplicates = store.get_all_duplicate_symbols()[:10] if store is not None else []
            summary = {"initialized": bool(store), **(store.get_stats() if store is not None else {})}
        return {
            "kind": "report_surfaces",
            "summary": summary,
            "entry_points": {"count": len(entry_points), "top": entry_points},
            "doc_warnings": {"count": len(doc_warnings), "top": doc_warnings},
            "duplicates": {"count": len(duplicates), "top": duplicates},
            "evidence": evidence_tag(CAP_REPORT_SURFACES, SOURCE_STATIC).as_dict(),
        }


def build_plugin() -> ReportSurfacesExporterPlugin:
    return ReportSurfacesExporterPlugin()
