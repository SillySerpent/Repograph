"""Static analyzer plugin registry.

Powers the sync-time ``on_graph_built`` hook. Service/query-time analyzers live
under ``plugins/demand_analyzers/`` and register separately.
"""
from __future__ import annotations

import threading

from repograph.core.plugin_framework import PluginRegistry, StaticAnalyzerPlugin
from repograph.plugins.discovery import STATIC_ANALYZER_ORDER, iter_build_plugins

_REGISTRY: PluginRegistry[StaticAnalyzerPlugin] = PluginRegistry("static_analyzer")
_DEFAULTS_REGISTERED = False
_DEFAULTS_LOCK = threading.Lock()


def get_registry() -> PluginRegistry[StaticAnalyzerPlugin]:
    ensure_default_static_analyzers_registered()
    return _REGISTRY


def register_static_analyzer(plugin: StaticAnalyzerPlugin, *, replace: bool = False) -> None:
    _REGISTRY.register(plugin, replace=replace)


def ensure_default_static_analyzers_registered() -> None:
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return
    with _DEFAULTS_LOCK:
        if _DEFAULTS_REGISTERED:
            return
        for build in iter_build_plugins(
            "repograph.plugins.static_analyzers",
            STATIC_ANALYZER_ORDER,
        ):
            register_static_analyzer(build())
        _DEFAULTS_REGISTERED = True
