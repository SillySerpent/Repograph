from __future__ import annotations

import threading

from repograph.core.plugin_framework import ExporterPlugin, PluginRegistry
from repograph.plugins.discovery import EXPORTER_ORDER, iter_build_plugins

_EXPORTER_REGISTRY: PluginRegistry[ExporterPlugin] = PluginRegistry("exporter")
_DEFAULTS_REGISTERED = False
_DEFAULTS_LOCK = threading.Lock()


def get_registry() -> PluginRegistry[ExporterPlugin]:
    ensure_default_exporters_registered()
    return _EXPORTER_REGISTRY


def register_exporter(plugin: ExporterPlugin, *, replace: bool = False) -> None:
    _EXPORTER_REGISTRY.register(plugin, replace=replace)


def get_exporter(plugin_id: str) -> ExporterPlugin | None:
    ensure_default_exporters_registered()
    return _EXPORTER_REGISTRY.get(plugin_id)


def exporter_manifests() -> list[dict]:
    ensure_default_exporters_registered()
    return _EXPORTER_REGISTRY.manifests()


def ensure_default_exporters_registered() -> None:
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return
    with _DEFAULTS_LOCK:
        if _DEFAULTS_REGISTERED:
            return
        for build in iter_build_plugins(
            "repograph.plugins.exporters",
            EXPORTER_ORDER,
        ):
            register_exporter(build())
        _DEFAULTS_REGISTERED = True
