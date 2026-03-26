"""Tracer plugin registry.

Tracers instrument a repository to produce execution trace files.
Built-ins are registered here; third-party tracers call register_tracer().
"""
from __future__ import annotations

from repograph.core.plugin_framework import PluginRegistry, TracerPlugin

_REGISTRY: PluginRegistry[TracerPlugin] = PluginRegistry("tracer")
_DEFAULTS_REGISTERED = False


def get_registry() -> PluginRegistry[TracerPlugin]:
    ensure_default_tracers_registered()
    return _REGISTRY


def register_tracer(plugin: TracerPlugin, *, replace: bool = False) -> None:
    _REGISTRY.register(plugin, replace=replace)


def ensure_default_tracers_registered() -> None:
    global _DEFAULTS_REGISTERED
    if _DEFAULTS_REGISTERED:
        return
    _DEFAULTS_REGISTERED = True
    from repograph.plugins.dynamic_analyzers.coverage_tracer.plugin import build_plugin as build_coverage
    register_tracer(build_coverage())
