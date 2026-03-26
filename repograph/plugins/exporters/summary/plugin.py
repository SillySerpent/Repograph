from __future__ import annotations

from repograph.core.plugin_framework import ExporterPlugin, PluginManifest


class SummaryExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.summary",
        name="Summary exporter",
        kind="exporter",
        description="Compatibility exporter wrapper for repo summary/status payloads.",
        requires=("stats",),
        produces=("artifacts.summary_json",),
        hooks=("on_export",),
        order=180,
    )

    def export(self, **kwargs):
        service = kwargs.get("service")
        if service is not None:
            return service.status()
        store = kwargs.get("store")
        if store is None:
            return {"initialized": False}
        stats = store.get_stats()
        stats["initialized"] = True
        return stats


def build_plugin() -> SummaryExporterPlugin:
    return SummaryExporterPlugin()
