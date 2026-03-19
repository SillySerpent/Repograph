"""Stable Python library facade: :class:`RepoGraph`.

:class:`RepoGraph` is a thin wrapper over
:class:`~repograph.services.repo_graph_service.RepoGraphService`. Unresolved
attributes delegate with ``__getattr__``, so callers get ``sync``, ``pathways``,
``dead_code``, ``impact``, ``full_report``, etc., without importing the service
directly.

The CLI (:mod:`repograph.surfaces.cli`) and MCP server
(:mod:`repograph.surfaces.mcp.server`) use the same ``RepoGraphService``
implementation; MCP exposes a smaller tool set. See ``docs/SURFACES.md``.

Usage::

    from repograph.surfaces.api import RepoGraph

    rg = RepoGraph("/path/to/your/repo")

    # Index the repo (full rebuild)
    stats = rg.sync(full=True)

    # Unattended full sync against a repo that may have an attachable live server
    stats = rg.sync(full=True, attach_policy="never")

    # Query
    print(rg.status())
    print(rg.entry_points())
    print(rg.dead_code())
    print(rg.pathways())
    print(rg.get_pathway("my_flow"))
    print(rg.search("rate limiting middleware"))
    print(rg.impact("validate_credentials"))
    print(rg.node("src/services/auth.py"))
    print(rg.get_all_files())

    # Change a setting at runtime
    rg.set_config("auto_dynamic_analysis", True)
    rg.set_config("exclude_dirs", ["vendor", "node_modules"])
"""
from __future__ import annotations

from typing import Any

from repograph.runtime.session import RuntimeAttachPolicy

from repograph.services import RepoGraphService


class RepoGraph:
    """Stable high-level API wrapper around :class:`RepoGraphService`.

    Parameters
    ----------
    repo_path:
        Path to the repository root. Defaults to the current directory.
    repograph_dir:
        Where to store the RepoGraph index. Defaults to
        ``<repo_path>/.repograph``.
    include_git:
        Whether to include git coupling analysis. When omitted, the persisted
        RepoGraph setting is used.

    Examples
    --------
    Basic usage::

        with RepoGraph("/path/to/repo") as rg:
            rg.sync(full=True)
            print(rg.pathways())
            print(rg.dead_code())

    Change settings at runtime::

        rg = RepoGraph("/path/to/repo")
        rg.set_config("nl_model", "claude-opus-4-6")
        rg.set_config("exclude_dirs", ["vendor", "dist"])
    """

    def __init__(
        self,
        repo_path: str | None = None,
        repograph_dir: str | None = None,
        include_git: bool | None = None,
    ) -> None:
        self._service = RepoGraphService(
            repo_path=repo_path,
            repograph_dir=repograph_dir,
            include_git=include_git,
        )

    # ------------------------------------------------------------------
    # Settings access (primary configuration interface)
    # ------------------------------------------------------------------

    def get_config(self, key: str) -> Any:
        """Return the effective value of a setting.

        Parameters
        ----------
        key:
            Setting name (e.g. ``"auto_dynamic_analysis"``).
            Use ``list_config()`` to see all available keys.
        """
        from repograph.settings import get_setting
        return get_setting(self._service.repo_path, key)

    def set_config(self, key: str, value: Any) -> None:
        """Persist a runtime override in ``.repograph/settings.json``.

        Changes are immediate and persist across all future invocations.

        Parameters
        ----------
        key:
            Setting name (e.g. ``"exclude_dirs"``).
        value:
            New value. Must match the expected type for the setting.

        Examples
        --------
        ::

            rg.set_config("auto_dynamic_analysis", False)
            rg.set_config("nl_model", "claude-opus-4-6")
            rg.set_config("exclude_dirs", ["vendor", "node_modules"])
        """
        from repograph.settings import set_setting
        set_setting(self._service.repo_path, key, value)

    def describe_config(self, key: str | None = None) -> dict[str, Any] | list[dict[str, Any]]:
        """Return schema/lifecycle details for settings.

        Parameters
        ----------
        key:
            When provided, return metadata for one setting. When omitted, return
            metadata for all settings including current effective values,
            current source, and accepted value shapes.
        """
        from repograph.settings import describe_setting, list_setting_metadata

        if key is None:
            return list_setting_metadata(self._service.repo_path)
        return describe_setting(self._service.repo_path, key)

    def unset_config(self, key: str) -> None:
        """Remove a runtime override so YAML/default values apply again."""
        from repograph.settings import unset_setting

        unset_setting(self._service.repo_path, key)

    def list_config(self) -> dict[str, Any]:
        """Return all effective settings as a dict.

        Reflects the merged result of defaults, YAML overrides, and
        runtime changes (settings.json).
        """
        from repograph.settings import load_settings
        from dataclasses import asdict
        return asdict(load_settings(self._service.repo_path))

    def reset_config(self) -> None:
        """Clear runtime overrides while keeping the settings document."""
        from repograph.settings import reset_settings
        reset_settings(self._service.repo_path)

    def sync(
        self,
        *,
        full: bool = False,
        include_embeddings: bool | None = None,
        max_context_tokens: int | None = None,
        strict: bool = False,
        continue_on_error: bool = True,
        attach_policy: RuntimeAttachPolicy | None = None,
    ) -> dict[str, Any]:
        """Index or re-index the repository.

        Parameters
        ----------
        full:
            When true, run the full-power sync path. This can include automatic
            dynamic analysis when enabled by settings.
        attach_policy:
            Optional per-call override for how full sync handles an attachable
            live runtime target. Use ``"always"`` or ``"never"`` for unattended
            API use; the default ``"prompt"`` is mainly intended for CLI use.
        """
        return self._service.sync(
            full=full,
            include_embeddings=include_embeddings,
            max_context_tokens=max_context_tokens,
            strict=strict,
            continue_on_error=continue_on_error,
            attach_policy=attach_policy,
        )

    # ------------------------------------------------------------------
    # Delegation
    # ------------------------------------------------------------------

    def __getattr__(self, name: str) -> Any:
        return getattr(self._service, name)

    def __enter__(self) -> "RepoGraph":
        self._service.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        self._service.__exit__(*args)

    def __repr__(self) -> str:
        return f"RepoGraph(repo={self._service.repo_path!r})"
