"""PluginHookScheduler — central lifecycle controller for all hook execution.

Usage
-----
    from repograph.core.plugin_framework import PluginHookScheduler

    scheduler = PluginHookScheduler(registries)

    # Fire a hook — all plugins that declared it receive the call.
    results = scheduler.fire("on_graph_built", store=store, config=config)

    # Run a single named plugin directly (bypasses hook matching).
    result = scheduler.run_plugin("static_analyzer", "static_analyzer.dead_code", service=svc)
"""
from __future__ import annotations

from dataclasses import dataclass
from heapq import heappop, heappush
from pathlib import Path
from typing import Any

from repograph.core.plugin_framework.contracts import (
    DemandAnalyzerPlugin,
    DynamicAnalyzerPlugin,
    EvidenceProducerPlugin,
    ExporterPlugin,
    FrameworkAdapterPlugin,
    HookName,
    ParserPlugin,
    RepoGraphPlugin,
    StaticAnalyzerPlugin,
    TracerPlugin,
)
from repograph.core.plugin_framework.registry import PluginRegistry


def _as_path(val: Any, *, name: str) -> Path:
    """Coerce hook kwargs to ``Path`` for typed plugin methods."""
    if val is None:
        raise TypeError(f"{name} is required for this hook")
    return val if isinstance(val, Path) else Path(val)


