from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import ExporterPlugin, PluginManifest


class PathwaysExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.pathways",
        name="Pathways exporter",
        kind="exporter",
        description="Compatibility exporter wrapper for pathway listings.",
        requires=("pathways",),
        produces=("artifacts.pathways_json",),
        hooks=("on_export",),
        order=110,
    )

    def export(self, **kwargs: Any) -> dict[str, Any]:
        service = kwargs.get("service")
        min_confidence = kwargs.get("min_confidence", 0.0)
        include_tests = kwargs.get("include_tests", False)
        if service is not None:
            out = service.pathways(
                min_confidence=min_confidence, include_tests=include_tests
            )
            return out if isinstance(out, dict) else {"data": out}
        store = kwargs.get("store")
        if store is None:
            return {"data": []}
        rows = store.get_all_pathways()
        filtered = [r for r in rows if (r.get("confidence") or 0.0) >= min_confidence]
        if not include_tests:
            filtered = [r for r in filtered if r.get("source") != "auto_detected_test"]
        return {"data": filtered}


def build_plugin() -> PathwaysExporterPlugin:
    return PathwaysExporterPlugin()
