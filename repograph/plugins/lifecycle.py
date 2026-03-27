"""Plugin lifecycle — single source of truth for scheduler construction.

All plugin registries funnel through here.  Import get_hook_scheduler() to
get the singleton scheduler, ensure_all_plugins_registered() to boot
all built-in plugins, and reset_hook_scheduler() to clear state between
test runs or after a repograph clean.
"""
from __future__ import annotations

import threading

from repograph.core.plugin_framework import PluginHookScheduler
from repograph.observability import get_logger

_logger = get_logger(__name__, subsystem="plugins")

# Double-checked locking for a true singleton.
# lru_cache is NOT used because it does NOT prevent concurrent execution of the
# function body — it only protects cache lookup/storage, so two threads can race
# to construct separate scheduler instances.
_scheduler_lock = threading.Lock()
_scheduler: PluginHookScheduler | None = None

# Separate lock for plugin registration (ensure_all_plugins_registered).
_registration_lock = threading.Lock()
_registration_done = False


def _run_registrations() -> None:
    """Internal: call all ensure_default_* functions.  Must be called under _registration_lock."""
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


def _build_scheduler() -> PluginHookScheduler:
    """Internal: construct a fully-configured PluginHookScheduler from current registries."""
    from repograph.plugins.parsers._registry import get_registry as parsers
    from repograph.plugins.framework_adapters.registry import get_registry as adapters
    from repograph.plugins.static_analyzers._registry import get_registry as static_analyzers
    from repograph.plugins.demand_analyzers.registry import get_registry as demand_analyzers
    from repograph.plugins.dynamic_analyzers._registry import get_registry as dynamic_analyzers
    from repograph.plugins.evidence_producers.registry import get_registry as evidence
    from repograph.plugins.exporters._registry import get_registry as exporters
    from repograph.plugins.tracers._registry import get_registry as tracers

    return PluginHookScheduler({
        "parser":            parsers(),
        "framework_adapter": adapters(),
        "static_analyzer":   static_analyzers(),
        "demand_analyzer":   demand_analyzers(),
        "dynamic_analyzer":  dynamic_analyzers(),
        "evidence_producer": evidence(),
        "exporter":          exporters(),
        "tracer":            tracers(),
    })


def get_hook_scheduler() -> PluginHookScheduler:
    """Return the singleton PluginHookScheduler, with all plugins registered.

    Thread-safe via double-checked locking.  All built-in plugins are
    guaranteed to be registered before the scheduler is returned — calling
    :func:`ensure_all_plugins_registered` first is optional but harmless.
    """
    global _scheduler, _registration_done

    # Fast path — no lock needed once initialized.
    if _scheduler is not None:
        return _scheduler

    with _scheduler_lock:
        # Re-check under the lock (classic double-checked locking).
        if _scheduler is not None:
            return _scheduler

        # Ensure registrations happen before building the scheduler from the registries.
        with _registration_lock:
            if not _registration_done:
                _run_registrations()
                _registration_done = True

        sched = _build_scheduler()
        _logger.debug("all plugin families registered — firing on_registry_bootstrap")
        sched.fire("on_registry_bootstrap")
        _logger.debug("plugin bootstrap complete")
        _scheduler = sched
        return _scheduler


def ensure_all_plugins_registered() -> None:
    """Boot all built-in plugin families.

    Safe to call multiple times from any thread — registration runs exactly
    once per process lifetime (or after :func:`reset_hook_scheduler`).
    Calling this before :func:`get_hook_scheduler` is optional: the scheduler
    function guarantees registration on its own.
    """
    # Trigger scheduler construction which handles registration.
    get_hook_scheduler()


def reset_hook_scheduler() -> None:
    """Clear the scheduler singleton and reset registration state.

    Called by ``repograph clean`` and test teardown to reset plugin state.
    Acquires both locks so this cannot race with concurrent initialization
    or registration.
    """
    global _scheduler, _registration_done
    with _scheduler_lock:
        with _registration_lock:
            _scheduler = None
            _registration_done = False
