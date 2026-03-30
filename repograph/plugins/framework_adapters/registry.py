from __future__ import annotations

import threading

from repograph.core.plugin_framework import FrameworkAdapterPlugin, PluginRegistry
from repograph.plugins.discovery import FRAMEWORK_ADAPTER_ORDER, iter_build_plugins

_FRAMEWORK_ADAPTER_REGISTRY: PluginRegistry[FrameworkAdapterPlugin] = PluginRegistry("framework_adapter")
_DEFAULTS_REGISTERED = False
_DEFAULTS_LOCK = threading.Lock()


def get_registry() -> PluginRegistry[FrameworkAdapterPlugin]:
    ensure_default_framework_adapters_registered()
    return _FRAMEWORK_ADAPTER_REGISTRY


def register_framework_adapter(plugin: FrameworkAdapterPlugin, *, replace: bool = False) -> None:
    _FRAMEWORK_ADAPTER_REGISTRY.register(plugin, replace=replace)


def get_framework_adapter(plugin_id: str) -> FrameworkAdapterPlugin | None:
    ensure_default_framework_adapters_registered()
    return _FRAMEWORK_ADAPTER_REGISTRY.get(plugin_id)


def framework_adapter_manifests() -> list[dict]:
    ensure_default_framework_adapters_registered()
    return _FRAMEWORK_ADAPTER_REGISTRY.manifests()


def ensure_default_framework_adapters_registered() -> None:
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return
    with _DEFAULTS_LOCK:
        if _DEFAULTS_REGISTERED:
            return
        for build in iter_build_plugins(
            "repograph.plugins.framework_adapters",
            FRAMEWORK_ADAPTER_ORDER,
        ):
            register_framework_adapter(build())
        _DEFAULTS_REGISTERED = True
