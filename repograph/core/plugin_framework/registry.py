from __future__ import annotations

from typing import Generic, TypeVar

from repograph.core.plugin_framework.contracts import RepoGraphPlugin

T = TypeVar("T", bound=RepoGraphPlugin)


class PluginRegistry(Generic[T]):
    """Simple, namespaced registry for RepoGraph plugin types.

    Canonical plugin IDs live in ``plugin.manifest.id``. Optional
    ``manifest.aliases`` provide compatibility entry points that resolve back
    to the canonical plugin without polluting manifest listings.
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._plugins: dict[str, T] = {}
        self._aliases: dict[str, str] = {}

    def register(self, plugin: T, *, replace: bool = False) -> None:
        plugin_id = plugin.plugin_id()
        if plugin_id in self._plugins and not replace:
            raise ValueError(f"{self.kind} plugin '{plugin_id}' already registered")
        if replace and plugin_id in self._plugins:
            self._remove_aliases_for(plugin_id)
        self._plugins[plugin_id] = plugin
        for alias in getattr(plugin.manifest, "aliases", ()):
            owner = self._aliases.get(alias)
            if owner is not None and owner != plugin_id and not replace:
                raise ValueError(
                    f"{self.kind} plugin alias '{alias}' already registered to '{owner}'"
                )
            self._aliases[alias] = plugin_id

    def get(self, plugin_id: str) -> T | None:
        canonical = self.resolve_id(plugin_id)
        if canonical is None:
            return None
        return self._plugins.get(canonical)

    def resolve_id(self, plugin_id: str) -> str | None:
        if plugin_id in self._plugins:
            return plugin_id
        return self._aliases.get(plugin_id)

    def aliases_for(self, plugin_id: str) -> list[str]:
        canonical = self.resolve_id(plugin_id)
        if canonical is None:
            return []
        return [alias for alias, owner in self._aliases.items() if owner == canonical]

    def all(self) -> list[T]:
        return list(self._plugins.values())

    def manifests(self) -> list[dict]:
        return [plugin.manifest.as_dict() for plugin in self.all()]

    def ids(self) -> list[str]:
        return list(self._plugins.keys())

    def _remove_aliases_for(self, plugin_id: str) -> None:
        stale = [alias for alias, owner in self._aliases.items() if owner == plugin_id]
        for alias in stale:
            self._aliases.pop(alias, None)

    def __contains__(self, plugin_id: str) -> bool:
        return self.resolve_id(plugin_id) is not None

    def __len__(self) -> int:
        return len(self._plugins)
