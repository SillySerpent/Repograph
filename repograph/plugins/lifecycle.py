"""Plugin lifecycle — single source of truth for scheduler construction.

All plugin registries funnel through here.  Import get_hook_scheduler() to
get the singleton scheduler, ensure_all_plugins_registered() to boot
all built-in plugins, and reset_hook_scheduler() to clear state between
test runs or after a repograph clean.
"""
from __future__ import annotations

from functools import lru_cache

from repograph.core.plugin_framework import PluginHookScheduler


@lru_cache(maxsize=1)
def get_hook_scheduler() -> PluginHookScheduler:
    """Return the singleton PluginHookScheduler.

    All built-in plugin families are registered before the scheduler is
    returned so callers can immediately fire any hook.
    """
    from repograph.plugins.parsers._registry import get_registry as parsers
    from repograph.plugins.framework_adapters.registry import get_registry as adapters
    from repograph.plugins.static_analyzers._registry import get_registry as static_analyzers
    from repograph.plugins.demand_analyzers.registry import get_registry as demand_analyzers
    from repograph.plugins.dynamic_analyzers._registry import get_registry as dynamic_analyzers
    from repograph.plugins.evidence_producers.registry import get_registry as evidence
    from repograph.plugins.exporters._registry import get_registry as exporters
    from repograph.plugins.tracers._registry import get_registry as tracers

    return PluginHookScheduler({
        "parser":           parsers(),
        "framework_adapter": adapters(),
        "static_analyzer":  static_analyzers(),
        "demand_analyzer":  demand_analyzers(),
        "dynamic_analyzer": dynamic_analyzers(),
        "evidence_producer": evidence(),
        "exporter":         exporters(),
        "tracer":           tracers(),
    })


def ensure_all_plugins_registered() -> None:
    """Boot all built-in plugin families and fire on_registry_bootstrap.

    Safe to call multiple times — the lru_cache means bootstrap fires exactly
    once per process lifetime (or after reset_hook_scheduler()).
    """
    from repograph.plugins.parsers._registry import ensure_default_parsers_registered
    from repograph.plugins.framework_adapters.registry import ensure_default_framework_adapters_registered
    from repograph.plugins.static_analyzers._registry import ensure_default_static_analyzers_registered
    from repograph.plugins.demand_analyzers.registry import ensure_default_analyzers_registered
    from repograph.plugins.dynamic_analyzers._registry import ensure_default_dynamic_analyzers_registered
    from repograph.plugins.evidence_producers.registry import ensure_default_evidence_producers_registered
    from repograph.plugins.exporters._registry import ensure_default_exporters_registered
    from repograph.plugins.tracers._registry import ensure_default_tracers_registered

    ensure_default_parsers_registered()
    ensure_default_framework_adapters_registered()
    ensure_default_static_analyzers_registered()
    ensure_default_analyzers_registered()
    ensure_default_dynamic_analyzers_registered()
    ensure_default_evidence_producers_registered()
    ensure_default_exporters_registered()
    ensure_default_tracers_registered()

    get_hook_scheduler().fire("on_registry_bootstrap")


def reset_hook_scheduler() -> None:
    """Clear the scheduler cache.

    Called by repograph clean and test teardown to reset plugin state.
    """
    get_hook_scheduler.cache_clear()
