from __future__ import annotations

from typing import Any

from repograph.core.plugin_framework import ExporterPlugin, PluginManifest
from repograph.plugins.utils import read_meta_json


class AsyncTasksExporterPlugin(ExporterPlugin):
    manifest = PluginManifest(
        id="exporter.async_tasks",
        name="Async tasks exporter",
        kind="exporter",
        description="Compatibility exporter wrapper for async task metadata.",
        requires=("meta.async_tasks",),
        produces=("artifacts.async_tasks_json",),
        hooks=("on_export",),
        order=150,
    )

    def export(self, **kwargs: Any) -> dict[str, Any]:
        service = kwargs.get("service")
        if service is not None:
            out = service.async_tasks()
            return out if isinstance(out, dict) else {"data": out}
        repograph_dir = kwargs.get("repograph_dir") or ""
        if not repograph_dir:
            return {"data": []}
        raw = read_meta_json(repograph_dir, "async_tasks.json", [])
        return raw if isinstance(raw, dict) else {"data": raw}


def build_plugin() -> AsyncTasksExporterPlugin:
    return AsyncTasksExporterPlugin()
