from __future__ import annotations

from repograph.core.plugin_framework import DemandAnalyzerPlugin, PluginRegistry
from repograph.plugins.discovery import DEMAND_ANALYZER_ORDER, iter_build_plugins

_ANALYZER_REGISTRY: PluginRegistry[DemandAnalyzerPlugin] = PluginRegistry("demand_analyzer")
_DEFAULTS_REGISTERED = False


def get_registry() -> PluginRegistry[DemandAnalyzerPlugin]:
    ensure_default_analyzers_registered()
    return _ANALYZER_REGISTRY


def register_analyzer(plugin: DemandAnalyzerPlugin, *, replace: bool = False) -> None:
    _ANALYZER_REGISTRY.register(plugin, replace=replace)


def get_analyzer(plugin_id: str) -> DemandAnalyzerPlugin | None:
    ensure_default_analyzers_registered()
    return _ANALYZER_REGISTRY.get(plugin_id)


def analyzer_manifests() -> list[dict]:
    ensure_default_analyzers_registered()
    return _ANALYZER_REGISTRY.manifests()


def ensure_default_analyzers_registered() -> None:
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return
    for build in iter_build_plugins(
        "repograph.plugins.demand_analyzers",
        DEMAND_ANALYZER_ORDER,
    ):
        register_analyzer(build())
    _DEFAULTS_REGISTERED = True
