"""Stable Python library facade: :class:`RepoGraph`.

:class:`RepoGraph` is a thin wrapper over
:class:`~repograph.services.repo_graph_service.RepoGraphService`. Unresolved
attributes delegate with ``__getattr__``, so callers get ``sync``, ``pathways``,
``dead_code``, ``impact``, ``full_report``, etc., without importing the service
directly.

The CLI (:mod:`repograph.cli`) and MCP server (:mod:`repograph.mcp.server`) use
the same ``RepoGraphService`` implementation; MCP exposes a smaller tool set.
See ``docs/SURFACES.md``.
"""
from __future__ import annotations

from typing import Any

from repograph.services import RepoGraphService


class RepoGraph:
    """Stable high-level API wrapper around :class:`RepoGraphService`."""

    def __init__(self, repo_path: str | None = None, repograph_dir: str | None = None, include_git: bool | None = None) -> None:
        self._service = RepoGraphService(
            repo_path=repo_path,
            repograph_dir=repograph_dir,
            include_git=include_git,
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._service, name)

    def __enter__(self) -> "RepoGraph":
        self._service.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        self._service.__exit__(*args)

    def __repr__(self) -> str:
        return f"RepoGraph(repo={self._service.repo_path!r})"