@dataclass(frozen=True)
class HookExecution:
    """Record of a single plugin invocation."""
    plugin_id: str
    plugin_kind: str
    hook: HookName
    result: Any
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class PluginHookScheduler:
    """Central lifecycle scheduler for plugin hook execution.

    The scheduler holds one PluginRegistry per plugin kind. When a hook is
    fired, it resolves the plugins that declared that hook, orders them using
    manifest ``order`` / ``after`` / ``before`` metadata, and calls the
    appropriate abstract method on each one.

    Dispatch uses :func:`_dispatch`, which selects the method by **hook name**
    and **concrete plugin ABC** (e.g. :class:`~repograph.core.plugin_framework.contracts.StaticAnalyzerPlugin`
    for ``on_graph_built``). See ``contracts.py`` for plugin kinds.

    Failures are isolated per-plugin: one bad plugin never blocks the others.
    Each plugin invocation is wrapped in try/except; errors are captured in
    the returned HookExecution.error field rather than propagated.
    """

    def __init__(self, registries: dict[str, PluginRegistry[Any]]) -> None:
        self._registries = registries

    @staticmethod
    def _canonical_kind(kind: str) -> str:
        return kind

    def fire(self, hook: HookName, *, kind: str | None = None, **kwargs: Any) -> list[HookExecution]:
        executions: list[HookExecution] = []
        for plugin in self._plugins_for_hook(hook, kind=kind):
            result = error = None
            try:
                result = self._dispatch(plugin, hook, kwargs)
            except Exception as exc:  # noqa: BLE001
                error = f"{type(exc).__name__}: {exc}"
            executions.append(HookExecution(
                plugin_id=plugin.plugin_id(),
                plugin_kind=plugin.manifest.kind,
                hook=hook,
                result=result,
                error=error,
            ))
        return executions

    def run_hook(self, hook: HookName, *, kind: str | None = None, **kwargs: Any) -> list[HookExecution]:
        return self.fire(hook, kind=kind, **kwargs)

    def run_plugin(self, kind: str, plugin_id: str, **kwargs: Any) -> Any:
        kind = self._canonical_kind(kind)
        registry = self._registries.get(kind)
        if registry is None:
            raise KeyError(f"No registry for kind '{kind}'")
        plugin = registry.get(plugin_id)
        if plugin is None:
            raise KeyError(f"Unknown {kind} plugin: '{plugin_id}'")
        return self._dispatch(plugin, self._default_hook_for_kind(kind), kwargs)

    def manifests(self) -> dict[str, list[dict]]:
        return {kind: registry.manifests() for kind, registry in self._registries.items()}

    def list_for_hook(self, hook: HookName, *, kind: str | None = None) -> list[RepoGraphPlugin]:
        return self._plugins_for_hook(hook, kind=kind)

    def _plugins_for_hook(self, hook: HookName, *, kind: str | None) -> list[RepoGraphPlugin]:
        kind = self._canonical_kind(kind) if kind is not None else None
        registries = (
            {kind: self._registries[kind]}
            if kind is not None and kind in self._registries
            else self._registries
        )
        result: list[RepoGraphPlugin] = []
        for registry in registries.values():
            for plugin in registry.all():
                if hook in plugin.manifest.hooks:
                    result.append(plugin)
        return self._ordered_plugins(result)

    @staticmethod
    def _ordered_plugins(plugins: list[RepoGraphPlugin]) -> list[RepoGraphPlugin]:
        if len(plugins) < 2:
            return plugins
        plugin_map = {plugin.plugin_id(): plugin for plugin in plugins}
        canonical = set(plugin_map)
        indegree = {plugin_id: 0 for plugin_id in canonical}
        outgoing = {plugin_id: set() for plugin_id in canonical}

        def add_edge(src: str, dst: str) -> None:
            if src == dst or src not in canonical or dst not in canonical:
                return
            bucket = outgoing[src]
            if dst in bucket:
                return
            bucket.add(dst)
            indegree[dst] += 1

        for plugin in plugins:
            for dep in plugin.manifest.after:
                if dep in canonical:
                    add_edge(dep, plugin.plugin_id())
            for dep in plugin.manifest.before:
                if dep in canonical:
                    add_edge(plugin.plugin_id(), dep)

        heap: list[tuple[int, str]] = []
        for plugin in plugins:
            if indegree[plugin.plugin_id()] == 0:
                heappush(heap, (plugin.manifest.order, plugin.plugin_id()))

        ordered_ids: list[str] = []
        while heap:
            _, plugin_id = heappop(heap)
            ordered_ids.append(plugin_id)
            for nxt in sorted(outgoing[plugin_id]):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    plugin = plugin_map[nxt]
                    heappush(heap, (plugin.manifest.order, nxt))

        if len(ordered_ids) != len(plugins):
            return sorted(plugins, key=lambda plugin: (plugin.manifest.order, plugin.plugin_id()))
        return [plugin_map[plugin_id] for plugin_id in ordered_ids]

    @staticmethod
    def _dispatch(plugin: RepoGraphPlugin, hook: HookName, kwargs: dict[str, Any]) -> Any:
        if hook == "on_file_parsed" and isinstance(plugin, ParserPlugin):
            return plugin.parse_file(**kwargs)
        if hook == "on_file_parsed" and isinstance(plugin, FrameworkAdapterPlugin):
            return plugin.inspect(**kwargs)
        if hook == "on_graph_built" and isinstance(plugin, StaticAnalyzerPlugin):
            return plugin.analyze(**kwargs)
        if hook == "on_analysis" and isinstance(plugin, DemandAnalyzerPlugin):
            return plugin.analyze(**kwargs)
        if hook == "on_evidence" and isinstance(plugin, EvidenceProducerPlugin):
            return plugin.produce(**kwargs)
        if hook == "on_export" and isinstance(plugin, ExporterPlugin):
            return plugin.export(**kwargs)
        if hook == "on_traces_collected" and isinstance(plugin, DynamicAnalyzerPlugin):
            trace_dir = _as_path(kwargs.get("trace_dir"), name="trace_dir")
            store = kwargs.get("store")
            rest = {k: v for k, v in kwargs.items() if k not in ("trace_dir", "store")}
            return plugin.analyze_traces(trace_dir, store, **rest)
        if hook == "on_tracer_install" and isinstance(plugin, TracerPlugin):
            repo_root = _as_path(kwargs.get("repo_root"), name="repo_root")
            trace_dir = _as_path(kwargs.get("trace_dir"), name="trace_dir")
            return plugin.install(
                repo_root,
                trace_dir,
                **{k: v for k, v in kwargs.items() if k not in ("repo_root", "trace_dir")},
            )
        if hook == "on_tracer_collect" and isinstance(plugin, TracerPlugin):
            trace_dir = _as_path(kwargs.get("trace_dir"), name="trace_dir")
            return plugin.collect(
                trace_dir,
                **{k: v for k, v in kwargs.items() if k != "trace_dir"},
            )
        if hook in ("on_registry_bootstrap", "on_files_discovered", "on_traces_analyzed", "on_export"):
            return None
        raise TypeError(
            f"Plugin {plugin.plugin_id()!r} declared hook {hook!r} "
            f"but no matching method was found on {type(plugin).__name__}"
        )

    @staticmethod
    def _default_hook_for_kind(kind: str) -> HookName:
        mapping: dict[str, HookName] = {
            "framework_adapter": "on_file_parsed",
            "evidence_producer": "on_evidence",
            "static_analyzer":   "on_graph_built",
            "demand_analyzer":   "on_analysis",
            "exporter":          "on_export",
            "parser":            "on_file_parsed",
            "dynamic_analyzer":  "on_traces_collected",
            "tracer":            "on_tracer_install",
        }
        if kind not in mapping:
            raise KeyError(f"No default hook for plugin kind '{kind}'")
        return mapping[kind]
