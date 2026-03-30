"""Dynamic analyzer plugin registry.

Dynamic analyzers consume runtime trace files produced by TracerPlugins.
Built-ins are registered here; third-party analyzers call
register_dynamic_analyzer() to add themselves.
"""
from __future__ import annotations

import threading

from repograph.core.plugin_framework import DynamicAnalyzerPlugin, PluginRegistry
from repograph.plugins.discovery import DYNAMIC_ANALYZER_ORDER, iter_build_plugins

_REGISTRY: PluginRegistry[DynamicAnalyzerPlugin] = PluginRegistry("dynamic_analyzer")
_DEFAULTS_REGISTERED = False
_DEFAULTS_LOCK = threading.Lock()


def get_registry() -> PluginRegistry[DynamicAnalyzerPlugin]:
    ensure_default_dynamic_analyzers_registered()
    return _REGISTRY


def register_dynamic_analyzer(plugin: DynamicAnalyzerPlugin, *, replace: bool = False) -> None:
    _REGISTRY.register(plugin, replace=replace)


def ensure_default_dynamic_analyzers_registered() -> None:
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return
    with _DEFAULTS_LOCK:
        if _DEFAULTS_REGISTERED:
            return
        for build in iter_build_plugins(
            "repograph.plugins.dynamic_analyzers",
            DYNAMIC_ANALYZER_ORDER,
        ):
            register_dynamic_analyzer(build())
        _DEFAULTS_REGISTERED = True
