"""Service-oriented helpers over the plugin system (not a plugin).

Use this module for:

- **Manifest introspection** — ``built_in_plugin_manifests()`` reads the live
  ``PluginHookScheduler`` after ``ensure_all_plugins_registered()``.
- **Ad-hoc execution** — ``run_*`` helpers call ``PluginHookScheduler.run_plugin``
  with the correct **kind** string (``static_analyzer``, ``demand_analyzer``,
  ``exporter``, ``evidence_producer``). Individual plugins still live under
  ``repograph.plugins.<family>/`` and register via ``discovery.py``.

Sync-time behaviour is unchanged: the pipeline still fires hooks from
``repograph.pipeline.runner``; this module is for API/service callers that need
to run a single plugin by id (e.g. ``RepoGraphService.run_analyzer_plugin``).
"""
from __future__ import annotations

from repograph.plugins.lifecycle import ensure_all_plugins_registered, get_hook_scheduler


def built_in_plugin_manifests() -> dict[str, list[dict]]:
    ensure_all_plugins_registered()
    manifests = get_hook_scheduler().manifests()
    demand = manifests["demand_analyzer"]
    return {
        "parsers": manifests["parser"],
        "framework_adapters": manifests["framework_adapter"],
        "static_analyzers": manifests["static_analyzer"],
        "demand_analyzers": demand,
        "evidence_producers": manifests["evidence_producer"],
        "exporters": manifests["exporter"],
        "tracers": manifests["tracer"],
        "dynamic_analyzers": manifests["dynamic_analyzer"],
    }


def run_static_analyzer(plugin_id: str, **kwargs):
    ensure_all_plugins_registered()
    return get_hook_scheduler().run_plugin("static_analyzer", plugin_id, **kwargs)


def run_analyzer(plugin_id: str, **kwargs):
    ensure_all_plugins_registered()
    return get_hook_scheduler().run_plugin("demand_analyzer", plugin_id, **kwargs)


def run_exporter(plugin_id: str, **kwargs):
    ensure_all_plugins_registered()
    return get_hook_scheduler().run_plugin("exporter", plugin_id, **kwargs)


def run_evidence_producer(plugin_id: str, **kwargs):
    ensure_all_plugins_registered()
    return get_hook_scheduler().run_plugin("evidence_producer", plugin_id, **kwargs)
